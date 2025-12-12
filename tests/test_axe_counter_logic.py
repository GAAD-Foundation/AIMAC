"""Tests for axe counter logic - ensuring axe_failed only counts axe-specific failures.

Bug: axe_failed was incrementing when ANY reason was set, including screenshot failures.
Fix: Only count axe failures when screenshot succeeded and reason is axe-specific.
"""


from aimac.screenshotter import AnalysisResult

# These are the axe-specific error reasons that should increment axe_failed
AXE_ERROR_REASONS = frozenset({
    "axe_not_present",
    "axe_inject_timeout",
    "axe_db_error",
    "axe_runtime_error",
})


def should_count_axe_failure(result: AnalysisResult) -> bool:
    """Determine if this result should increment axe_failed counter.

    Only count as axe failure when:
    1. Screenshot succeeded (or was skipped/cached), AND
    2. Axe did not succeed, AND
    3. Reason is an axe-specific error code
    """
    # Import here to test the actual implementation once it exists
    from aimac.executor import should_count_axe_failure as impl
    return impl(result)


def should_count_axe_attempt(result: AnalysisResult) -> bool:
    """Determine if this result should count toward axe_total.

    Axe is attempted when screenshot succeeded or was skipped (cached).
    """
    from aimac.executor import should_count_axe_attempt as impl
    return impl(result)


class TestAxeFailureCounter:
    """Tests for axe_failed counter logic."""

    def test_screenshot_failure_does_not_count_as_axe_failure(self):
        """When screenshot fails, axe never ran - don't count as axe failure."""
        result = AnalysisResult(
            status="failed",
            screenshot_ok=False,
            axe_ok=False,
            elapsed_ms=100.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path=None,
            reason="screenshot_error",
        )
        assert not should_count_axe_failure(result), \
            "Screenshot failure should NOT increment axe_failed"

    def test_playwright_timeout_does_not_count_as_axe_failure(self):
        """Playwright timeout is a browser issue, not axe."""
        result = AnalysisResult(
            status="failed",
            screenshot_ok=False,
            axe_ok=False,
            elapsed_ms=10000.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path=None,
            reason="playwright_timeout",
        )
        assert not should_count_axe_failure(result), \
            "Playwright timeout should NOT increment axe_failed"

    def test_html_not_found_does_not_count_as_axe_failure(self):
        """Missing HTML file is a screenshot issue, not axe."""
        result = AnalysisResult(
            status="failed",
            screenshot_ok=False,
            axe_ok=False,
            elapsed_ms=5.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path=None,
            reason="html_not_found",
        )
        assert not should_count_axe_failure(result), \
            "HTML not found should NOT increment axe_failed"

    def test_axe_not_present_counts_as_axe_failure(self):
        """When screenshot succeeded but axe wasn't available, count it."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=False,
            elapsed_ms=500.0,
            inject_ms=100.0,
            run_ms=0.0,
            axe_path=None,
            reason="axe_not_present",
        )
        assert should_count_axe_failure(result), \
            "axe_not_present with screenshot_ok=True SHOULD increment axe_failed"

    def test_axe_inject_timeout_counts_as_axe_failure(self):
        """Axe injection timeout is an axe-specific failure."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=False,
            elapsed_ms=2500.0,
            inject_ms=2000.0,
            run_ms=0.0,
            axe_path=None,
            reason="axe_inject_timeout",
        )
        assert should_count_axe_failure(result), \
            "axe_inject_timeout SHOULD increment axe_failed"

    def test_axe_runtime_error_counts_as_axe_failure(self):
        """Axe runtime error is an axe-specific failure."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=False,
            elapsed_ms=800.0,
            inject_ms=100.0,
            run_ms=500.0,
            axe_path=None,
            reason="axe_runtime_error",
        )
        assert should_count_axe_failure(result), \
            "axe_runtime_error SHOULD increment axe_failed"

    def test_axe_db_error_counts_as_axe_failure(self):
        """Axe DB upsert error is an axe-specific failure."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=False,
            elapsed_ms=600.0,
            inject_ms=100.0,
            run_ms=300.0,
            axe_path=None,
            reason="axe_db_error",
        )
        assert should_count_axe_failure(result), \
            "axe_db_error SHOULD increment axe_failed"

    def test_axe_success_does_not_count_as_failure(self):
        """When axe succeeded, don't count as failure."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=True,
            elapsed_ms=500.0,
            inject_ms=100.0,
            run_ms=200.0,
            axe_path="/path/to/results.axe.json",
            reason=None,
        )
        assert not should_count_axe_failure(result), \
            "Successful axe run should NOT increment axe_failed"

    def test_skipped_with_axe_ok_does_not_count_as_failure(self):
        """Cached/skipped items with axe_ok=True are not failures."""
        result = AnalysisResult(
            status="skipped",
            screenshot_ok=True,
            axe_ok=True,
            elapsed_ms=1.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path="/path/to/cached.axe.json",
            reason=None,
        )
        assert not should_count_axe_failure(result), \
            "Skipped (cached) items should NOT increment axe_failed"


class TestAxeAttemptCounter:
    """Tests for axe_total (axe attempt) counter logic."""

    def test_screenshot_success_counts_as_axe_attempt(self):
        """When screenshot succeeded, axe was attempted."""
        result = AnalysisResult(
            status="ok",
            screenshot_ok=True,
            axe_ok=True,
            elapsed_ms=500.0,
            inject_ms=100.0,
            run_ms=200.0,
            axe_path="/path/to/results.axe.json",
            reason=None,
        )
        assert should_count_axe_attempt(result), \
            "Screenshot success should count toward axe_total"

    def test_skipped_counts_as_axe_attempt(self):
        """Cached/skipped items had axe run previously."""
        result = AnalysisResult(
            status="skipped",
            screenshot_ok=True,
            axe_ok=True,
            elapsed_ms=1.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path="/path/to/cached.axe.json",
            reason=None,
        )
        assert should_count_axe_attempt(result), \
            "Skipped (cached) items should count toward axe_total"

    def test_screenshot_failure_does_not_count_as_axe_attempt(self):
        """When screenshot failed, axe never ran."""
        result = AnalysisResult(
            status="failed",
            screenshot_ok=False,
            axe_ok=False,
            elapsed_ms=100.0,
            inject_ms=0.0,
            run_ms=0.0,
            axe_path=None,
            reason="screenshot_error",
        )
        assert not should_count_axe_attempt(result), \
            "Screenshot failure should NOT count toward axe_total"
