"""OpenRouter API client.

Handles all HTTP communication with the OpenRouter API:
- fetch_top_models(): Sync call to get available models (used at collection start)
- send_completion(): Async call to generate HTML from a prompt (used in executor)

This module is the only place that knows about OpenRouter's API structure.
All other modules work with normalized Python dicts.

Environment:
- OPENROUTER_API_KEY: Required. API key for authentication.

See also:
- https://openrouter.ai/docs - OpenRouter API documentation
- src/aimac/executor.py - async batch execution using send_completion
- src/aimac/collector.py - orchestration using fetch_top_models
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_ERROR_LOG_LENGTH = 5000  # Characters of response/error text to log (truncate for readability)


def _get_headers() -> dict[str, str]:
    """Build headers for OpenRouter API requests.

    Includes authentication and identifying headers. The HTTP-Referer, X-Title,
    and User-Agent headers allow OpenRouter to attribute usage in their dashboard.

    Returns:
        dict[str, str]: HTTP headers including Authorization bearer token and
            identifying headers for OpenRouter dashboard attribution.

    Raises:
        ValueError: If OPENROUTER_API_KEY environment variable is not set.
    """
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment")

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aimac.ai",
        "X-Title": "AIMAC: AI Model Accessibility Checker",
        "User-Agent": "AIMAC/1.0 (+https://aimac.ai)",
    }


def fetch_top_models(category: str | None = "programming") -> list[dict[str, Any]]:
    """Fetch available models from OpenRouter API.

    Called once at the start of collection to get the current model list.
    Results are sorted by model ID for deterministic ordering (important for
    model_set canonicalization).

    Args:
        category: Model category to filter by (default: "programming").
            Passed as query parameter to OpenRouter /models endpoint.
            If None, fetches ALL models without category filtering.

    Returns:
        list[dict[str, Any]]: List of model dictionaries sorted by model ID.
            Returns empty list if response 'data' field is not a list.

    Raises:
        httpx.HTTPError: On API failure (network error, non-2xx status).
        ValueError: If OPENROUTER_API_KEY is not set or if response body
            is not valid JSON.
    """
    url = "https://openrouter.ai/api/v1/models"
    if category:
        url += f"?category={category}"

    logger.info(f"Fetching models from OpenRouter API: {url}")

    try:
        with httpx.Client() as client:
            response = client.get(url, headers=_get_headers())
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError:
                logger.error(
                    "Non-JSON response from OpenRouter /models endpoint "
                    "(status=%s, body=%r)",
                    response.status_code,
                    response.text[:MAX_ERROR_LOG_LENGTH],
                )
                raise

            models = data.get("data", [])
            if not isinstance(models, list):
                logger.error(
                    "Unexpected /models response shape: 'data' is %s, expected list",
                    type(models).__name__,
                )
                return []

            # Sort models by ID for consistent ordering
            models.sort(key=lambda m: m.get("id", ""))

            logger.info(f"Successfully fetched {len(models)} models from OpenRouter")
            return models

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch models from OpenRouter: {e}")
        raise


async def send_completion(
    client: httpx.AsyncClient,
    request_body: dict,
    *,
    timeout_seconds: float = 60.0,
) -> dict:
    """Send a chat completion request to OpenRouter.

    This is the core LLM call - sends a prompt and receives generated HTML.
    Called by executor.py in an async loop for each (model, category) pair.

    Args:
        client: Async HTTP client for making the request. Reused across
            multiple calls for connection pooling.
        request_body: OpenRouter chat completion request payload containing
            model, messages, and other API parameters.
        timeout_seconds: Request timeout in seconds (default: 60.0).

    Returns:
        dict: Normalized response with two keys:
            - status (int): HTTP status code, or -1 on network error.
            - json (dict): Parsed response body with 'http_status' field
                injected for SQL views. On error, contains 'error' dict
                with 'message' and details.

    Raises:
        ValueError: If OPENROUTER_API_KEY environment variable is not set.

    Notes:
        Network-related errors (timeout, connection) are normalized into the
        return dict rather than raised, enabling batch executor retry logic.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = _get_headers()
    try:
        resp = await client.post(
            url,
            headers=headers,
            json=request_body,
            timeout=timeout_seconds,
        )
        status = resp.status_code
        try:
            data = resp.json()
        except ValueError:
            # Not JSON; capture full response text for DB forensics
            data = {
                "http_status": status,
                "error": {
                    "message": "non_json_response",
                    "detail": resp.text,
                },
            }
        # Ensure http_status present for downstream logic
        if isinstance(data, dict) and "http_status" not in data:
            data["http_status"] = status
        return {"status": status, "json": data}
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError) as e:
        # Log at debug level - executor will handle retries and user-facing errors
        logger.debug(f"Network error calling OpenRouter (will retry): {e!s}")
        return {
            "status": -1,
            "json": {
                "http_status": -1,
                "error": {"message": "network_error", "detail": str(e)},  # Full error in DB
            },
        }
