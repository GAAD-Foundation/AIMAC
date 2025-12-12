"""Test helper for batch screenshot generation.

This module contains screenshot_batch(), a test utility that was moved out of
production code (src/aimac/screenshotter.py) because it's only used in tests.

Production use goes through executor.py's streaming worker model instead.
"""

from __future__ import annotations

import asyncio
import os

try:
    from playwright.async_api import BrowserContext, async_playwright
except ImportError:
    BrowserContext = None  # type: ignore
    async_playwright = None  # type: ignore

from aimac.screenshotter import AXE_ERROR_REASONS, CANONICAL_VIEWPORT, screenshot_and_axe
from aimac.utils import compute_percentiles, get_env_int


async def screenshot_batch(html_paths: list[tuple[str, str]]) -> dict:
    """Batch screenshot generation for tests and standalone development.

    Processes multiple HTML files in parallel using a shared browser instance
    and multiple contexts. Production use goes through executor.py's streaming
    worker model instead; this function is primarily for testing screenshot_and_axe()
    in isolation.

    Args:
        html_paths: List of (html_path, png_path) tuples to process.

    Returns:
        Dict with keys:
            - total: Total items processed
            - succeeded: Screenshot succeeded (includes skipped)
            - failed: Screenshot failed
            - skipped: Both PNG and axe.json already existed
            - axe_total: Items where axe could run
            - axe_succeeded: Axe analyses that completed successfully
            - axe_failed: Axe analyses that failed
            - timing_ms: Percentiles dict (p50_ms, p95_ms, p99_ms)
            - axe_timing_ms: Axe inject/run timing percentiles

    Raises:
        ImportError: If Playwright is not installed.
    """
    if async_playwright is None:
        # Signal to caller/tests that Playwright is not available
        raise ImportError("Playwright not installed")

    total = len(html_paths)
    if total == 0:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "axe_succeeded": 0,
            "axe_failed": 0,
        }

    timeout_ms = get_env_int("SCREENSHOT_TIMEOUT_MS", 10000)
    wait_images_ms = get_env_int("SCREENSHOT_WAIT_IMAGES_MS", 3000)
    wait_fonts_ms = get_env_int("SCREENSHOT_WAIT_FONTS_MS", 2000)
    progress_every = max(1, get_env_int("SCREENSHOT_PROGRESS_EVERY", 10))

    cpu = os.cpu_count() or 4
    max_contexts = min(8, max(2, cpu // 2))
    max_concurrent = min(total, max_contexts * 4)

    succeeded = 0
    failed = 0
    skipped = 0
    axe_total = 0
    axe_succeeded = 0
    axe_failed = 0
    processed = 0

    durations_ms: list[float] = []
    inject_times: list[float] = []
    run_times: list[float] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            contexts = [
                await browser.new_context(viewport=CANONICAL_VIEWPORT)
                for _ in range(max_contexts)
            ]
            sem = asyncio.Semaphore(max_concurrent)
            tasks: list[asyncio.Task] = []

            for i, (html_path, png_path) in enumerate(html_paths):
                context = contexts[i % len(contexts)]

                async def runner(ctx: BrowserContext = context, hp: str = html_path, pp: str = png_path):
                    async with sem:
                        return await screenshot_and_axe(
                            ctx, hp, pp,
                            timeout_ms=timeout_ms,
                            wait_images_ms=wait_images_ms,
                            wait_fonts_ms=wait_fonts_ms,
                        )

                tasks.append(asyncio.create_task(runner()))

            for t in asyncio.as_completed(tasks):
                result = await t
                status, screenshot_ok, axe_ok, elapsed_ms, inj_ms, run_ms, _axe_path, reason = result
                processed += 1
                if status == "skipped":
                    skipped += 1
                    succeeded += 1
                elif status == "ok":
                    succeeded += 1
                    durations_ms.append(elapsed_ms)
                else:
                    failed += 1

                # Track axe metrics - only count when axe could run
                if screenshot_ok or status == "skipped":
                    axe_total += 1
                    if axe_ok:
                        axe_succeeded += 1
                    elif reason in AXE_ERROR_REASONS:
                        axe_failed += 1

                if inj_ms and inj_ms > 0:
                    inject_times.append(inj_ms)
                if run_ms and run_ms > 0:
                    run_times.append(run_ms)

                if (processed % progress_every) == 0 or processed == total:
                    print(f"  Screenshots progress: {processed}/{total}")
        finally:
            await browser.close()

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "timing_ms": compute_percentiles(durations_ms),
        "axe_total": axe_total,
        "axe_succeeded": axe_succeeded,
        "axe_failed": axe_failed,
        "axe_timing_ms": {
            "inject_p50": compute_percentiles(inject_times).get("p50_ms", 0.0),
            "inject_p95": compute_percentiles(inject_times).get("p95_ms", 0.0),
            "run_p50": compute_percentiles(run_times).get("p50_ms", 0.0),
            "run_p95": compute_percentiles(run_times).get("p95_ms", 0.0),
        },
    }
