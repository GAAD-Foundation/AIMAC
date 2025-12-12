"""Tests for executor module - retry logic, backoff, and execution flows.

Characterization tests lock in current _execute_request and execute_pending_requests
behavior BEFORE refactoring.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aimac.executor import MAX_LENGTH_RETRIES, _execute_request, backoff_seconds, execute_pending_requests


def test_backoff_first_attempt_is_zero():
    """First attempt should have no backoff."""
    assert backoff_seconds(1, max_backoff=30) == 0.0


def test_backoff_exponential_growth():
    """Backoff should grow exponentially with jitter."""
    # Attempt 2: base 2^1 = 2, jitter 0-3 → 2-5s
    result = backoff_seconds(2, max_backoff=30)
    assert 2.0 <= result <= 5.0

    # Attempt 3: base 2^2 = 4, jitter 0-3 → 4-7s
    result = backoff_seconds(3, max_backoff=30)
    assert 4.0 <= result <= 7.0


def test_backoff_respects_max_cap():
    """Backoff should never exceed max_backoff."""
    # Attempt 10 would be 2^9 = 512, but capped at 30
    result = backoff_seconds(10, max_backoff=30)
    assert result <= 30.0


def test_backoff_zero_for_attempt_zero():
    """Edge case: attempt 0 or negative should return 0."""
    assert backoff_seconds(0, max_backoff=30) == 0.0
    assert backoff_seconds(-1, max_backoff=30) == 0.0


# -----------------------------------------------------------------------------
# Characterization tests for _execute_request
# These lock in current behavior before refactoring.
# -----------------------------------------------------------------------------


def _make_request(request_pk: int = 1) -> dict:
    """Create a minimal request dict for testing."""
    return {
        "request_pk": request_pk,
        "body_json": json.dumps({"model": "test/model", "messages": []}),
        "company_slug": "test",
        "model_slug": "model",
        "category_slug": "category",
        "request_json_path": "/fake/request.json",
        "response_json_path": "/fake/response.json",
        "html_path": "/fake/output.html",
    }


def _make_api_response(status: int = 200, finish_reason: str = "stop") -> dict:
    """Create a mock API response."""
    return {
        "status": status,
        "json": {
            "choices": [{"finish_reason": finish_reason, "message": {"content": "<html></html>"}}],
        },
    }


class TestExecuteRequestSingleAttempt:
    """Tests for _execute_request single-attempt scenarios."""

    @pytest.mark.asyncio
    async def test_single_attempt_success(self):
        """HTTP 200 + valid HTML succeeds on first attempt, write_artifacts called once."""
        req = _make_request(request_pk=42)
        mock_client = MagicMock()

        with patch("aimac.executor.send_completion", new_callable=AsyncMock) as mock_send, \
             patch("aimac.executor.insert_response") as mock_insert, \
             patch("aimac.executor.get_response_evaluation") as mock_eval, \
             patch("aimac.executor.write_artifacts") as mock_write:

            mock_send.return_value = _make_api_response(status=200, finish_reason="stop")
            mock_insert.return_value = 100  # response_pk
            mock_eval.return_value = (200, 1, "<html></html>")  # http_status, html_is_valid, html_page
            mock_write.return_value = {"request": True, "response": True, "html": True}

            result = await _execute_request(
                mock_client,
                req,
                max_retries=3,
                max_backoff=10,
                http_sem=asyncio.Semaphore(10),
                db_sem=asyncio.Semaphore(1),
            )

            request_pk, success, attempts_used, http_status, finish_reason, provider = result

            assert request_pk == 42
            assert success is True
            assert attempts_used == 1
            assert http_status == 200
            assert finish_reason == "stop"

            # Verify single call to each
            assert mock_send.call_count == 1
            assert mock_insert.call_count == 1
            assert mock_write.call_count == 1


class TestExecuteRequestRetryBehavior:
    """Tests for _execute_request retry scenarios."""

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """First attempt fails (500), second succeeds - verify attempts count."""
        req = _make_request(request_pk=42)
        mock_client = MagicMock()

        call_count = 0

        async def mock_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 500, "json": {"error": {"message": "server error"}}}
            return _make_api_response(status=200, finish_reason="stop")

        with patch("aimac.executor.send_completion", side_effect=mock_send), \
             patch("aimac.executor.insert_response") as mock_insert, \
             patch("aimac.executor.get_response_evaluation") as mock_eval, \
             patch("aimac.executor.write_artifacts") as mock_write, \
             patch("aimac.executor.backoff_seconds", return_value=0.0):  # Skip actual backoff

            def eval_side_effect(response_pk):
                # First call: 500 with invalid HTML, second: 200 with valid
                if mock_insert.call_count <= 1:
                    return (500, 0, None)
                return (200, 1, "<html></html>")

            mock_insert.return_value = 100
            mock_eval.side_effect = eval_side_effect
            mock_write.return_value = {"request": True, "response": True, "html": True}

            result = await _execute_request(
                mock_client,
                req,
                max_retries=3,
                max_backoff=10,
                http_sem=asyncio.Semaphore(10),
                db_sem=asyncio.Semaphore(1),
            )

            request_pk, success, attempts_used, http_status, finish_reason, provider = result

            assert success is True
            assert attempts_used == 2  # First failed, second succeeded
            assert http_status == 200

    @pytest.mark.asyncio
    async def test_terminal_failure_stops_immediately(self):
        """Terminal HTTP status (401) stops retrying immediately."""
        req = _make_request(request_pk=42)
        mock_client = MagicMock()

        with patch("aimac.executor.send_completion", new_callable=AsyncMock) as mock_send, \
             patch("aimac.executor.insert_response") as mock_insert, \
             patch("aimac.executor.get_response_evaluation") as mock_eval, \
             patch("aimac.executor.write_artifacts") as mock_write:

            mock_send.return_value = {"status": 401, "json": {"error": {"message": "unauthorized"}}}
            mock_insert.return_value = 100
            mock_eval.return_value = (401, 0, None)
            mock_write.return_value = {"request": True, "response": True, "html": True}

            result = await _execute_request(
                mock_client,
                req,
                max_retries=5,  # Would retry 5 times if not terminal
                max_backoff=10,
                http_sem=asyncio.Semaphore(10),
                db_sem=asyncio.Semaphore(1),
            )

            request_pk, success, attempts_used, http_status, finish_reason, provider = result

            assert success is False
            assert attempts_used == 1  # Stopped immediately
            assert http_status == 401
            assert mock_send.call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_consecutive_length_failures_stops_at_ceiling(self):
        """Repeated finish_reason='length' stops at MAX_LENGTH_RETRIES."""
        req = _make_request(request_pk=42)
        mock_client = MagicMock()

        with patch("aimac.executor.send_completion", new_callable=AsyncMock) as mock_send, \
             patch("aimac.executor.insert_response") as mock_insert, \
             patch("aimac.executor.get_response_evaluation") as mock_eval, \
             patch("aimac.executor.write_artifacts") as mock_write, \
             patch("aimac.executor.backoff_seconds", return_value=0.0):

            # Always return 200 with finish_reason="length" and invalid HTML
            mock_send.return_value = _make_api_response(status=200, finish_reason="length")
            mock_insert.return_value = 100
            mock_eval.return_value = (200, 0, None)  # 200 but invalid HTML
            mock_write.return_value = {"request": True, "response": True, "html": True}

            result = await _execute_request(
                mock_client,
                req,
                max_retries=10,  # More than MAX_LENGTH_RETRIES
                max_backoff=10,
                http_sem=asyncio.Semaphore(10),
                db_sem=asyncio.Semaphore(1),
            )

            request_pk, success, attempts_used, http_status, finish_reason, provider = result

            assert success is False
            assert attempts_used == MAX_LENGTH_RETRIES  # Stopped at ceiling
            assert finish_reason == "length"
            assert mock_send.call_count == MAX_LENGTH_RETRIES


class TestExecuteRequestDbFailure:
    """Tests for _execute_request database failure handling."""

    @pytest.mark.asyncio
    async def test_db_insert_failure_graceful_return(self):
        """When insert_response raises, function returns gracefully."""
        req = _make_request(request_pk=42)
        mock_client = MagicMock()

        with patch("aimac.executor.send_completion", new_callable=AsyncMock) as mock_send, \
             patch("aimac.executor.insert_response") as mock_insert, \
             patch("aimac.executor.get_response_evaluation") as mock_eval, \
             patch("aimac.executor.write_artifacts") as mock_write, \
             patch("aimac.executor.backoff_seconds", return_value=0.0):

            import sqlite3
            mock_send.return_value = _make_api_response(status=200, finish_reason="stop")
            mock_insert.side_effect = sqlite3.Error("DB connection lost")
            # get_response_evaluation won't be called since insert failed
            mock_write.return_value = {"request": True, "response": True, "html": True}

            result = await _execute_request(
                mock_client,
                req,
                max_retries=3,
                max_backoff=10,
                http_sem=asyncio.Semaphore(10),
                db_sem=asyncio.Semaphore(1),
            )

            request_pk, success, attempts_used, http_status, finish_reason, provider = result

            # When DB fails, code uses fallback status and retries
            assert request_pk == 42
            # Should eventually exhaust retries since DB keeps failing
            assert attempts_used == 4  # 1 + max_retries
            assert success is False
            # Current behavior: returns the API status (200) even when DB fails
            assert http_status == 200
            # Current behavior: preserves finish_reason from API response
            assert finish_reason == "stop"


# -----------------------------------------------------------------------------
# Characterization tests for execute_pending_requests
# -----------------------------------------------------------------------------


class TestExecutePendingRequests:
    """Tests for execute_pending_requests orchestration."""

    @pytest.mark.asyncio
    async def test_no_pending_returns_empty_result(self):
        """Empty pending list returns correct result shape."""
        with patch("aimac.executor.get_pending_requests_for_batch") as mock_get:
            mock_get.return_value = []

            result = await execute_pending_requests(batch_pk=1)

            assert result == {
                "succeeded": 0,
                "failed": 0,
                "elapsed_minutes": 0.0,
            }

    @pytest.mark.asyncio
    async def test_mixed_outcomes_aggregation(self):
        """Multiple requests with mixed success/failure - verify counters.

        This test lets Playwright import fail (handled gracefully) and
        focuses on LLM request orchestration.
        """
        # Two requests: one will succeed, one will fail
        pending = [
            _make_request(request_pk=1),
            _make_request(request_pk=2),
        ]

        call_count = 0

        async def mock_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First request succeeds, second fails with terminal error
            if call_count == 1:
                return _make_api_response(status=200, finish_reason="stop")
            return {"status": 401, "json": {"error": {"message": "unauthorized"}}}

        insert_count = 0

        def mock_eval(response_pk):
            nonlocal insert_count
            insert_count += 1
            if insert_count == 1:
                return (200, 1, "<html></html>")  # Success
            return (401, 0, None)  # Terminal failure

        # Mock Playwright to skip analysis entirely - create a mock that works as async context manager
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_context.add_init_script = AsyncMock()  # For axe injection
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = MagicMock()
        mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("aimac.executor.get_pending_requests_for_batch") as mock_get, \
             patch("aimac.executor.send_completion", side_effect=mock_send), \
             patch("aimac.executor.insert_response", return_value=100), \
             patch("aimac.executor.get_response_evaluation", side_effect=mock_eval), \
             patch("aimac.executor.write_artifacts", return_value={"request": True, "response": True, "html": True}), \
             patch("aimac.executor.write_retry_summary") as mock_write_summary, \
             patch("playwright.async_api.async_playwright", return_value=mock_pw_cm):

            mock_get.return_value = pending

            result = await execute_pending_requests(batch_pk=1)

            # Verify LLM request aggregation
            assert result["succeeded"] == 1
            assert result["failed"] == 1
            assert "elapsed_minutes" in result

            # Verify retry tracking - no retries in this test
            assert result["total_retries"] == 0
            assert result["requests_with_retries"] == 0

            # Verify retry_summary was written
            assert mock_write_summary.called
            summary_arg = mock_write_summary.call_args[0][1]  # Second positional arg
            assert summary_arg["batch_pk"] == 1
            assert summary_arg["total_requests"] == 2
            assert summary_arg["total_retries"] == 0

            # Verify retry_summary is in result
            assert "retry_summary" in result
            assert result["retry_summary"]["total_requests"] == 2

            # Verify screenshot/axe counters present (may be 0 with mocked Playwright)
            # These are only populated if Playwright analysis runs
            assert "screenshot_total" in result
            assert "axe_total" in result

            # Verify LLM failure tracking
            assert "llm_failure_status" in result
            assert "llm_failure_finish_reason" in result
            assert "llm_failure_by_model" in result


# -----------------------------------------------------------------------------
# Tests for _extract_error_message
# -----------------------------------------------------------------------------


class TestExtractErrorMessage:
    """Tests for _extract_error_message helper function."""

    def test_top_level_error_standard_format(self):
        """Standard OpenRouter error format is extracted correctly."""
        from aimac.executor import _extract_error_message

        response = {
            "error": {
                "message": "Rate limit exceeded",
                "detail": "Please retry after 60 seconds",
            }
        }
        msg, detail = _extract_error_message(response)
        assert msg == "Rate limit exceeded"
        assert detail == "Please retry after 60 seconds"

    def test_nested_error_in_choices(self):
        """Provider-specific nested error in choices[0].error is extracted."""
        from aimac.executor import _extract_error_message

        # Real response format from Chutes provider
        response = {
            "provider": "Chutes",
            "choices": [
                {
                    "error": {
                        "message": "Network connection lost.",
                        "code": 502,
                        "metadata": {"provider_name": "Chutes"},
                    },
                    "finish_reason": None,
                    "message": {"content": ""},
                }
            ],
            "http_status": 200,
        }
        msg, detail = _extract_error_message(response)
        assert msg == "Network connection lost."
        assert detail == "provider=Chutes"

    def test_nested_error_without_provider_metadata(self):
        """Nested error without provider metadata still extracts message."""
        from aimac.executor import _extract_error_message

        response = {
            "choices": [
                {
                    "error": {
                        "message": "Internal server error",
                        "code": 500,
                    }
                }
            ]
        }
        msg, detail = _extract_error_message(response)
        assert msg == "Internal server error"
        assert detail == ""

    def test_empty_response_returns_unknown_error(self):
        """Empty response returns 'unknown_error' fallback."""
        from aimac.executor import _extract_error_message

        msg, detail = _extract_error_message({})
        assert msg == "unknown_error"
        assert detail == ""

    def test_no_error_field_returns_unknown_error(self):
        """Response without error field returns 'unknown_error'."""
        from aimac.executor import _extract_error_message

        response = {
            "choices": [
                {
                    "message": {"content": "some content"},
                    "finish_reason": "stop",
                }
            ]
        }
        msg, detail = _extract_error_message(response)
        assert msg == "unknown_error"
        assert detail == ""

    def test_top_level_error_takes_priority_over_nested(self):
        """When both top-level and nested errors exist, top-level wins."""
        from aimac.executor import _extract_error_message

        response = {
            "error": {
                "message": "Top level error",
                "detail": "Top detail",
            },
            "choices": [
                {
                    "error": {
                        "message": "Nested error",
                        "code": 500,
                    }
                }
            ],
        }
        msg, detail = _extract_error_message(response)
        assert msg == "Top level error"
        assert detail == "Top detail"

    def test_detail_truncated_to_200_chars(self):
        """Long detail strings are truncated to 200 characters."""
        from aimac.executor import _extract_error_message

        long_detail = "x" * 300
        response = {
            "error": {
                "message": "Error",
                "detail": long_detail,
            }
        }
        msg, detail = _extract_error_message(response)
        assert msg == "Error"
        assert len(detail) == 200
        assert detail == "x" * 200
