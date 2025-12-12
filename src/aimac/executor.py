"""Async execution of pending requests with retries and artifact writing.

The executor is the runtime engine for benchmark collection. It takes pending
requests from the database, sends them to OpenRouter concurrently, handles
retries with exponential backoff, and coordinates screenshot/axe analysis.

Key design decisions:
- Async concurrency with semaphores (not thread pools) for HTTP and DB access
- SQLite single-writer pattern: db_sem=1 prevents WAL contention
- Streaming analysis: screenshots are enqueued as LLM responses complete
- Never-throw pattern: all errors are captured in result dicts for reporting

Environment variables (see README.md for full list):
- OPENROUTER_CONCURRENCY: Max concurrent HTTP requests (default: 50)
- OPENROUTER_MAX_RETRY_ATTEMPTS: Retry limit per request (default: 4)
- OPENROUTER_MAX_BACKOFF_SECONDS: Max backoff delay (default: 30)

See also:
- src/aimac/collector.py - calls execute_pending_requests() as main entry point
- src/aimac/openrouter.py - HTTP communication with OpenRouter API
- src/aimac/artifacts.py - file I/O for request/response JSON and HTML
- src/aimac/screenshotter.py - Playwright-based screenshot and axe analysis
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .screenshotter import AnalysisResult

from .artifacts import write_artifacts, write_retry_summary
from .database import DatabaseError, get_pending_requests_for_batch, get_response_evaluation, insert_response
from .openrouter import send_completion
from .utils import compute_percentiles, get_env_int

logger = logging.getLogger(__name__)

# Limit failure samples stored for error reporting (per failure type)
MAX_FAILURE_SAMPLES = 10


@dataclass
class AnalysisMetrics:
    """Mutable container for screenshot/axe analysis counters.

    Using a dataclass eliminates the need for 9 nonlocal declarations in
    the worker function - the object reference stays the same while its
    fields are mutated.
    """

    screenshot_succeeded: int = 0
    screenshot_failed: int = 0
    screenshot_skipped: int = 0
    screenshot_retries: int = 0
    screenshot_retry_successes: int = 0
    axe_total: int = 0
    axe_succeeded: int = 0
    axe_failed: int = 0
    processed: int = 0


@dataclass
class WorkerContext:
    """Shared context passed to analysis workers.

    Groups the parameters and mutable state that workers need access to,
    avoiding long parameter lists and excessive closure captures.
    """

    metrics: AnalysisMetrics
    queue: asyncio.Queue
    total: int
    timeout_ms: int
    wait_images_ms: int
    wait_fonts_ms: int
    durations_ms: list[float]
    inject_times: list[float]
    run_times: list[float]
    axe_failure_reasons: dict[str, int]
    axe_failure_samples: list[dict]


def backoff_seconds(attempt_index: int, max_backoff: int) -> float:
    """Calculate exponential backoff delay with jitter for retries.

    Jitter (0-3s random) prevents thundering herd when many requests retry
    simultaneously after a provider outage.

    Args:
        attempt_index: Retry attempt number (1-based)
        max_backoff: Maximum backoff delay in seconds

    Returns:
        Backoff delay in seconds (0.0 for first attempt, exponential + jitter thereafter)
    """
    import random

    if attempt_index <= 1:
        return 0.0
    base = min(max_backoff, 2 ** (attempt_index - 1))
    jitter = random.uniform(0, 3)
    return float(min(max_backoff, base + jitter))


# Terminal HTTP status codes that should not be retried.
# These indicate permanent failures (auth, bad request) not transient issues.
# Note: 408 (timeout) and 503 (no provider) are retryable per OpenRouter docs.
TERMINAL_HTTP_STATUSES = frozenset({400, 401, 402, 403, 404, 405, 422})

# Max consecutive "length" failures before giving up.
# finish_reason="length" means the model hit its output token ceiling.
# Retrying is unlikely to help if the model consistently can't fit the response.
MAX_LENGTH_RETRIES = 3

# Axe-specific error reasons (screenshot succeeded but axe failed).
# Used by should_count_axe_failure() to distinguish axe issues from screenshot issues.
AXE_ERROR_REASONS = frozenset({
    "axe_not_present",      # axe-core script not injected
    "axe_inject_timeout",   # axe injection timed out
    "axe_db_error",         # database write of axe results failed
    "axe_runtime_error",    # axe.run() threw an exception
    "axe_db_missing",       # skip path: files exist but axe_runs row missing
})

# Transient screenshot/axe errors that may succeed on retry.
# These are typically Playwright/browser hiccups, not permanent failures.
TRANSIENT_SCREENSHOT_REASONS = frozenset({
    "playwright_timeout",   # Navigation or screenshot timeout
    "screenshot_error",     # General screenshot failure
    "axe_inject_timeout",   # Axe injection timed out
    "axe_runtime_error",    # axe.run() threw an exception
})

# Backoff seconds for screenshot/axe retry (can be patched in tests)
RETRY_BACKOFF_SECONDS = 30


def should_count_axe_failure(result: AnalysisResult) -> bool:
    """Determine if this result should increment axe_failed counter.

    Only count as axe failure when:
    1. Screenshot succeeded (or was skipped/cached), AND
    2. Axe did not succeed, AND
    3. Reason is an axe-specific error code

    This prevents screenshot failures from polluting axe metrics.

    Args:
        result: AnalysisResult from screenshot_and_axe operation

    Returns:
        True if this should be counted as an axe failure, False otherwise
    """
    if result.axe_ok:
        return False
    if not (result.screenshot_ok or result.status == "skipped"):
        return False
    return result.reason in AXE_ERROR_REASONS


def should_count_axe_attempt(result: AnalysisResult) -> bool:
    """Determine if this result should count toward axe_total.

    Axe is attempted when screenshot succeeded or was skipped (cached).
    When screenshot fails, axe never had a chance to run.

    Args:
        result: AnalysisResult from screenshot_and_axe operation

    Returns:
        True if axe was attempted (regardless of success), False otherwise
    """
    return result.screenshot_ok or result.status == "skipped"


def should_stop_retrying(
    http_status: int,
    html_is_valid: int,
    finish_reason: str | None,
    consecutive_length_failures: int,
) -> tuple[bool, bool, bool]:
    """Determine if we should stop retrying a request.

    Returns:
        (succeeded, terminal_error, length_ceiling_hit)
        - succeeded: Request completed successfully
        - terminal_error: Unrecoverable HTTP error
        - length_ceiling_hit: Hit output token ceiling too many times
    """
    succeeded = html_is_valid == 1 and http_status == 200
    terminal_error = http_status in TERMINAL_HTTP_STATUSES
    length_ceiling_hit = (
        finish_reason == "length" and consecutive_length_failures >= MAX_LENGTH_RETRIES
    )
    return succeeded, terminal_error, length_ceiling_hit


def _is_transient_screenshot_or_axe_failure(result: AnalysisResult) -> bool:
    """Determine if a screenshot/axe failure is transient and worth retrying.

    Transient failures are browser hiccups that may succeed on retry:
    - playwright_timeout: navigation or screenshot timeout
    - screenshot_error: general screenshot failure
    - axe_inject_timeout: axe script injection timed out
    - axe_runtime_error: axe.run() threw an exception

    Non-transient failures should NOT be retried:
    - html_not_found: file doesn't exist (won't magically appear)
    - axe_db_error: DB write failed (retrying won't help)
    - axe_db_missing: skip-path issue, not a runtime failure
    - success/skipped: not failures at all
    """
    # Success or cached - not a failure
    if result.axe_ok and result.screenshot_ok:
        return False
    if result.status == "skipped" and result.axe_ok:
        return False

    return result.reason in TRANSIENT_SCREENSHOT_REASONS


async def run_screenshot_and_axe_with_retry(
    screenshot_and_axe_fn,
    context,
    html_path: str,
    png_path: str,
    *,
    timeout_ms: int,
    wait_images_ms: int,
    wait_fonts_ms: int,
) -> tuple[AnalysisResult, bool, str | None]:
    """Wrapper that retries screenshot_and_axe once on transient failures.

    Behavior:
    1. Call screenshot_and_axe once
    2. If success or non-transient failure, return immediately
    3. If transient failure, wait RETRY_BACKOFF_SECONDS and retry once
    4. Return the result of the second attempt (success or failure)

    Returns:
        (result, did_retry, first_failure_reason)
        - result: The final AnalysisResult
        - did_retry: True if a retry was attempted
        - first_failure_reason: The reason from the first attempt if retried, else None

    This handles flaky Playwright issues (OOM, GPU hiccups, timeouts) without
    changing Tier-1/Tier-2 cache semantics.
    """
    result = await screenshot_and_axe_fn(
        context,
        html_path,
        png_path,
        timeout_ms=timeout_ms,
        wait_images_ms=wait_images_ms,
        wait_fonts_ms=wait_fonts_ms,
    )

    # Check if we should retry
    if not _is_transient_screenshot_or_axe_failure(result):
        return result, False, None

    # Transient failure - wait and retry once
    first_failure_reason = result.reason
    if RETRY_BACKOFF_SECONDS > 0:
        await asyncio.sleep(RETRY_BACKOFF_SECONDS)

    retry_result = await screenshot_and_axe_fn(
        context,
        html_path,
        png_path,
        timeout_ms=timeout_ms,
        wait_images_ms=wait_images_ms,
        wait_fonts_ms=wait_fonts_ms,
    )
    return retry_result, True, first_failure_reason


async def _analysis_worker(
    browser_context,
    wctx: WorkerContext,
    screenshot_and_axe_fn,
) -> None:
    """Process screenshot/axe analysis jobs from the queue.

    Runs until it receives a None sentinel value. Each job is a tuple of
    (request_pk, html_path, png_path, progress_num).

    Args:
        browser_context: Playwright BrowserContext to use for screenshots
        wctx: WorkerContext with shared state and configuration
        screenshot_and_axe_fn: The screenshot_and_axe function to call
    """
    while True:
        item = await wctx.queue.get()
        if item is None:
            wctx.queue.task_done()
            break
        request_pk: int = item[0]
        html_path: str = item[1]
        png_path: str = item[2]
        progress_num: int = item[3] if len(item) > 3 else request_pk

        # Try block narrowed to just the async call - metrics/printing bugs
        # should surface as real errors, not "worker crashed"
        try:
            result, did_retry, first_reason = await run_screenshot_and_axe_with_retry(
                screenshot_and_axe_fn,
                browser_context,
                html_path,
                png_path,
                timeout_ms=wctx.timeout_ms,
                wait_images_ms=wctx.wait_images_ms,
                wait_fonts_ms=wctx.wait_fonts_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Analysis worker crashed for request_pk=%s", request_pk)
            wctx.metrics.screenshot_failed += 1
            progress_display = f"[{progress_num}/{wctx.total}]" if wctx.total > 0 else f"[{request_pk}]"
            print(f"{progress_display} [FAIL] Analysis crashed")
        else:
            # Bookkeeping and printing - bugs here will bubble up properly
            _record_analysis_result(
                wctx, result, did_retry, first_reason,
                request_pk, html_path, png_path, progress_num,
            )
        finally:
            wctx.metrics.processed += 1
            wctx.queue.task_done()


def _record_analysis_result(
    wctx: WorkerContext,
    result,
    did_retry: bool,
    first_reason: str | None,
    request_pk: int,
    html_path: str,
    png_path: str,
    progress_num: int,
) -> None:
    """Record analysis result metrics and print progress.

    Extracted from worker to keep the async worker function focused on
    the async operations.
    """
    # Track retry metrics
    if did_retry:
        wctx.metrics.screenshot_retries += 1
        if result.status == "ok" or (result.screenshot_ok and result.axe_ok):
            wctx.metrics.screenshot_retry_successes += 1

    # CLI visibility - separate lines with full file paths
    progress_display = f"[{progress_num}/{wctx.total}]" if wctx.total > 0 else f"[{request_pk}]"
    retry_indicator = f" [RETRY: {first_reason}]" if did_retry else ""

    # PNG status line with path
    if result.status == "ok":
        print(f"{progress_display} PNG [OK]{retry_indicator} {png_path}")
    elif result.status == "skipped":
        print(f"{progress_display} PNG (cached) {png_path}")
    else:
        print(f"{progress_display} PNG [FAIL] ({result.reason or 'unknown'}){retry_indicator} {png_path}")

    # Axe status line (only if PNG succeeded or was cached)
    if result.status in ("ok", "skipped"):
        axe_status = "[OK]" if result.axe_ok else "[FAIL]"
        axe_path = str(Path(html_path).with_suffix('.axe.json'))
        print(f"{progress_display} Axe {axe_status} {axe_path}")

    # Track axe metrics for summary
    if should_count_axe_attempt(result):
        wctx.metrics.axe_total += 1
        if result.axe_ok:
            wctx.metrics.axe_succeeded += 1
        elif should_count_axe_failure(result):
            wctx.metrics.axe_failed += 1
            wctx.axe_failure_reasons[result.reason] = wctx.axe_failure_reasons.get(result.reason, 0) + 1
            if len(wctx.axe_failure_samples) < MAX_FAILURE_SAMPLES:
                wctx.axe_failure_samples.append({
                    "request_pk": request_pk,
                    "reason": result.reason,
                    "path": html_path,
                })

    if result.elapsed_ms and result.status == "ok":
        wctx.durations_ms.append(result.elapsed_ms)
    if result.inject_ms and result.inject_ms > 0:
        wctx.inject_times.append(result.inject_ms)
    if result.run_ms and result.run_ms > 0:
        wctx.run_times.append(result.run_ms)

    if result.status == "ok":
        wctx.metrics.screenshot_succeeded += 1
    elif result.status == "skipped":
        wctx.metrics.screenshot_skipped += 1
    else:
        wctx.metrics.screenshot_failed += 1


def _stamp_response_metadata(
    response_json: dict,
    request_body: dict,
    req: dict,
    request_pk: int,
    http_rtt_ms: float,
) -> None:
    """Stamp execution metadata onto response JSON for standalone artifact readability.

    Adds aimac_metadata block so response.json files can be understood without
    cross-referencing the database or request.json file.

    Args:
        response_json: Response dictionary to mutate (aimac_metadata field added/updated)
        request_body: Original request body sent to OpenRouter
        req: Database row dict with company/model/category slugs
        request_pk: Database primary key for this request
        http_rtt_ms: HTTP round-trip time in milliseconds
    """
    metadata = response_json.get("aimac_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update({
        "request_pk": request_pk,
        "model_id": request_body.get("model"),
        "company_slug": req.get("company_slug"),
        "model_slug": req.get("model_slug"),
        "category_slug": req.get("category_slug"),
        "http_rtt_ms": http_rtt_ms,
    })
    response_json["aimac_metadata"] = metadata


def _persist_response(
    request_pk: int,
    attempt: int,
    response_json: dict,
    fallback_status: int,
) -> tuple[int, int, str | None]:
    """Insert response to DB and evaluate validity via SQL view.

    The evaluation happens in the database via response_evaluation view which
    extracts HTML from the response, validates it, and returns status codes.

    Args:
        request_pk: Database primary key for the request
        attempt: Retry attempt number (1-based)
        response_json: Response dictionary to persist
        fallback_status: HTTP status to return if DB operations fail

    Returns:
        Tuple of (http_status, html_is_valid, html_page).
        On DB failure, returns fallback values with valid=0 so retry logic continues.
    """
    # Serialize outside try to surface TypeError (non-serializable) as programming error
    payload = json.dumps(response_json, separators=(",", ":"))
    try:
        response_pk = insert_response(request_pk, attempt, payload)
        return get_response_evaluation(response_pk)
    except (sqlite3.Error, DatabaseError):
        logger.warning("DB write/evaluation failed", exc_info=True)
        return (fallback_status if isinstance(fallback_status, int) else 500, 0, None)


def _extract_error_message(response_json: dict) -> tuple[str, str]:
    """Extract error message and detail from response, checking all known locations.

    OpenRouter responses can contain errors in two places:
    1. Top-level: {"error": {"message": "...", "detail": "..."}}
    2. Nested in choices: {"choices": [{"error": {"message": "...", "code": 502}}]}

    The nested format occurs with certain providers (e.g., Chutes) that return
    HTTP 200 but embed the actual error in choices[0].error.

    Args:
        response_json: Response dictionary from OpenRouter

    Returns:
        Tuple of (error_message, error_detail) with fallback to "unknown_error"
    """
    # Try top-level error first (standard OpenRouter format)
    top_error = response_json.get("error", {})
    if isinstance(top_error, dict):
        msg = top_error.get("message")
        if msg:
            detail = str(top_error.get("detail", ""))[:200]
            return msg, detail

    # Try nested error in choices[0].error (provider-specific format)
    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            nested_error = first_choice.get("error", {})
            if isinstance(nested_error, dict):
                msg = nested_error.get("message")
                if msg:
                    # Include provider name if available in metadata
                    provider = nested_error.get("metadata", {}).get("provider_name", "")
                    detail = f"provider={provider}" if provider else ""
                    return msg, detail

    return "unknown_error", ""


def _log_transient_error(
    request_pk: int,
    attempt: int,
    attempts_total: int,
    response_json: dict,
) -> None:
    """Log transient errors that will be retried.

    Args:
        request_pk: Database primary key for the request
        attempt: Current retry attempt number
        attempts_total: Maximum retry attempts allowed
        response_json: Response dictionary containing error details
    """
    error_msg, error_detail = _extract_error_message(response_json)
    logger.info(
        f"Request {request_pk} attempt {attempt}/{attempts_total} failed "
        f"({error_msg}: {error_detail}), will retry"
    )


def _write_artifacts_safe(
    req: dict,
    request_body: dict,
    response_json: dict,
    html_page: str | None,
    html_is_valid: int,
    attempt: int,
) -> None:
    """Write artifacts and log failures (non-fatal).

    Args:
        req: Database row dict containing artifact paths
        request_body: Original request body to write
        response_json: Response to write
        html_page: Extracted HTML to write (or None if invalid)
        html_is_valid: 1 if HTML is valid, 0 otherwise
        attempt: Retry attempt number for logging
    """
    artifact_results = write_artifacts(
        req.get("request_json_path"),
        req.get("response_json_path"),
        req.get("html_path"),
        request_body,
        response_json,
        html_page if html_is_valid else None,
        attempt,
    )
    if not all(artifact_results.values()):
        failed = [k for k, v in artifact_results.items() if not v]
        logger.debug(f"Some artifacts failed to write: {failed}")


def _extract_finish_reason(response_json: dict) -> str | None:
    """Extract LLM finish_reason from response choices if present.

    Args:
        response_json: OpenRouter API response dictionary

    Returns:
        The finish_reason string if present in choices[0], None otherwise
    """
    choices = response_json.get("choices") or []
    if isinstance(choices, list) and choices:
        fr = (choices[0] or {}).get("finish_reason")
        if isinstance(fr, str):
            return fr
    return None


async def _execute_request(
    client: httpx.AsyncClient,
    req: dict,
    *,
    max_retries: int,
    max_backoff: int,
    http_sem: asyncio.Semaphore,
    db_sem: asyncio.Semaphore,
    http_wait_ms_list: list[float] | None = None,
    http_rtt_ms_list: list[float] | None = None,
    db_wait_ms_list: list[float] | None = None,
) -> tuple[int, bool, int, int, str | None, str | None]:
    """Execute a single request with retries.

    Args:
        client: Async HTTP client for OpenRouter API calls
        req: Database row dict containing request details and artifact paths
        max_retries: Maximum number of retry attempts beyond initial attempt
        max_backoff: Maximum backoff delay in seconds
        http_sem: Semaphore controlling HTTP concurrency
        db_sem: Semaphore controlling database write concurrency
        http_wait_ms_list: Optional list to append HTTP queue wait times
        http_rtt_ms_list: Optional list to append HTTP round-trip times
        db_wait_ms_list: Optional list to append DB queue wait times

    Returns:
        Tuple of (request_pk, success, attempts_used, http_status, finish_reason, provider).
        Progress printing is now handled in the main loop, not here.
    """
    request_pk = req["request_pk"]
    body_json = req["body_json"]
    request_body = json.loads(body_json) if isinstance(body_json, str) else dict(body_json)

    attempts_total = 1 + max(0, max_retries)
    attempts_used = 0
    consecutive_length_failures = 0  # Track "length" finish_reason for early stop

    for attempt in range(1, attempts_total + 1):
        attempts_used = attempt
        # HTTP concurrency wait timing
        w0 = time.monotonic()
        await http_sem.acquire()
        w1 = time.monotonic()
        if http_wait_ms_list is not None:
            http_wait_ms_list.append((w1 - w0) * 1000.0)
        try:
            send0 = time.monotonic()
            result = await send_completion(client, request_body)
            send1 = time.monotonic()
            if http_rtt_ms_list is not None:
                http_rtt_ms_list.append((send1 - send0) * 1000.0)
        finally:
            http_sem.release()

        status = result.get("status", -1)
        response_json = result.get("json", {"http_status": status})
        http_rtt_ms = round((send1 - send0) * 1000.0, 2)
        _stamp_response_metadata(response_json, request_body, req, request_pk, http_rtt_ms)
        finish_reason = _extract_finish_reason(response_json)
        provider = response_json.get("provider")  # OpenRouter provider that served request

        # Track consecutive "length" failures for early termination
        # (output ceiling hit - more retries unlikely to help)
        if finish_reason == "length":
            consecutive_length_failures += 1
        else:
            consecutive_length_failures = 0

        # DB concurrency wait timing
        dw0 = time.monotonic()
        await db_sem.acquire()
        dw1 = time.monotonic()
        if db_wait_ms_list is not None:
            db_wait_ms_list.append((dw1 - dw0) * 1000.0)
        try:
            http_status, html_is_valid, html_page = _persist_response(
                request_pk, attempt, response_json, status
            )
        finally:
            db_sem.release()

        _write_artifacts_safe(req, request_body, response_json, html_page, html_is_valid, attempt)

        succeeded, terminal_error, length_ceiling_hit = should_stop_retrying(
            http_status, html_is_valid, finish_reason, consecutive_length_failures
        )
        if length_ceiling_hit:
            logger.debug(
                f"Request {request_pk} hit output length ceiling {consecutive_length_failures}x, "
                "stopping retries"
            )

        # Log transient errors that will be retried
        if not succeeded and not terminal_error and not length_ceiling_hit and attempt < attempts_total:
            _log_transient_error(request_pk, attempt, attempts_total, response_json)

        if succeeded or terminal_error or length_ceiling_hit:
            return request_pk, succeeded, attempts_used, http_status, finish_reason, provider

        if attempt < attempts_total:
            await asyncio.sleep(backoff_seconds(attempt + 1, max_backoff))

    return request_pk, False, attempts_used, http_status, finish_reason, provider


def _build_result_dict(
    *,
    succeeded: int,
    failed: int,
    elapsed_minutes: float,
    total_retries: int,
    requests_with_retries: int,
    retry_summary: dict,
    screenshot_total: int,
    screenshot_succeeded: int,
    screenshot_failed: int,
    screenshot_skipped: int,
    screenshot_retries: int,
    screenshot_retry_successes: int,
    axe_total: int,
    axe_succeeded: int,
    axe_failed: int,
    durations_ms: list[float],
    inject_times: list[float],
    run_times: list[float],
    axe_failure_reasons: dict[str, int],
    axe_failure_samples: list[dict],
    llm_fail_status: dict[int, int],
    llm_fail_finish: dict[str, int],
    llm_fail_samples: list[dict],
    llm_fail_by_model: dict[str, dict],
) -> dict:
    """Assemble the final result dictionary for execute_pending_requests.

    Args:
        succeeded: Count of successful requests
        failed: Count of failed requests
        elapsed_minutes: Total execution time in minutes
        total_retries: Total retry attempts across all requests
        requests_with_retries: Count of requests that needed retries
        retry_summary: Full retry summary dict from _build_retry_summary
        screenshot_total: Total screenshots attempted
        screenshot_succeeded: Successful screenshots
        screenshot_failed: Failed screenshots
        screenshot_skipped: Cached/skipped screenshots
        screenshot_retries: Total screenshot retry attempts
        screenshot_retry_successes: Successful screenshot retries
        axe_total: Total axe runs attempted
        axe_succeeded: Successful axe runs
        axe_failed: Failed axe runs
        durations_ms: Screenshot duration samples for percentile calculation
        inject_times: Axe injection time samples
        run_times: Axe run time samples
        axe_failure_reasons: Aggregated axe failure counts by reason
        axe_failure_samples: Sample failures for debugging
        llm_fail_status: Aggregated LLM failure counts by HTTP status
        llm_fail_finish: Aggregated LLM failure counts by finish_reason
        llm_fail_samples: Sample LLM failures for debugging
        llm_fail_by_model: LLM failure breakdown by model

    Returns:
        Complete result dictionary with all metrics and timing data
    """
    return {
        "succeeded": succeeded,
        "failed": failed,
        "elapsed_minutes": elapsed_minutes,
        "total_retries": total_retries,
        "requests_with_retries": requests_with_retries,
        "retry_summary": retry_summary,
        # analysis fields for collector summary
        "screenshot_total": screenshot_total,
        "screenshot_succeeded": screenshot_succeeded,
        "screenshot_failed": screenshot_failed,
        "screenshot_skipped": screenshot_skipped,
        "screenshot_retries": screenshot_retries,
        "screenshot_retry_successes": screenshot_retry_successes,
        "axe_total": axe_total,
        "axe_succeeded": axe_succeeded,
        "axe_failed": axe_failed,
        "timing_ms": compute_percentiles(durations_ms),
        "axe_timing_ms": {
            "inject_p95": compute_percentiles(inject_times).get("p95_ms", 0.0),
            "run_p95": compute_percentiles(run_times).get("p95_ms", 0.0),
        },
        "axe_failure_reasons": axe_failure_reasons,
        "axe_failure_samples": axe_failure_samples,
        "llm_failure_status": llm_fail_status,
        "llm_failure_finish_reason": llm_fail_finish,
        "llm_failure_samples": llm_fail_samples,
        "llm_failure_by_model": llm_fail_by_model,
    }


def _build_retry_summary(
    *,
    batch_pk: int,
    total_requests: int,
    total_retries: int,
    requests_with_retries: int,
    retry_distribution: dict[int, int],
    concurrency: int,
    http_wait_ms: list[float],
    http_rtt_ms: list[float],
    db_wait_ms: list[float],
    screenshot_total: int,
    screenshot_succeeded: int,
    screenshot_failed: int,
    screenshot_skipped: int,
    axe_total: int,
    axe_succeeded: int,
    axe_failed: int,
    axe_failure_reasons: dict[str, int],
    durations_ms: list[float],
    inject_times: list[float],
    run_times: list[float],
    llm_fail_status: dict[int, int],
    llm_fail_finish: dict[str, int],
    llm_fail_samples: list[dict],
) -> dict:
    """Build the retry summary dictionary for logging and artifact writing.

    Args:
        batch_pk: Database primary key for the batch
        total_requests: Total number of requests in batch
        total_retries: Total retry attempts across all requests
        requests_with_retries: Count of requests that needed retries
        retry_distribution: Histogram of retry counts (key=retries, val=count)
        concurrency: Effective HTTP concurrency used
        http_wait_ms: HTTP queue wait time samples
        http_rtt_ms: HTTP round-trip time samples
        db_wait_ms: DB queue wait time samples
        screenshot_total: Total screenshots attempted
        screenshot_succeeded: Successful screenshots
        screenshot_failed: Failed screenshots
        screenshot_skipped: Cached/skipped screenshots
        axe_total: Total axe runs attempted
        axe_succeeded: Successful axe runs
        axe_failed: Failed axe runs
        axe_failure_reasons: Aggregated axe failure counts by reason
        durations_ms: Screenshot duration samples
        inject_times: Axe injection time samples
        run_times: Axe run time samples
        llm_fail_status: Aggregated LLM failure counts by HTTP status
        llm_fail_finish: Aggregated LLM failure counts by finish_reason
        llm_fail_samples: Sample LLM failures for debugging

    Returns:
        Summary dictionary written to retry_summary.json artifact
    """
    summary = {
        "batch_pk": batch_pk,
        "total_requests": total_requests,
        "total_retries": total_retries,
        "requests_with_retries": requests_with_retries,
        "max_retries": max(retry_distribution.keys()) if retry_distribution else 0,
        "retry_distribution": retry_distribution,
        "effective_concurrency": concurrency,
        "timing_ms": {
            "http_queue_wait": compute_percentiles(http_wait_ms),
            "http_roundtrip": compute_percentiles(http_rtt_ms),
            "db_queue_wait": compute_percentiles(db_wait_ms),
        },
    }
    # Attach analysis summary if any was attempted
    if screenshot_total or screenshot_succeeded or screenshot_failed or screenshot_skipped:
        summary["analysis"] = {
            "total": screenshot_total,
            "succeeded": screenshot_succeeded,
            "failed": screenshot_failed,
            "skipped": screenshot_skipped,
            "axe_total": axe_total,
            "axe_succeeded": axe_succeeded,
            "axe_failed": axe_failed,
            "reasons": axe_failure_reasons,
            "timing_ms": compute_percentiles(durations_ms),
            "axe_timing_ms": {
                "inject_p95": compute_percentiles(inject_times).get("p95_ms", 0.0),
                "run_p95": compute_percentiles(run_times).get("p95_ms", 0.0),
            },
        }
        # Attach LLM failure analytics for visibility
        summary["llm_failures"] = {
            "status": llm_fail_status,
            "finish_reason": llm_fail_finish,
            "samples": llm_fail_samples,
        }
    return summary


async def _setup_browser_contexts(pw, num_workers: int):
    """Create browser and contexts from a playwright instance.

    Args:
        pw: Started playwright instance (from async_playwright context manager)
        num_workers: Number of browser contexts to create

    Returns:
        Tuple of (browser, contexts).
        Caller is responsible for closing browser.
    """
    from playwright.async_api import Error as PlaywrightError

    print("  Launching browser...", flush=True)
    browser = await pw.chromium.launch(headless=True)
    print(f"  Creating {num_workers} browser contexts...", flush=True)
    contexts = [
        await browser.new_context(viewport={"width": 1280, "height": 720})
        for _ in range(num_workers)
    ]

    # Pre-inject axe at context level when vendored script is present.
    # This is an OPTIMIZATION - per-page injection in screenshotter.py/_inject_axe()
    # is the fallback. Don't fail batch if context injection fails.
    axe_vendor_path = Path(__file__).parent / "vendor" / "axe.min.js"
    if axe_vendor_path.exists():
        print("  Injecting axe-core into contexts...", flush=True)
        axe_path_str = str(axe_vendor_path.resolve())
        injection_failures = 0
        for ctx in contexts:
            try:
                await ctx.add_init_script(path=axe_path_str)
            except PlaywrightError:
                injection_failures += 1
        if injection_failures == len(contexts):
            logger.error(
                "Axe pre-injection failed for ALL %d contexts - "
                "falling back to per-page injection (may be slower)",
                len(contexts),
            )
        elif injection_failures:
            logger.warning("Axe injection failed for %d/%d contexts", injection_failures, len(contexts))
    print("  Browser ready\n", flush=True)
    return browser, contexts


@dataclass
class LLMFailureTracker:
    """Tracks LLM failure analytics during batch execution."""

    status: dict[int, int]
    finish_reason: dict[str, int]
    samples: list[dict]
    by_model: dict[str, dict]

    @classmethod
    def create(cls) -> LLMFailureTracker:
        return cls(status={}, finish_reason={}, samples=[], by_model={})

    def record_failure(
        self,
        request_pk: int,
        last_status: int | str,
        finish_reason: str | None,
        model_key: str,
        category_slug: str,
    ) -> None:
        """Record an LLM failure for analytics."""
        if isinstance(last_status, int):
            self.status[last_status] = self.status.get(last_status, 0) + 1
        fr = finish_reason or ""
        if fr:
            self.finish_reason[fr] = self.finish_reason.get(fr, 0) + 1
        if model_key not in self.by_model:
            self.by_model[model_key] = {'count': 0, 'reasons': {}}
        self.by_model[model_key]['count'] += 1
        if fr:
            self.by_model[model_key]['reasons'][fr] = self.by_model[model_key]['reasons'].get(fr, 0) + 1
        if len(self.samples) < MAX_FAILURE_SAMPLES:
            self.samples.append({
                "request_pk": request_pk,
                "status": last_status,
                "finish_reason": fr,
                "model": model_key,
                "category": category_slug,
            })


def _print_llm_completion(
    req: dict | None,
    request_pk: int,
    ok: bool,
    attempts_used: int,
    last_status: int | str,
    finish_reason: str | None,
    provider: str | None,
    completed: int,
    total: int,
) -> None:
    """Print progress line for a completed LLM request."""
    if not req:
        return
    model = f"{req.get('company_slug','')}/{req.get('model_slug','')}"
    cat = req.get("category_slug", "")
    progress = f"[{completed}/{total}]" if total > 0 else f"[{request_pk}]"
    retry_indicator = f" [RETRY {attempts_used - 1}]" if attempts_used > 1 else ""
    provider_str = f" via {provider}" if provider else ""

    if ok:
        print(f"{progress} [OK] {model}/{cat} {last_status}{provider_str}{retry_indicator}\n")
    else:
        reason_str = f" ({finish_reason})" if finish_reason else ""
        print(f"{progress} [FAIL] {model}/{cat} {last_status}{reason_str}{provider_str}{retry_indicator}\n")


async def execute_pending_requests(batch_pk: int) -> dict:
    """Execute all pending requests for a batch with concurrent HTTP and streaming analysis.

    This is the main entry point called by collector.py. It:
    1. Fetches pending requests from database
    2. Sends them to OpenRouter concurrently (controlled by OPENROUTER_CONCURRENCY)
    3. Retries failed requests with exponential backoff
    4. Streams successful HTML to Playwright workers for screenshot+axe analysis
    5. Writes retry_summary.json with timing and failure analytics

    Returns a summary dict with success/failure counts, timing percentiles, and
    detailed failure breakdowns for diagnosis.
    """
    pending = get_pending_requests_for_batch(batch_pk)
    total = len(pending)
    if total == 0:
        return {"succeeded": 0, "failed": 0, "elapsed_minutes": 0.0}

    # Concurrency bounds
    configured = get_env_int("OPENROUTER_CONCURRENCY", 50)
    concurrency = max(1, min(total, configured))
    max_retries = get_env_int("OPENROUTER_MAX_RETRY_ATTEMPTS", 4)
    max_backoff = get_env_int("OPENROUTER_MAX_BACKOFF_SECONDS", 30)

    timeout = httpx.Timeout(60.0)
    # Semaphores control concurrency without thread pools.
    # HTTP: limit concurrent requests to avoid overwhelming OpenRouter.
    # DB: single writer prevents SQLite WAL contention (readers don't block).
    http_sem = asyncio.Semaphore(concurrency)
    db_sem = asyncio.Semaphore(1)

    start = datetime.now()
    succeeded = 0
    failed = 0
    total_retries = 0
    requests_with_retries = 0
    retry_distribution: dict[int, int] = {}
    http_wait_ms: list[float] = []
    http_rtt_ms: list[float] = []
    db_wait_ms: list[float] = []

    # For retry_summary path discovery
    any_artifact_path = (
        pending[0].get("html_path")
        or pending[0].get("request_json_path")
        or pending[0].get("response_json_path")
    )

    # Streaming analysis: screenshots are processed as LLM responses complete.
    # Workers = browser contexts, each processing one HTML at a time.
    # Queue max prevents unbounded memory growth if LLM responses outpace Playwright.
    # Cap workers at request count - no point spinning up 24 browsers for 2 requests.
    cpu = os.cpu_count() or 4
    max_by_cpu = min(24, max(2, cpu * 4))
    workers = min(max_by_cpu, total)
    q_max = workers * 3
    timeout_ms = get_env_int("SCREENSHOT_TIMEOUT_MS", 10000)
    wait_images_ms = get_env_int("SCREENSHOT_WAIT_IMAGES_MS", 3000)
    wait_fonts_ms = get_env_int("SCREENSHOT_WAIT_FONTS_MS", 2000)

    screenshot_total = 0
    metrics = AnalysisMetrics()  # Replaces 9 nonlocal counters in worker
    durations_ms: list[float] = []
    inject_times: list[float] = []
    run_times: list[float] = []
    axe_failure_reasons: dict[str, int] = {}
    axe_failure_samples: list[dict] = []

    # LLM failure analytics - defined here so they exist even if Playwright is missing
    llm_fail_status: dict[int, int] = {}
    llm_fail_finish: dict[str, int] = {}
    llm_fail_samples: list[dict] = []
    llm_fail_by_model: dict[str, dict] = {}

    # Pre-build lookup for O(1) access by request_pk
    req_map = {r["request_pk"]: r for r in pending}

    # Pre-flight message: show scope of work
    n_models = len({f"{r.get('company_slug')}/{r.get('model_slug')}" for r in pending})
    print(f"  Executing {total} requests across {n_models} models...", flush=True)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _execute_request(
                client,
                req,
                max_retries=max_retries,
                max_backoff=max_backoff,
                http_sem=http_sem,
                db_sem=db_sem,
                http_wait_ms_list=http_wait_ms,
                http_rtt_ms_list=http_rtt_ms,
                db_wait_ms_list=db_wait_ms,
            )
            for req in pending
        ]

        # Start Playwright and analysis workers
        try:
            from playwright.async_api import async_playwright

            from .screenshotter import screenshot_and_axe

            q: asyncio.Queue = asyncio.Queue(maxsize=q_max)
            wctx = WorkerContext(
                metrics=metrics,
                queue=q,
                total=total,
                timeout_ms=timeout_ms,
                wait_images_ms=wait_images_ms,
                wait_fonts_ms=wait_fonts_ms,
                durations_ms=durations_ms,
                inject_times=inject_times,
                run_times=run_times,
                axe_failure_reasons=axe_failure_reasons,
                axe_failure_samples=axe_failure_samples,
            )
            llm_tracker = LLMFailureTracker.create()

            async with async_playwright() as pw:
                browser, contexts = await _setup_browser_contexts(pw, workers)
                try:
                    worker_tasks = [
                        asyncio.create_task(_analysis_worker(ctx, wctx, screenshot_and_axe))
                        for ctx in contexts
                    ]

                    completed = 0
                    pending_tasks = {asyncio.create_task(coro) for coro in tasks}
                    heartbeat_started = False

                    while pending_tasks:
                        done, pending_tasks = await asyncio.wait(
                            pending_tasks, timeout=30.0, return_when=asyncio.FIRST_COMPLETED
                        )

                        # Heartbeat: after 30s with no responses, print waiting message then dots
                        if not done:
                            if not heartbeat_started:
                                print(f"  {total - completed} requests pending, waiting for providers...", end="", flush=True)
                                heartbeat_started = True
                            else:
                                print(".", end="", flush=True)
                            continue

                        # Got responses - newline if we were printing dots
                        if heartbeat_started:
                            print(flush=True)  # newline
                            heartbeat_started = False

                        for task in done:
                            _req_pk, ok, attempts_used, last_status, finish_reason, provider = task.result()
                            succeeded += 1 if ok else 0
                            failed += 0 if ok else 1
                            completed += 1

                            # Print progress and track retries
                            req = req_map.get(_req_pk)
                            _print_llm_completion(req, _req_pk, ok, attempts_used, last_status, finish_reason, provider, completed, total)

                            retries = max(0, attempts_used - 1)
                            total_retries += retries
                            if retries > 0:
                                requests_with_retries += 1
                            retry_distribution[retries] = retry_distribution.get(retries, 0) + 1

                            # Enqueue for analysis on success
                            if ok and req:
                                html_path = req.get("html_path")
                                if html_path:
                                    png_path = str(Path(html_path).with_suffix('.png'))
                                    screenshot_total += 1
                                    await q.put((_req_pk, html_path, png_path, completed))
                            elif not ok:
                                model_key = f"{(req or {}).get('company_slug','')}/{(req or {}).get('model_slug','')}"
                                llm_tracker.record_failure(
                                    _req_pk, last_status, finish_reason, model_key,
                                    (req or {}).get('category_slug', ''),
                                )

                    # Shutdown workers
                    for _ in range(workers):
                        await q.put(None)
                    await q.join()
                    for t in worker_tasks:
                        await t
                finally:
                    await browser.close()

            # Transfer tracker data to legacy variable names for summary building
            llm_fail_status = llm_tracker.status
            llm_fail_finish = llm_tracker.finish_reason
            llm_fail_samples = llm_tracker.samples
            llm_fail_by_model = llm_tracker.by_model

        except ImportError:
            # Playwright not installed: analysis skipped but collection still succeeds
            print("  [WARN] Streaming analysis skipped: Playwright not installed.\n"
                  "        Run: uv sync && uv run playwright install chromium\n")

    elapsed = (datetime.now() - start).total_seconds() / 60.0

    # Emit retry summary under the batch root
    summary = _build_retry_summary(
        batch_pk=batch_pk,
        total_requests=total,
        total_retries=total_retries,
        requests_with_retries=requests_with_retries,
        retry_distribution=retry_distribution,
        concurrency=concurrency,
        http_wait_ms=http_wait_ms,
        http_rtt_ms=http_rtt_ms,
        db_wait_ms=db_wait_ms,
        screenshot_total=screenshot_total,
        screenshot_succeeded=metrics.screenshot_succeeded,
        screenshot_failed=metrics.screenshot_failed,
        screenshot_skipped=metrics.screenshot_skipped,
        axe_total=metrics.axe_total,
        axe_succeeded=metrics.axe_succeeded,
        axe_failed=metrics.axe_failed,
        axe_failure_reasons=axe_failure_reasons,
        durations_ms=durations_ms,
        inject_times=inject_times,
        run_times=run_times,
        llm_fail_status=llm_fail_status,
        llm_fail_finish=llm_fail_finish,
        llm_fail_samples=llm_fail_samples,
    )
    try:
        write_retry_summary(any_artifact_path, summary)
    except Exception:
        logger.warning("Failed to write retry summary", exc_info=True)

    return _build_result_dict(
        succeeded=succeeded,
        failed=failed,
        elapsed_minutes=elapsed,
        total_retries=total_retries,
        requests_with_retries=requests_with_retries,
        retry_summary=summary,
        screenshot_total=screenshot_total,
        screenshot_succeeded=metrics.screenshot_succeeded,
        screenshot_failed=metrics.screenshot_failed,
        screenshot_skipped=metrics.screenshot_skipped,
        screenshot_retries=metrics.screenshot_retries,
        screenshot_retry_successes=metrics.screenshot_retry_successes,
        axe_total=metrics.axe_total,
        axe_succeeded=metrics.axe_succeeded,
        axe_failed=metrics.axe_failed,
        durations_ms=durations_ms,
        inject_times=inject_times,
        run_times=run_times,
        axe_failure_reasons=axe_failure_reasons,
        axe_failure_samples=axe_failure_samples,
        llm_fail_status=llm_fail_status,
        llm_fail_finish=llm_fail_finish,
        llm_fail_samples=llm_fail_samples,
        llm_fail_by_model=llm_fail_by_model,
    )
