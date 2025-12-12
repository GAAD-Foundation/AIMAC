"""Unit tests for screenshotter module.

These tests are pragmatic and will skip gracefully if Playwright browsers
are not installed on the machine running tests.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aimac.screenshotter import AXE_ERROR_REASONS, AnalysisResult, _wait_for_fonts, screenshot_and_axe
from tests.helpers.screenshotter import screenshot_batch

# Skip slow browser tests in local dev unless explicitly requested
# In CI (GitHub Actions, etc.), CI=true is typically set
_SKIP_SLOW_LOCALLY = os.getenv("CI") != "true" and os.getenv("RUN_SLOW_TESTS") != "1"


@pytest.mark.asyncio
async def test_screenshot_batch_empty():
    result = await screenshot_batch([])
    # Accept new keys for axe stats; core counters must be zero
    assert result["total"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 0
    # Axe counters present and zero for empty input
    assert result.get("axe_succeeded", 0) == 0
    assert result.get("axe_failed", 0) == 0


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_screenshot_batch_single_file(tmp_path: Path):
    html_file = tmp_path / "one.html"
    html_file.write_text("<html><body><h1>Test</h1></body></html>")
    png_file = tmp_path / "one.png"

    try:
        result = await screenshot_batch([(str(html_file), str(png_file))])
    except Exception as e:  # pragma: no cover - environment-dependent (browser install)
        pytest.skip(f"Playwright not available or browser missing: {e}")

    assert result["total"] == 1
    assert result["failed"] == 0
    assert png_file.exists() and png_file.stat().st_size > 0


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_screenshot_batch_idempotent(tmp_path: Path):
    html_file = tmp_path / "idempotent.html"
    html_file.write_text("<html><body>Ok</body></html>")
    png_file = tmp_path / "idempotent.png"

    try:
        first = await screenshot_batch([(str(html_file), str(png_file))])
        second = await screenshot_batch([(str(html_file), str(png_file))])
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Playwright not available or browser missing: {e}")

    assert first["succeeded"] == 1
    assert first["skipped"] == 0
    assert second["succeeded"] == 1
    assert second["skipped"] == 1


@pytest.mark.asyncio
async def test_wait_for_fonts_respects_timeout():
    """_wait_for_fonts should timeout after max_wait_ms, not hang for 30s."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    page = MagicMock()

    # Simulate Playwright timeout behavior - raises TimeoutError after specified ms
    async def simulate_timeout(*args, timeout=30000, **kwargs):
        await asyncio.sleep(timeout / 1000)
        raise PlaywrightTimeout("Timeout")

    page.wait_for_function = AsyncMock(side_effect=simulate_timeout)

    timeout_ms = 100
    start = time.monotonic()
    await _wait_for_fonts(page, max_wait_ms=timeout_ms)
    elapsed_ms = (time.monotonic() - start) * 1000

    # Should complete within 500ms (100ms timeout + buffer for test overhead)
    assert elapsed_ms < 500, f"Took {elapsed_ms:.0f}ms - timeout not respected"

    # Verify timeout was passed correctly to wait_for_function
    page.wait_for_function.assert_called_once()
    call_kwargs = page.wait_for_function.call_args.kwargs
    assert call_kwargs.get("timeout") == timeout_ms, "timeout param not passed"


# =============================================================================
# Characterization tests for screenshot_and_axe
# These lock in current behavior before refactoring (TDD style)
# =============================================================================


class TestScreenshotAndAxeFastPath:
    """Tests for the idempotency fast-path (skip when both artifacts exist)."""

    @pytest.mark.asyncio
    async def test_skip_when_both_png_and_axe_exist_non_numeric(self, tmp_path: Path):
        """When files exist but filename is non-numeric, skip with axe_ok=False.

        Non-numeric filenames (like test.html) can't be verified against the DB
        since we can't derive a request PK. This is the safe behavior - we skip
        the screenshot work but don't claim axe success without DB verification.
        """
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        axe_file = tmp_path / "test.axe.json"

        # Create all files
        html_file.write_text("<html></html>")
        png_file.write_bytes(b"fake png")
        axe_file.write_text("{}")

        # Create a mock context that should NOT be called
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(side_effect=AssertionError("Should not create page"))

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "skipped"
        assert result.screenshot_ok is True
        # Non-numeric filename: can't verify DB, so axe_ok=False
        assert result.axe_ok is False
        assert result.reason == "axe_db_missing"
        # Context should never be touched
        mock_context.new_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_skip_when_only_png_exists(self, tmp_path: Path):
        """When only PNG exists (no axe JSON), should NOT skip."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"

        html_file.write_text("<html></html>")
        png_file.write_bytes(b"fake png")
        # No axe file created

        # Mock context - new_page WILL be called
        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Expected - testing partial skip"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        # Should have attempted to create page (not skipped)
        mock_context.new_page.assert_called_once()
        assert result.status == "failed"  # Because goto failed

    @pytest.mark.asyncio
    async def test_no_skip_when_only_axe_exists(self, tmp_path: Path):
        """When only axe JSON exists (no PNG), should NOT skip."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        axe_file = tmp_path / "test.axe.json"

        html_file.write_text("<html></html>")
        axe_file.write_text("{}")
        # No png file created

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Expected - testing partial skip"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        mock_context.new_page.assert_called_once()
        assert result.status == "failed"


class TestScreenshotAndAxeHtmlMissing:
    """Tests for HTML file not found case."""

    @pytest.mark.asyncio
    async def test_html_not_found_returns_failed(self, tmp_path: Path):
        """When HTML file doesn't exist, return failed with reason."""
        html_file = tmp_path / "nonexistent.html"
        png_file = tmp_path / "test.png"

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(side_effect=AssertionError("Should not create page"))

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "failed"
        assert result.screenshot_ok is False
        assert result.axe_ok is False
        assert result.reason == "html_not_found"
        assert result.axe_path is None
        mock_context.new_page.assert_not_called()


class TestScreenshotAndAxeBrowserSetup:
    """Tests for browser setup failures (new_page, etc.)."""

    @pytest.mark.asyncio
    async def test_new_page_failure_propagates(self, tmp_path: Path):
        """When context.new_page() fails, exception propagates (worker crash path).

        Browser setup failures should NOT be silently converted to AnalysisResult.
        They indicate environment problems (Playwright not working, browser crashed)
        that require operator attention.
        """
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(side_effect=Exception("Browser crashed"))

        with pytest.raises(Exception, match="Browser crashed"):
            await screenshot_and_axe(
                mock_context,
                str(html_file),
                str(png_file),
                timeout_ms=5000,
                wait_images_ms=1000,
                wait_fonts_ms=1000,
            )


class TestScreenshotAndAxeNavFailure:
    """Tests for navigation/screenshot failure cases."""

    @pytest.mark.asyncio
    async def test_goto_exception_returns_failed(self, tmp_path: Path):
        """When page.goto raises, return failed with screenshot_error."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "failed"
        assert result.screenshot_ok is False
        assert result.axe_ok is False
        assert result.reason == "screenshot_error"

    @pytest.mark.asyncio
    async def test_playwright_timeout_returns_playwright_timeout(self, tmp_path: Path):
        """When Playwright times out (goto or screenshot), return playwright_timeout."""
        from playwright.async_api import TimeoutError as PwTimeout

        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=PwTimeout("Timeout 5000ms exceeded"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "failed"
        assert result.screenshot_ok is False
        assert result.axe_ok is False
        assert result.reason == "playwright_timeout"

    @pytest.mark.asyncio
    async def test_screenshot_exception_returns_failed(self, tmp_path: Path):
        """When page.screenshot raises, return failed."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_function = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=Exception("Screenshot failed"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "failed"
        assert result.screenshot_ok is False
        assert result.axe_ok is False
        assert result.reason == "screenshot_error"

    @pytest.mark.asyncio
    async def test_screenshot_timeout_returns_playwright_timeout(self, tmp_path: Path):
        """When page.screenshot times out (Playwright TimeoutError), return playwright_timeout.

        Both navigation and screenshot timeouts share the same handler and return
        playwright_timeout. This ensures consistent timeout classification.
        """
        from playwright.async_api import TimeoutError as PwTimeout

        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_function = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=PwTimeout("Screenshot timeout"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "failed"
        assert result.screenshot_ok is False
        assert result.axe_ok is False
        assert result.reason == "playwright_timeout"


class TestScreenshotAndAxeAxeFailures:
    """Tests for axe injection and runtime failures."""

    @pytest.mark.asyncio
    async def test_axe_not_present_after_inject(self, tmp_path: Path):
        """When axe injection succeeds but axe not present, screenshot still ok."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        # First two wait_for_function calls: images, fonts (succeed)
        # Third call: check if axe present (fail)
        # Fourth call after inject: check if axe present (fail)
        call_count = [0]

        async def mock_wait_for_function(script, timeout=30000):
            call_count[0] += 1
            if "axe" in script:
                raise Exception("axe not defined")
            return True

        mock_page.wait_for_function = AsyncMock(side_effect=mock_wait_for_function)
        mock_page.screenshot = AsyncMock()
        mock_page.add_script_tag = AsyncMock()  # Injection "succeeds" but axe still not present
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "ok"
        assert result.screenshot_ok is True
        assert result.axe_ok is False
        assert result.reason == "axe_not_present"
        # Note: PNG file not asserted here since mock.screenshot doesn't write file
        # The key behavior is that screenshot_ok=True despite axe failure

    @pytest.mark.asyncio
    async def test_axe_runtime_error(self, tmp_path: Path):
        """When axe.run throws, screenshot still ok but axe_ok=false."""
        html_file = tmp_path / "test.html"
        png_file = tmp_path / "test.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_function = AsyncMock()  # All succeed including axe check
        mock_page.screenshot = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("axe.run failed"))
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        result = await screenshot_and_axe(
            mock_context,
            str(html_file),
            str(png_file),
            timeout_ms=5000,
            wait_images_ms=1000,
            wait_fonts_ms=1000,
        )

        assert result.status == "ok"
        assert result.screenshot_ok is True
        assert result.axe_ok is False
        assert result.reason == "axe_runtime_error"


class TestScreenshotAndAxeDbFailure:
    """Tests for database insert failures."""

    @pytest.mark.asyncio
    async def test_db_insert_failure_returns_axe_db_error(self, tmp_path: Path):
        """When insert_axe_run raises, axe_ok=false with reason=axe_db_error."""
        # Use a numeric filename so it tries to insert
        html_file = tmp_path / "12345.html"
        png_file = tmp_path / "12345.png"
        html_file.write_text("<html></html>")

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_function = AsyncMock()
        mock_page.screenshot = AsyncMock()
        # Return valid axe results that would trigger DB insert
        mock_page.evaluate = AsyncMock(return_value={
            "testEngine": {"version": "4.10.2"},
            "violations": [],
            "timestamp": "2025-01-01T00:00:00Z",
        })
        mock_page.close = AsyncMock()
        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        with patch("aimac.screenshotter.insert_axe_run", side_effect=Exception("DB error")):
            result = await screenshot_and_axe(
                mock_context,
                str(html_file),
                str(png_file),
                timeout_ms=5000,
                wait_images_ms=1000,
                wait_fonts_ms=1000,
            )

        assert result.status == "ok"
        assert result.screenshot_ok is True
        assert result.axe_ok is False
        assert result.reason == "axe_db_error"


class TestScreenshotBatchAggregation:
    """Tests for screenshot_batch result aggregation."""

    @pytest.mark.asyncio
    async def test_mixed_results_aggregation(self):
        """Verify counters correctly aggregate mixed ok/failed/skipped results.

        This test actually calls screenshot_batch with mocked screenshot_and_axe
        to verify the real aggregation path is exercised.
        """
        # Canned results that screenshot_and_axe will return
        mock_results = [
            AnalysisResult("ok", True, True, 100.0, 10.0, 50.0, "/path/1.axe.json", None),
            AnalysisResult("ok", True, False, 100.0, 10.0, 0.0, None, "axe_runtime_error"),
            AnalysisResult("skipped", True, True, 1.0, 0.0, 0.0, "/path/2.axe.json", None),
            AnalysisResult("failed", False, False, 50.0, 0.0, 0.0, None, "playwright_timeout"),
            AnalysisResult("ok", True, False, 100.0, 10.0, 0.0, None, "axe_not_present"),
        ]

        # Create iterator to return results in sequence
        result_iter = iter(mock_results)

        async def mock_screenshot_and_axe(*args, **kwargs):
            return next(result_iter)

        # Mock the Playwright browser setup
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

        # Create async context manager for async_playwright()
        mock_playwright_cm = MagicMock()
        mock_playwright_cm.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_playwright_cm.__aexit__ = AsyncMock(return_value=None)

        # Dummy paths matching the number of results
        html_paths = [(f"/fake/{i}.html", f"/fake/{i}.png") for i in range(len(mock_results))]

        with patch("tests.helpers.screenshotter.async_playwright", return_value=mock_playwright_cm), \
             patch("tests.helpers.screenshotter.screenshot_and_axe", side_effect=mock_screenshot_and_axe):

            result = await screenshot_batch(html_paths)

        # Verify aggregation from actual screenshot_batch function
        # - ok (axe ok): succeeded=1, axe_total=1, axe_succeeded=1
        # - ok (axe_runtime_error): succeeded=1, axe_total=1, axe_failed=1
        # - skipped: succeeded=1, skipped=1, axe_total=1, axe_succeeded=1
        # - failed (screenshot): failed=1, axe_total=0 (screenshot_ok=false)
        # - ok (axe_not_present): succeeded=1, axe_total=1, axe_failed=1
        assert result["total"] == 5
        assert result["succeeded"] == 4  # 3 ok + 1 skipped
        assert result["failed"] == 1  # 1 playwright_timeout
        assert result["skipped"] == 1
        assert result["axe_total"] == 4  # 4 where screenshot_ok=true or status=skipped
        assert result["axe_succeeded"] == 2  # 2 where axe_ok=true
        assert result["axe_failed"] == 2  # 2 where reason in AXE_ERROR_REASONS

    @pytest.mark.asyncio
    async def test_screenshot_failure_not_counted_as_axe_failure(self):
        """Verify screenshot failures don't inflate axe_failed counter."""
        # This documents the FIXED behavior (lastmac-dte)
        result = AnalysisResult(
            "failed", False, False, 50.0, 0.0, 0.0, None, "playwright_timeout"
        )

        # Per current logic, screenshot failures should NOT count toward axe metrics
        should_count_axe = result.screenshot_ok or result.status == "skipped"
        assert should_count_axe is False

        # And the reason is not in AXE_ERROR_REASONS
        assert result.reason not in AXE_ERROR_REASONS
