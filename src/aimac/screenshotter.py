"""Screenshot and axe-core accessibility analysis using Playwright.

Generates PNG screenshots and runs axe-core WCAG analysis on LLM-generated HTML.
Entry point:
- screenshot_and_axe(): Single-item analysis, called by executor.py worker loop

Design notes:
- Axe failures are non-fatal: screenshot succeeds even if axe analysis fails
- Idempotent: skips if PNG, axe.json, and axe_runs DB row all exist
- Axe injection: requires vendored axe.min.js (no CDN fallback)
- WCAG focus: only runs WCAG 2.x A/AA rules (no best-practices or experimental)

See also:
- src/aimac/executor.py - calls screenshot_and_axe() in worker loop
- src/aimac/axe_scorer.py - scoring algorithm for axe results
- src/aimac/database/_axe.py - persists axe results to database
- src/aimac/vendor/axe.min.js - vendored axe-core library
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import time
from typing import NamedTuple

try:
    from playwright.async_api import BrowserContext, Page, async_playwright
except ImportError:  # Playwright is optional
    BrowserContext = None  # type: ignore
    Page = None  # type: ignore
    async_playwright = None  # type: ignore

from .axe_scorer import score_axe_results
from .database import axe_run_exists, insert_axe_run
from .utils import compute_percentiles, get_env_int

# Standard viewport for consistent screenshot dimensions across all models.
# 1280x720 captures above-the-fold content typical of web pages.
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720
CANONICAL_VIEWPORT = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}

# Axe-specific error reasons (screenshot succeeded but axe failed)
# Duplicated from executor.py to avoid circular imports
AXE_ERROR_REASONS = frozenset({
    "axe_not_present",
    "axe_inject_timeout",
    "axe_db_error",
    "axe_runtime_error",
    "axe_db_missing",  # skip path: files exist but axe_runs row missing
})

# Preflight check: fail fast at import if vendor file missing (deployment issue)
_AXE_VENDOR_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
if not _AXE_VENDOR_PATH.exists():
    raise FileNotFoundError(
        f"axe.min.js not found at {_AXE_VENDOR_PATH}. See vendor/README.txt."
    )

logger = logging.getLogger(__name__)


async def _wait_for_images(page: Page, max_wait_ms: int = 3000) -> None:
    """Wait for <img> elements to finish loading.

    Non-fatal: continues after timeout to avoid blocking generation.
    """
    try:
        await page.wait_for_function(
            """
            () => {
              const imgs = Array.from(document.images || []);
              if (imgs.length === 0) return true;
              return imgs.every(img => img.complete && img.naturalWidth > 0);
            }
            """,
            timeout=max_wait_ms,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Proceed even if images never reach a settled state
        pass


async def _wait_for_fonts(page: Page, max_wait_ms: int = 2000) -> None:
    """Wait for web fonts to be ready via document.fonts.ready.

    Non-fatal: continues after timeout to avoid blocking generation.
    """
    try:
        await page.wait_for_function(
            "() => document.fonts.ready.then(() => true)",
            timeout=max_wait_ms,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Proceed even if fonts aren't ready (timeout or other error)
        pass


async def _navigate_and_wait(
    page: Page,
    html_path: str,
    timeout_ms: int,
    wait_images_ms: int,
    wait_fonts_ms: int,
) -> None:
    """Navigate to HTML file and wait for assets.

    Raises on navigation failure. Caller is responsible for page lifecycle.
    """
    await page.goto(
        f"file://{Path(html_path).resolve()}",
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )
    await _wait_for_images(page, max_wait_ms=wait_images_ms)
    await _wait_for_fonts(page, max_wait_ms=wait_fonts_ms)


async def _run_axe(page: Page, axe_json_path: str, html_path: str) -> tuple[bool, float, str | None]:
    """Run axe accessibility scan and save results.

    Returns (axe_ok, run_ms, reason_or_none).
    reason is set if axe_ok is False: 'axe_runtime_error' or 'axe_db_error'.

    Exception handling is intentionally narrow:
    - axe.run() JS execution: caught, returns 'axe_runtime_error'
    - DB insert: caught, returns 'axe_db_error'
    - Data transformation (scoring, dict ops): NOT caught - bugs should crash
    """
    import json as _json
    import time as _t

    # Run axe in browser - this is the external boundary that can fail
    try:
        run0 = _t.monotonic()
        axe_results = await page.evaluate(
            """
            async () => {
                return await axe.run({
                    runOnly: {
                        type: 'tag',
                        values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22a','wcag22aa']
                    },
                    resultTypes: ['violations']
                });
            }
            """
        )
        run1 = _t.monotonic()
        run_ms = (run1 - run0) * 1000.0
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Axe runtime error for %s: %s", html_path, e, exc_info=True)
        return (False, 0.0, "axe_runtime_error")

    # Write filtered JSON report (file I/O - let errors propagate as programming bugs)
    Path(axe_json_path).parent.mkdir(parents=True, exist_ok=True)
    filtered_results = {
        "testEngine": axe_results.get("testEngine"),
        "testRunner": axe_results.get("testRunner"),
        "testEnvironment": axe_results.get("testEnvironment"),
        "timestamp": axe_results.get("timestamp"),
        "url": axe_results.get("url"),
        "toolOptions": axe_results.get("toolOptions"),
        "violations": axe_results.get("violations", []),
    }
    with open(axe_json_path, "w", encoding="utf-8") as f:
        _json.dump(filtered_results, f, indent=2)

    # Parse request_pk from filename - let ValueError propagate (invalid filename is a bug)
    request_pk = int(Path(html_path).stem)

    # Score and extract data (pure transformation - bugs should crash, not be hidden)
    score = score_axe_results(axe_results)
    rule_breakdown: dict[str, int] = {}
    rule_metadata: dict[str, dict[str, str | None]] = {}
    for v in axe_results.get("violations", []):
        rule_id = v.get("id")
        if not rule_id:
            continue
        node_count = len(v.get("nodes", []))
        if node_count > 0:
            rule_breakdown[rule_id] = rule_breakdown.get(rule_id, 0) + node_count
        if rule_id not in rule_metadata:
            rule_metadata[rule_id] = {
                "help": (v.get("help") or "").strip() or None,
                "help_url": (v.get("helpUrl") or "").strip() or None,
            }
    axe_engine = axe_results.get("testEngine") or {}
    axe_version = (axe_engine.get("version") or "").strip() or None

    # DB insert - the only operation that should be caught as 'axe_db_error'
    try:
        insert_axe_run(
            request_pk=request_pk,
            total_violations=score["total_violations"],
            critical_violations=score["critical_violations"],
            serious_violations=score["serious_violations"],
            weighted_score=score["weighted_score"],
            axe_json_path=axe_json_path,
            rule_breakdown=rule_breakdown,
            rule_metadata=rule_metadata,
            axe_version=axe_version,
        )
        return (True, run_ms, None)
    except Exception as e:
        logger.error("Failed to insert axe run for %s: %s", html_path, e, exc_info=True)
        return (False, run_ms, "axe_db_error")


async def _inject_axe(page: Page) -> tuple[bool, float, str | None]:
    """Inject axe-core into the page if not already present.

    Returns (axe_present, inject_ms, reason_or_none).
    reason is set if axe_present is False: 'axe_not_present' or 'axe_inject_timeout'.
    """
    import time as _t

    # Check if axe is already present via context init script
    axe_present = False
    try:
        await page.wait_for_function("() => typeof axe !== 'undefined'", timeout=2000)
        axe_present = True
    except asyncio.CancelledError:
        raise
    except Exception:
        axe_present = False

    if axe_present:
        return (True, 0.0, None)

    # Inject axe from local vendor file (preflight check at module load ensures it exists)
    injected = False
    inj0 = _t.monotonic()
    try:
        await page.add_script_tag(path=str(_AXE_VENDOR_PATH.resolve()))
        injected = True
    except asyncio.CancelledError:
        raise
    except Exception:
        injected = False
    inj1 = _t.monotonic()
    inject_ms = (inj1 - inj0) * 1000.0 if injected else 0.0

    # Check again after injection
    if injected:
        try:
            await page.wait_for_function("() => typeof axe !== 'undefined'", timeout=2000)
            axe_present = True
        except asyncio.CancelledError:
            raise
        except Exception:
            axe_present = False

    if not axe_present:
        reason = "axe_not_present" if injected else "axe_inject_timeout"
        return (False, inject_ms, reason)

    return (True, inject_ms, None)


def _cleanup_partial_files(png_path: str, axe_path: str) -> None:
    """Remove partial/incomplete files before retry.

    Best effort - if cleanup fails, the actual write step will fail too.
    """
    for path in (png_path, axe_path):
        if Path(path).exists():
            try:
                Path(path).unlink()
            except Exception:
                pass  # Race condition or permission issue - write will fail if real problem


def _make_result(
    status: str,
    elapsed_ms: float,
    *,
    screenshot_ok: bool = False,
    axe_ok: bool = False,
    inject_ms: float = 0.0,
    run_ms: float = 0.0,
    axe_path: str | None = None,
    reason: str | None = None,
) -> AnalysisResult:
    """Build an AnalysisResult with sensible defaults."""
    return AnalysisResult(
        status=status,
        screenshot_ok=screenshot_ok,
        axe_ok=axe_ok,
        elapsed_ms=elapsed_ms,
        inject_ms=inject_ms,
        run_ms=run_ms,
        axe_path=axe_path,
        reason=reason,
    )


class AnalysisResult(NamedTuple):
    """Return type for screenshot_and_axe() to keep executor logic readable.

    status: "ok" (screenshot succeeded), "skipped" (cached), "failed" (error)
    screenshot_ok: True if PNG was created (or cached)
    axe_ok: True if axe analysis succeeded and was persisted to DB
    elapsed_ms: Total wall-clock time for this item
    inject_ms: Time spent injecting axe-core (0 if pre-injected via context)
    run_ms: Time spent running axe.run() analysis
    axe_path: Path to axe.json if created, None otherwise
    reason: Short error code if failed (e.g., "playwright_timeout", "axe_db_error")
    """

    status: str
    screenshot_ok: bool
    axe_ok: bool
    elapsed_ms: float
    inject_ms: float
    run_ms: float
    axe_path: str | None
    reason: str | None


async def screenshot_and_axe(
    context: BrowserContext,
    html_path: str,
    png_path: str,
    *,
    timeout_ms: int,
    wait_images_ms: int,
    wait_fonts_ms: int,
) -> AnalysisResult:
    """Create a screenshot and run axe accessibility analysis for a single HTML file.

    Idempotent: skips if both PNG and axe.json exist AND axe_runs DB row exists.
    Axe failures are non-fatal - screenshot can succeed even if axe analysis fails.

    Args:
        context: Playwright BrowserContext to create page from.
        html_path: Absolute path to HTML file to analyze.
        png_path: Absolute path where screenshot PNG should be saved.
        timeout_ms: Navigation timeout in milliseconds.
        wait_images_ms: Max time to wait for images to load (non-fatal if timeout).
        wait_fonts_ms: Max time to wait for fonts to load (non-fatal if timeout).

    Returns:
        AnalysisResult with status ("ok", "skipped", "failed"), success flags,
        timing metrics, and optional error reason code.

    Raises:
        Exception: Browser setup failures (context.new_page) propagate to caller.
        asyncio.CancelledError: If task is cancelled during execution.
    """
    start = time.monotonic()
    axe_path = str(Path(html_path).with_suffix(".axe.json"))

    # Idempotency fast-path: only skip if BOTH png and axe exist on disk
    # AND the axe_runs DB row exists (files alone are not authoritative)
    png_exists = Path(png_path).exists()
    axe_exists = Path(axe_path).exists()

    if png_exists and axe_exists:
        # Derive request PK from filename (e.g., "12345.html" -> 12345)
        try:
            request_pk = int(Path(html_path).stem)
            db_has_axe = axe_run_exists(request_pk)
        except (ValueError, TypeError):
            # Non-numeric filename (e.g., test files) - can't verify DB
            db_has_axe = False

        elapsed_ms = (time.monotonic() - start) * 1000.0
        if db_has_axe:
            # Both disk and DB agree - safe to skip
            return _make_result("skipped", elapsed_ms, screenshot_ok=True, axe_ok=True, axe_path=axe_path)
        else:
            # Files exist but DB row is missing - treat axe as failed
            # Tier-2 will see this pair as missing and can re-run it
            return _make_result(
                "skipped", elapsed_ms,
                screenshot_ok=True, axe_ok=False,
                axe_path=axe_path,
                reason="axe_db_missing",
            )

    # Clean up partial/incomplete files before retry
    _cleanup_partial_files(png_path, axe_path)

    if not Path(html_path).exists():
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return _make_result("failed", elapsed_ms, reason="html_not_found")

    # Create page OUTSIDE try - browser setup failures propagate to caller
    page = await context.new_page()

    axe_ok = False
    inject_ms = 0.0
    run_ms = 0.0
    reason: str | None = None
    try:
        # Navigate and wait for assets
        await _navigate_and_wait(page, html_path, timeout_ms, wait_images_ms, wait_fonts_ms)

        # Take screenshot (same try block as navigation - share TimeoutError check)
        Path(png_path).parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=png_path)

        # Axe: non-fatal
        try:
            axe_present, inject_ms, inject_reason = await _inject_axe(page)
            if not axe_present:
                reason = inject_reason
            else:
                axe_ok, run_ms, run_reason = await _run_axe(page, axe_path, html_path)
                if not axe_ok:
                    reason = run_reason
        except asyncio.CancelledError:
            raise
        # No broad except here - _inject_axe and _run_axe handle their own exceptions
        # and return status codes. Programming errors should crash, not be hidden.

        elapsed_ms = (time.monotonic() - start) * 1000.0
        return _make_result(
            "ok", elapsed_ms,
            screenshot_ok=True, axe_ok=axe_ok,
            inject_ms=inject_ms, run_ms=run_ms,
            axe_path=axe_path if axe_ok else None,
            reason=reason if not axe_ok else None,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Navigation or screenshot failure - check for Playwright timeout
        elapsed_ms = (time.monotonic() - start) * 1000.0
        reason_code = "screenshot_error"
        try:
            from playwright.async_api import TimeoutError as PwTimeout
            if isinstance(e, PwTimeout):
                reason_code = "playwright_timeout"
        except Exception:
            pass
        return _make_result("failed", elapsed_ms, reason=reason_code)
    finally:
        try:
            await page.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
