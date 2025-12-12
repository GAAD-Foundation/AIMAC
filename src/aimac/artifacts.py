"""Artifact file writing for benchmark execution.

Handles all file I/O for the executor's request/response cycle:
- Request JSON: API payload sent to OpenRouter (written once per request)
- Response JSON: API responses (written per retry attempt for debugging)
- HTML: Generated accessibility test pages (written on success)
- Retry summary: Batch-level statistics (retries, timeouts, final states)

Separating file I/O from executor.py keeps orchestration logic focused on
API communication and retry decisions, not filesystem operations.

Directory structure created by write_artifacts():
    output/batch_123/
        company/
            model_name/
                category/
                    item.request.json
                    item.response.json (or .attempt2.json on retry)
                    item.html

See also:
- src/aimac/executor.py - calls write_artifacts() after each API response
- README.md - output directory structure documentation
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _ensure_parent_dirs(path_str: str | None) -> None:
    """Create parent directories for a file path if they don't exist."""
    if not path_str:
        return
    Path(path_str).parent.mkdir(parents=True, exist_ok=True)


def _response_attempt_path(base_response_json_path: str | None, attempt_number: int) -> str | None:
    """Convert base response path to attempt-specific path.

    Attempt 1 uses the base path (matches what's stored in DB).
    Retries (attempt 2+) get separate files for debugging:
        attempt 1 -> item.response.json
        attempt 2 -> item.response.attempt2.json
        attempt 3 -> item.response.attempt3.json
    """
    if not base_response_json_path:
        return None

    # Attempt 1 uses base path (matches DB's view_artifact_paths.response_json_path)
    if attempt_number == 1:
        return base_response_json_path

    # Attempt 2+ gets suffix for debugging retry history
    if base_response_json_path.endswith(".response.json"):
        return base_response_json_path.replace(
            ".response.json", f".response.attempt{attempt_number}.json"
        )
    # Fallback for non-standard paths: append suffix
    return base_response_json_path + f".attempt{attempt_number}"


def write_artifacts(
    request_json_path: str | None,
    base_response_json_path: str | None,
    html_path: str | None,
    request_body: dict,
    response_json: dict,
    html_content: str | None,
    attempt_number: int,
) -> dict[str, bool]:
    """Write request/response artifacts to disk.

    Args:
        request_json_path: Path for request JSON (written only on attempt 1).
            Example: "batch_123/company/model/category/item.request.json"
        base_response_json_path: Base path for response JSON (written per attempt).
            Example: "batch_123/.../item.response.json" -> "item.response.attempt2.json"
        html_path: Path for HTML output (written only on success).
        request_body: The API request payload to write.
        response_json: The API response to write.
        html_content: HTML content to write (if provided).
        attempt_number: Current attempt number (1-indexed).

    Returns:
        Dict indicating which artifacts were written successfully:
        {"request": bool, "response": bool, "html": bool}

    Behavior:
        - Request JSON only on first attempt (attempt_number == 1)
        - Response JSON for each attempt
        - HTML only on success (html_content provided)
    """
    results = {"request": False, "response": False, "html": False}

    # Request JSON (pretty-printed) on first attempt only
    if attempt_number == 1 and request_json_path:
        _ensure_parent_dirs(request_json_path)
        try:
            with open(request_json_path, "w", encoding="utf-8") as f:
                json.dump(request_body, f, indent=2)
            results["request"] = True
        except OSError as e:
            logger.warning(f"Failed writing request JSON to {request_json_path}: {e}", exc_info=True)

    # Response JSON per attempt
    resp_path = _response_attempt_path(base_response_json_path, attempt_number)
    if resp_path:
        _ensure_parent_dirs(resp_path)
        try:
            with open(resp_path, "w", encoding="utf-8") as f:
                json.dump(response_json, f, indent=2)
            results["response"] = True
        except OSError as e:
            logger.warning(f"Failed writing response JSON to {resp_path}: {e}", exc_info=True)

    # HTML only on success
    if html_content and html_path:
        _ensure_parent_dirs(html_path)
        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            results["html"] = True
        except OSError as e:
            logger.warning(f"Failed writing HTML artifact to {html_path}: {e}", exc_info=True)

    return results


def _find_batch_root_from_any_artifact(path_str: str | None) -> Path | None:
    """Find the batch_N directory from any artifact file path.

    Walks up the directory tree looking for a directory starting with "batch_".
    Returns None if not found (caller should skip writing rather than guess).
    """
    if not path_str:
        return None
    p = Path(path_str)
    for parent in [p] + list(p.parents):
        if parent.name.startswith("batch_"):
            return parent

    logger.warning(
        "Batch root not found for %s; retry summary will not be written.",
        path_str,
    )
    return None


def write_retry_summary(
    any_artifact_path: str | None,
    summary: dict,
) -> None:
    """Write a retry summary JSON next to the batch root (retry_summary.json).

    Walks up the directory tree from the given artifact path to find the batch_N
    directory, then writes the summary there. If we cannot derive the batch root,
    this function silently returns.

    Args:
        any_artifact_path: Path to any artifact file within the batch directory
            (e.g., "batch_123/company/model/item.request.json"). Used to locate
            the batch root directory.
        summary: Dictionary containing retry statistics and batch-level metrics
            to write to retry_summary.json.

    Returns:
        None. Logs a warning if batch root cannot be found or write fails.
    """
    root = _find_batch_root_from_any_artifact(any_artifact_path)
    if not root:
        return
    out_path = root / "retry_summary.json"
    _ensure_parent_dirs(str(out_path))
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except OSError as e:
        logger.warning(f"Failed writing retry summary to {out_path}: {e}", exc_info=True)

