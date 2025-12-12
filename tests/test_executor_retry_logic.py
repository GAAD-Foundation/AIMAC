"""Tests for executor retry decision logic.

Tests the should_stop_retrying() function which determines when to stop
retrying a failed request based on HTTP status, HTML validity, and
consecutive length failures.
"""

import pytest

from aimac.executor import MAX_LENGTH_RETRIES, TERMINAL_HTTP_STATUSES, should_stop_retrying


class TestShouldStopRetrying:
    """Tests for should_stop_retrying() function."""

    def test_success_returns_true(self):
        """HTTP 200 with valid HTML should succeed."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=200,
            html_is_valid=1,
            finish_reason="stop",
            consecutive_length_failures=0,
        )
        assert succeeded is True
        assert terminal is False
        assert length_hit is False

    def test_success_requires_valid_html(self):
        """HTTP 200 with invalid HTML should not succeed."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=200,
            html_is_valid=0,  # Invalid HTML
            finish_reason="stop",
            consecutive_length_failures=0,
        )
        assert succeeded is False
        assert terminal is False
        assert length_hit is False

    @pytest.mark.parametrize("status", sorted(TERMINAL_HTTP_STATUSES))
    def test_terminal_http_statuses(self, status: int):
        """Terminal HTTP statuses should stop retries immediately."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=status,
            html_is_valid=0,
            finish_reason=None,
            consecutive_length_failures=0,
        )
        assert succeeded is False
        assert terminal is True
        assert length_hit is False

    def test_non_terminal_status_allows_retry(self):
        """Non-terminal statuses (like 408, 429, 500, 502, 503) should allow retry."""
        for status in [408, 429, 500, 502, 503, 504]:
            succeeded, terminal, length_hit = should_stop_retrying(
                http_status=status,
                html_is_valid=0,
                finish_reason=None,
                consecutive_length_failures=0,
            )
            assert succeeded is False
            assert terminal is False, f"Status {status} should not be terminal"
            assert length_hit is False

    def test_length_failure_below_threshold_allows_retry(self):
        """Length failures below threshold should allow retry."""
        for failures in range(1, MAX_LENGTH_RETRIES):
            succeeded, terminal, length_hit = should_stop_retrying(
                http_status=200,  # Note: length can come with 200
                html_is_valid=0,
                finish_reason="length",
                consecutive_length_failures=failures,
            )
            assert length_hit is False, f"{failures} failures should not trigger ceiling"

    def test_length_failure_at_threshold_stops_retry(self):
        """Length failures at threshold should stop retries."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=200,
            html_is_valid=0,
            finish_reason="length",
            consecutive_length_failures=MAX_LENGTH_RETRIES,
        )
        assert succeeded is False
        assert terminal is False
        assert length_hit is True

    def test_length_failure_above_threshold_stops_retry(self):
        """Length failures above threshold should stop retries."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=200,
            html_is_valid=0,
            finish_reason="length",
            consecutive_length_failures=MAX_LENGTH_RETRIES + 2,
        )
        assert length_hit is True

    def test_length_ceiling_requires_length_finish_reason(self):
        """Length ceiling only triggers with finish_reason='length'."""
        # High consecutive failures but different finish_reason
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=200,
            html_is_valid=0,
            finish_reason="stop",  # Not "length"
            consecutive_length_failures=10,
        )
        assert length_hit is False

    def test_length_ceiling_with_none_finish_reason(self):
        """Length ceiling should not trigger with None finish_reason."""
        succeeded, terminal, length_hit = should_stop_retrying(
            http_status=500,
            html_is_valid=0,
            finish_reason=None,
            consecutive_length_failures=10,
        )
        assert length_hit is False


class TestRetryConstants:
    """Tests for retry-related constants."""

    def test_max_length_retries_is_reasonable(self):
        """MAX_LENGTH_RETRIES should be between 2 and 5."""
        assert 2 <= MAX_LENGTH_RETRIES <= 5, (
            f"MAX_LENGTH_RETRIES={MAX_LENGTH_RETRIES} seems unreasonable"
        )

    def test_terminal_statuses_include_auth_errors(self):
        """Terminal statuses should include authentication errors."""
        assert 401 in TERMINAL_HTTP_STATUSES  # Unauthorized
        assert 403 in TERMINAL_HTTP_STATUSES  # Forbidden

    def test_terminal_statuses_exclude_rate_limits(self):
        """Rate limits (429) should NOT be terminal - they're retriable."""
        assert 429 not in TERMINAL_HTTP_STATUSES

    def test_terminal_statuses_exclude_server_errors(self):
        """Most server errors should NOT be terminal - they're often transient."""
        assert 500 not in TERMINAL_HTTP_STATUSES  # Internal Server Error
        assert 502 not in TERMINAL_HTTP_STATUSES  # Bad Gateway
        assert 503 not in TERMINAL_HTTP_STATUSES  # Service Unavailable (no provider)
        assert 504 not in TERMINAL_HTTP_STATUSES  # Gateway Timeout

    def test_terminal_statuses_exclude_timeout(self):
        """408 Request Timeout should NOT be terminal - it's retryable."""
        assert 408 not in TERMINAL_HTTP_STATUSES
