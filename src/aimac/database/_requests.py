"""Internal. Import from aimac.database.

Request insertion and system prompt helpers.

This module handles the "request" side of the model×category testing pipeline:
- Creating request rows for each (model, category) pair to be tested
- Fetching the active system prompt used in all requests
- Finding pending requests (no successful response yet) for execution

Request lifecycle: create_batch → insert requests → execute → store responses
"""

from __future__ import annotations

import logging
import sqlite3

import aimac.database._core as _dbc
from aimac.database._core import DatabaseError

logger = logging.getLogger(__name__)


def _insert_model_category_request(
    conn: sqlite3.Connection,
    batch_pk: int,
    model_pk: int,
    category_pk: int,
    system_prompts_fk_pk: int,
    body_json: str,
) -> int:
    """Insert (or reuse) a model_categories_request row and return its PK.

    On IntegrityError (duplicate batch+model+category), fetches and returns
    the existing row's PK instead of failing. This allows idempotent retries.

    Args:
        conn: Active database connection.
        batch_pk: Batch primary key.
        model_pk: Model primary key.
        category_pk: Category primary key.
        system_prompts_fk_pk: System prompt primary key.
        body_json: JSON-encoded request body for OpenRouter API.

    Returns:
        Primary key of the inserted or existing request row.

    Raises:
        sqlite3.IntegrityError: If duplicate exists but cannot be fetched.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO model_categories_request (
                batches_fk_pk, models_fk_pk, categories_fk_pk,
                system_prompts_fk_pk, openrouter_request_body
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (batch_pk, model_pk, category_pk, system_prompts_fk_pk, body_json),
        )
        return int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        cursor.execute(
            """
            SELECT pk FROM model_categories_request
            WHERE batches_fk_pk = ? AND models_fk_pk = ? AND categories_fk_pk = ?
            """,
            (batch_pk, model_pk, category_pk),
        )
        row = cursor.fetchone()
        if row is None:
            raise
        return int(row[0])


def insert_model_category_request(
    batch_pk: int,
    model_pk: int,
    category_pk: int,
    system_prompts_fk_pk: int,
    body_json: str,
) -> int:
    """Insert a model_categories_request row with auto-managed connection.

    Handles connection lifecycle and commits the transaction automatically.
    If the row already exists (same batch+model+category), returns existing PK.

    Args:
        batch_pk: Batch primary key.
        model_pk: Model primary key.
        category_pk: Category primary key.
        system_prompts_fk_pk: System prompt primary key.
        body_json: JSON-encoded request body for OpenRouter API.

    Returns:
        Primary key of the inserted or existing request row.
    """
    conn = _dbc.get_connection()
    try:
        pk = _insert_model_category_request(
            conn, batch_pk, model_pk, category_pk, system_prompts_fk_pk, body_json
        )
        conn.commit()
        return pk
    finally:
        conn.close()


def insert_model_category_requests_many(
    batch_pk: int,
    rows: list[tuple[int, int, int, str]],
) -> int:
    """Bulk insert model_categories_request rows for a batch in one transaction.

    Args:
        batch_pk: Batch primary key.
        rows: List of tuples (model_pk, category_pk, system_prompts_fk_pk, body_json).

    Returns:
        Number of newly inserted rows (duplicates silently ignored via INSERT OR IGNORE).
        We count before/after rather than using rowcount because executemany's
        rowcount behavior varies across SQLite versions.
    """
    conn = _dbc.get_connection()
    try:
        cursor = conn.cursor()
        before = cursor.execute(
            "SELECT COUNT(*) FROM model_categories_request WHERE batches_fk_pk = ?",
            (batch_pk,),
        ).fetchone()[0]

        params = [
            (batch_pk, m, c, spk, body) for (m, c, spk, body) in rows
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO model_categories_request (
                batches_fk_pk, models_fk_pk, categories_fk_pk,
                system_prompts_fk_pk, openrouter_request_body
            ) VALUES (?, ?, ?, ?, ?)
            """,
            params,
        )
        conn.commit()
        after = cursor.execute(
            "SELECT COUNT(*) FROM model_categories_request WHERE batches_fk_pk = ?",
            (batch_pk,),
        ).fetchone()[0]
        return int(after - before)
    finally:
        conn.close()


def _get_active_system_prompt(conn: sqlite3.Connection) -> tuple[int, str]:
    """Return (system_prompts_fk_pk, prompt_text) for the active system prompt.

    Args:
        conn: Active database connection.

    Returns:
        Tuple of (system_prompts_fk_pk, prompt_text).

    Raises:
        DatabaseError: If no active system prompt is configured.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT system_prompts_fk_pk, prompt
        FROM view_system_prompt_active
        WHERE pk = 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise DatabaseError("Active system prompt not configured")
    spk = row[0]
    prompt = row[1]
    return int(spk), str(prompt)


def get_active_system_prompt() -> tuple[int, str]:
    """Fetch the active system prompt and its PK with auto-managed connection.

    Handles connection lifecycle automatically.

    Returns:
        Tuple of (system_prompts_fk_pk, prompt_text).

    Raises:
        DatabaseError: If no active system prompt is configured.
    """
    conn = _dbc.get_connection()
    try:
        return _get_active_system_prompt(conn)
    finally:
        conn.close()


def _get_pending_requests_for_batch(
    conn: sqlite3.Connection, batch_pk: int
) -> list[dict]:
    """Return pending request rows for a batch (no successful response yet).

    A request is "pending" if it has no response with http_status=200.
    Failed responses (4xx, 5xx, network errors) don't mark a request as complete,
    allowing retries.

    Note: This is for the API call stage only. "Pending" here means "needs API call",
    NOT "needs full pipeline completion". Screenshot/axe analysis happens downstream
    after http_status=200 responses. The Tier 2 cache checks use a stricter definition
    that requires BOTH http_status=200 AND axe_runs data.

    Returns dicts with: request_pk, body_json, html_path, request_json_path,
    response_json_path, company_slug, model_slug, category_slug.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        WITH filtered AS (
            SELECT
                req.pk AS request_pk,
                req.openrouter_request_body AS body_json,
                vm.company_slug,
                vm.model_slug,
                c.category_slug
            FROM model_categories_request AS req
            JOIN view_models vm ON vm.pk = req.models_fk_pk
            JOIN categories c ON req.categories_fk_pk = c.pk
            WHERE req.batches_fk_pk = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM model_categories_responses AS resp
                  JOIN view_model_categories_responses AS v ON v.pk = resp.pk
                  WHERE resp.model_categories_request_fk_pk = req.pk
                    AND v.http_status = 200
              )
            )
        SELECT
            f.request_pk,
            f.body_json,
            vap.html_path,
            vap.request_json_path,
            vap.response_json_path,
            f.company_slug,
            f.model_slug,
            f.category_slug
        FROM filtered AS f
        LEFT JOIN view_artifact_paths AS vap ON vap.request_pk = f.request_pk
        ORDER BY f.request_pk
        """,
        (batch_pk,),
    )
    rows = cursor.fetchall()
    results: list[dict] = []
    for r in rows:
        # Rows may be sequences or sqlite3.Row; access by index to keep it simple
        results.append(
            {
                "request_pk": int(r[0]),
                "body_json": str(r[1]) if r[1] is not None else "{}",
                "html_path": str(r[2]) if r[2] is not None else None,
                "request_json_path": str(r[3]) if r[3] is not None else None,
                "response_json_path": str(r[4]) if r[4] is not None else None,
                "company_slug": str(r[5]) if r[5] is not None else "",
                "model_slug": str(r[6]) if r[6] is not None else "",
                "category_slug": str(r[7]) if r[7] is not None else "",
            }
        )
    return results


def get_pending_requests_for_batch(batch_pk: int) -> list[dict]:
    """Fetch pending requests for a batch with auto-managed connection.

    Handles connection lifecycle automatically. Returns requests that have
    no successful (http_status=200) response yet.

    Args:
        batch_pk: Batch primary key.

    Returns:
        List of dicts with keys: request_pk, body_json, html_path,
        request_json_path, response_json_path, company_slug, model_slug,
        category_slug.
    """
    conn = _dbc.get_connection()
    try:
        return _get_pending_requests_for_batch(conn, batch_pk)
    finally:
        conn.close()
