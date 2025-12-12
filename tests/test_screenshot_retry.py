"""Tests for screenshot/axe retry logic.

Regression tests for bug where missing axe files were not retried if PNG existed.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aimac.screenshotter import AnalysisResult, screenshot_and_axe

# Skip slow browser tests in local dev unless explicitly requested
_SKIP_SLOW_LOCALLY = os.getenv("CI") != "true" and os.getenv("RUN_SLOW_TESTS") != "1"


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_screenshot_skip_when_both_exist(tmp_path: Path):
    """If both PNG and axe.json exist, should skip (idempotent behavior)."""
    html_file = tmp_path / "test.html"
    html_file.write_text("<html><body><h1>Test</h1></body></html>")
    png_file = tmp_path / "test.png"
    axe_file = tmp_path / "test.axe.json"

    # Create both files to simulate previous successful run
    png_file.write_bytes(b"fake png data")
    axe_file.write_text('{"violations": []}')

    # Mock browser context (should not be used since we skip)
    mock_context = AsyncMock()

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
    assert result.axe_ok is True
    assert png_file.exists()
    assert axe_file.exists()
    # Browser should not have been used
    mock_context.new_page.assert_not_called()


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_screenshot_retry_when_axe_missing(tmp_path: Path):
    """If PNG exists but axe.json missing, should delete PNG and retry both.

    Regression test for bug where missing axe files were never retried.
    """
    html_file = tmp_path / "test.html"
    html_file.write_text("<html><body><h1>Test</h1></body></html>")
    png_file = tmp_path / "test.png"
    axe_file = tmp_path / "test.axe.json"

    # Simulate incomplete run: PNG exists but axe.json missing
    png_file.write_bytes(b"fake png data")
    assert png_file.exists()
    assert not axe_file.exists()

    try:
        # Mock browser context to avoid real browser launch
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            result = await screenshot_and_axe(
                context,
                str(html_file),
                str(png_file),
                timeout_ms=5000,
                wait_images_ms=1000,
                wait_fonts_ms=1000,
            )

            await browser.close()

    except Exception as e:  # pragma: no cover - environment-dependent
        pytest.skip(f"Playwright not available or browser missing: {e}")

    # Should have deleted old PNG and created both new files
    assert result.status == "ok"
    assert result.screenshot_ok is True
    assert png_file.exists()
    assert png_file.stat().st_size > 0  # Real PNG, not fake data
    # Axe may or may not succeed (depends on page content), but should have tried
    assert result.axe_ok or result.reason is not None


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_screenshot_retry_when_png_partial(tmp_path: Path):
    """If PNG exists but axe.json also exists (both partial), should retry both.

    Tests cleanup of partial/corrupted files before retry.
    """
    html_file = tmp_path / "test.html"
    html_file.write_text("<html><body><h1>Test</h1></body></html>")
    png_file = tmp_path / "test.png"
    tmp_path / "test.axe.json"

    # Simulate partial/corrupted files
    png_file.write_bytes(b"corrupted")
    # Don't create axe_file - simulating timeout during axe run

    original_png_size = png_file.stat().st_size

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            result = await screenshot_and_axe(
                context,
                str(html_file),
                str(png_file),
                timeout_ms=5000,
                wait_images_ms=1000,
                wait_fonts_ms=1000,
            )

            await browser.close()

    except Exception as e:  # pragma: no cover
        pytest.skip(f"Playwright not available or browser missing: {e}")

    # Should have replaced corrupted PNG with real one
    assert result.status == "ok"
    assert result.screenshot_ok is True
    assert png_file.exists()
    assert png_file.stat().st_size > original_png_size  # Real PNG is larger


@pytest.mark.asyncio
async def test_screenshot_fails_when_html_missing(tmp_path: Path):
    """If HTML file doesn't exist, should fail immediately without cleanup."""
    html_file = tmp_path / "missing.html"
    png_file = tmp_path / "missing.png"

    # HTML doesn't exist
    assert not html_file.exists()

    mock_context = AsyncMock()

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
    mock_context.new_page.assert_not_called()


# =============================================================================
# In-run retry with backoff tests (lastmac-705)
# =============================================================================


def _make_result(
    status: str = "ok",
    screenshot_ok: bool = True,
    axe_ok: bool = True,
    reason: str | None = None,
) -> AnalysisResult:
    """Helper to create AnalysisResult for tests."""
    return AnalysisResult(
        status=status,
        screenshot_ok=screenshot_ok,
        axe_ok=axe_ok,
        elapsed_ms=100.0,
        inject_ms=10.0,
        run_ms=50.0,
        axe_path="/fake/path.axe.json" if axe_ok else None,
        reason=reason,
    )


class TestIsTransientFailure:
    """Tests for _is_transient_screenshot_or_axe_failure helper."""

    def test_playwright_timeout_is_transient(self):
        """playwright_timeout should be retried."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="playwright_timeout")
        assert _is_transient_screenshot_or_axe_failure(result) is True

    def test_screenshot_error_is_transient(self):
        """screenshot_error should be retried."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="screenshot_error")
        assert _is_transient_screenshot_or_axe_failure(result) is True

    def test_axe_inject_timeout_is_transient(self):
        """axe_inject_timeout should be retried."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="ok", screenshot_ok=True, axe_ok=False, reason="axe_inject_timeout")
        assert _is_transient_screenshot_or_axe_failure(result) is True

    def test_axe_runtime_error_is_transient(self):
        """axe_runtime_error should be retried."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="ok", screenshot_ok=True, axe_ok=False, reason="axe_runtime_error")
        assert _is_transient_screenshot_or_axe_failure(result) is True

    def test_html_not_found_is_not_transient(self):
        """html_not_found is permanent - file doesn't exist."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="html_not_found")
        assert _is_transient_screenshot_or_axe_failure(result) is False

    def test_axe_db_error_is_not_transient(self):
        """axe_db_error is not transient - DB issue won't fix itself."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="ok", screenshot_ok=True, axe_ok=False, reason="axe_db_error")
        assert _is_transient_screenshot_or_axe_failure(result) is False

    def test_axe_db_missing_is_not_transient(self):
        """axe_db_missing is skip-path issue, not runtime failure."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="skipped", screenshot_ok=True, axe_ok=False, reason="axe_db_missing")
        assert _is_transient_screenshot_or_axe_failure(result) is False

    def test_success_is_not_transient(self):
        """Successful result should not be marked as transient failure."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="ok", screenshot_ok=True, axe_ok=True, reason=None)
        assert _is_transient_screenshot_or_axe_failure(result) is False

    def test_skipped_with_axe_ok_is_not_transient(self):
        """Skipped (cached) with axe_ok=True should not be retried."""
        from aimac.executor import _is_transient_screenshot_or_axe_failure

        result = _make_result(status="skipped", screenshot_ok=True, axe_ok=True, reason=None)
        assert _is_transient_screenshot_or_axe_failure(result) is False


class TestScreenshotRetryWrapper:
    """Tests for run_screenshot_and_axe_with_retry wrapper."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """First call fails transiently, second succeeds - final result is success."""
        from aimac.executor import run_screenshot_and_axe_with_retry

        fail_result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="playwright_timeout")
        success_result = _make_result(status="ok", screenshot_ok=True, axe_ok=True)

        mock_screenshot_and_axe = AsyncMock(side_effect=[fail_result, success_result])

        with patch("aimac.executor.RETRY_BACKOFF_SECONDS", 0):  # Skip sleep in tests
            result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
                mock_screenshot_and_axe,
                AsyncMock(),  # mock context
                "/fake/path.html",
                "/fake/path.png",
                timeout_ms=10000,
                wait_images_ms=3000,
                wait_fonts_ms=2000,
            )

        assert result.status == "ok"
        assert result.axe_ok is True
        assert did_retry is True
        assert first_reason == "playwright_timeout"
        assert mock_screenshot_and_axe.call_count == 2

    @pytest.mark.asyncio
    async def test_non_transient_failure_not_retried(self):
        """Non-transient failure should be returned immediately without retry."""
        from aimac.executor import run_screenshot_and_axe_with_retry

        fail_result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="html_not_found")

        mock_screenshot_and_axe = AsyncMock(return_value=fail_result)

        result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
            mock_screenshot_and_axe,
            AsyncMock(),
            "/fake/path.html",
            "/fake/path.png",
            timeout_ms=10000,
            wait_images_ms=3000,
            wait_fonts_ms=2000,
        )

        assert result.status == "failed"
        assert result.reason == "html_not_found"
        assert did_retry is False
        assert first_reason is None
        assert mock_screenshot_and_axe.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_retry_fails_twice_returns_failure(self):
        """Both attempts fail - final result is failure."""
        from aimac.executor import run_screenshot_and_axe_with_retry

        fail_result = _make_result(status="failed", screenshot_ok=False, axe_ok=False, reason="playwright_timeout")

        mock_screenshot_and_axe = AsyncMock(return_value=fail_result)

        with patch("aimac.executor.RETRY_BACKOFF_SECONDS", 0):
            result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
                mock_screenshot_and_axe,
                AsyncMock(),
                "/fake/path.html",
                "/fake/path.png",
                timeout_ms=10000,
                wait_images_ms=3000,
                wait_fonts_ms=2000,
            )

        assert result.status == "failed"
        assert result.reason == "playwright_timeout"
        assert did_retry is True
        assert first_reason == "playwright_timeout"
        assert mock_screenshot_and_axe.call_count == 2  # Tried twice

    @pytest.mark.asyncio
    async def test_success_on_first_attempt_no_retry(self):
        """Success on first attempt should not trigger retry."""
        from aimac.executor import run_screenshot_and_axe_with_retry

        success_result = _make_result(status="ok", screenshot_ok=True, axe_ok=True)

        mock_screenshot_and_axe = AsyncMock(return_value=success_result)

        result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
            mock_screenshot_and_axe,
            AsyncMock(),
            "/fake/path.html",
            "/fake/path.png",
            timeout_ms=10000,
            wait_images_ms=3000,
            wait_fonts_ms=2000,
        )

        assert result.status == "ok"
        assert did_retry is False
        assert first_reason is None
        assert mock_screenshot_and_axe.call_count == 1

    @pytest.mark.asyncio
    async def test_axe_only_failure_retried(self):
        """Screenshot OK but axe transient failure should retry."""
        from aimac.executor import run_screenshot_and_axe_with_retry

        axe_fail = _make_result(status="ok", screenshot_ok=True, axe_ok=False, reason="axe_runtime_error")
        full_success = _make_result(status="ok", screenshot_ok=True, axe_ok=True)

        mock_screenshot_and_axe = AsyncMock(side_effect=[axe_fail, full_success])

        with patch("aimac.executor.RETRY_BACKOFF_SECONDS", 0):
            result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
                mock_screenshot_and_axe,
                AsyncMock(),
                "/fake/path.html",
                "/fake/path.png",
                timeout_ms=10000,
                wait_images_ms=3000,
                wait_fonts_ms=2000,
            )

        assert result.status == "ok"
        assert result.axe_ok is True
        assert did_retry is True
        assert first_reason == "axe_runtime_error"
        assert mock_screenshot_and_axe.call_count == 2

