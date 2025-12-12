"""Internal. Import from aimac.database.

Response storage and evaluation helpers.

This module handles the "response" side of the model×category testing pipeline:
- Storing each API response attempt (including retries)
- Evaluating responses via view_model_categories_responses (http_status, html validity)

Multiple response attempts can exist per request (retries on failure).
Only responses with http_status=200 mark a request as "complete".
"""

from __future__ import annotations

import logging
import sqlite3

import aimac.database._core as _dbc

logger = logging.getLogger(__name__)


def _insert_response(
    conn: sqlite3.Connection,
    request_pk: int,
    attempt_number: int,
    response_json: str,
) -> int:
    """Insert a response attempt row and return its PK.

    Each request can have multiple response attempts (1, 2, 3...) when retries
    occur due to rate limits, timeouts, or server errors. All attempts are
    stored for debugging and cost tracking.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO model_categories_responses (
            model_categories_request_fk_pk,
            attempt_number,
            openrouter_response,
            response_timestamp
        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (request_pk, attempt_number, response_json),
    )
    return int(cursor.lastrowid)


def insert_response(
    request_pk: int, attempt_number: int, response_json: str
) -> int:
    """Insert a response attempt and return its primary key.

    Stores a single API response attempt in the database. Multiple attempts
    can exist for one request when retries occur due to rate limits, timeouts,
    or server errors.

    Args:
        request_pk: Primary key of the parent request row.
        attempt_number: Sequential attempt number (1, 2, 3...) for this request.
        response_json: Full OpenRouter API response as JSON string.

    Returns:
        Primary key of the newly inserted response row.
    """
    conn = _dbc.get_connection()
    try:
        pk = _insert_response(conn, request_pk, attempt_number, response_json)
        conn.commit()
        return pk
    finally:
        conn.close()


def _get_response_evaluation(
    conn: sqlite3.Connection, response_pk: int
) -> tuple[int, int, str | None]:
    """Return (http_status, html_is_valid, html_page) from the view for a response PK.

    The view (view_model_categories_responses) extracts http_status from the JSON
    and validates that the response contains usable HTML. html_is_valid=1 means
    the response has extractable HTML content suitable for accessibility testing.

    Returns (500, 0, None) if the view is missing or the response row not found -
    treats missing data as a server error to trigger retry logic.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT http_status, html_is_valid, html_page
        FROM view_model_categories_responses
        WHERE pk = ?
        """,
        (response_pk,),
    )
    row = cursor.fetchone()
    if row is None:
        # View not present or row missing - treat as failure to trigger retry
        logger.warning(
            "Response evaluation fallback: pk=%d not found in view (view missing or row deleted)",
            response_pk,
        )
        return 500, 0, None
    http_status = int(row[0]) if row[0] is not None else 500
    html_is_valid = int(row[1]) if row[1] is not None else 0
    html_page = row[2]
    return http_status, html_is_valid, html_page


def get_response_evaluation(response_pk: int) -> tuple[int, int, str | None]:
    """Fetch evaluation fields for a response row.

    Retrieves HTTP status, HTML validity, and extracted HTML from the
    view_model_categories_responses view. This view parses the stored
    OpenRouter JSON response to extract status codes and validate HTML content.

    Args:
        response_pk: Primary key of the response row to evaluate.

    Returns:
        Tuple of (http_status, html_is_valid, html_page) where:
        - http_status: HTTP status code from the response (500 if missing)
        - html_is_valid: 1 if response contains valid HTML, 0 otherwise
        - html_page: Extracted HTML content or None if invalid/missing
    """
    conn = _dbc.get_connection()
    try:
        return _get_response_evaluation(conn, response_pk)
    finally:
        conn.close()

