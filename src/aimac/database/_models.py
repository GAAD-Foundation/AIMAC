"""Internal. Import from aimac.database.

Models and model_sets helpers.

This module handles:
- `models` table: Individual AI model metadata from OpenRouter API
- `model_sets` table: Canonical groupings of models used as cache keys

Model sets enable the Tier 1 leaderboard cache: if the same set of models
has been tested before, we can reuse the existing leaderboard without
re-running expensive API calls and accessibility tests.
"""

from __future__ import annotations

import json as _json
import logging
import sqlite3

import aimac.database._core as _dbc

logger = logging.getLogger(__name__)


def canonicalize_model_ids(model_ids: list[str]) -> str:
    """Return the canonical JSON array representation for model IDs.

    Canonicalization ensures that equivalent model lists produce identical
    database keys, enabling cache hits when the same models are tested in
    different orders or with different casing.

    Rules (must match database triggers in 004_model_sets.sql):
    1. Lowercase all IDs
    2. Remove all spaces from IDs
    3. Deduplicate
    4. Sort alphabetically
    5. Format as compact JSON array (no whitespace)

    Example: ["GPT-4", "claude-3-opus", "GPT-4"] -> '["claude-3-opus","gpt-4"]'
    """
    normalized = {
        value
        for value in (
            # remove spaces and lowercase
            model_id.replace(' ', '').lower() for model_id in model_ids
        )
        if value
    }
    sorted_ids = sorted(normalized)
    return _json.dumps(sorted_ids, separators=(',', ':'))


def _upsert_model_set_transactional(
    conn: sqlite3.Connection, model_ids: list[str]
) -> int:
    """Insert a model set or return the primary key of an existing one.

    Note: Empty model_ids will be rejected by the SQL trigger in 004_model_sets.sql
    (COALESCE treats empty arrays as invalid). No Python guard needed here because
    the only production caller (collector.py) already raises ValueError if no
    models are fetched from the API.

    Why SELECT-then-INSERT instead of INSERT OR IGNORE?

    We need the PK of the row, whether it was just inserted or already existed.
    INSERT OR IGNORE would skip the insert for existing rows, leaving lastrowid
    as 0 (or the last successful insert's ID) rather than the existing row's PK.

    This pattern is called "upsert with PK return" and is necessary because
    SQLite's ON CONFLICT doesn't provide RETURNING in all cases, and INSERT OR
    IGNORE doesn't give us the existing row's PK.

    Note: This function does NOT commit. Caller is responsible for transaction
    management. See ARCHITECTURE.md for connection pattern documentation.
    """
    canonical = canonicalize_model_ids(model_ids)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pk FROM model_sets WHERE sorted_model_list = ?",
        (canonical,),
    )
    row = cursor.fetchone()
    if row is not None:
        return row['pk'] if isinstance(row, sqlite3.Row) else row[0]

    cursor.execute(
        "INSERT INTO model_sets (sorted_model_list) VALUES (?)",
        (canonical,),
    )
    return cursor.lastrowid


def upsert_model_set(model_ids: list[str]) -> int:
    """Insert a model set or return the primary key of an existing one.

    This is the public convenience wrapper that manages its own connection.
    Use this for simple, single-operation calls.

    For atomic transactions across multiple tables (e.g., creating a model_set
    and its leaderboard together), use _upsert_model_set_transactional with
    an externally managed connection instead.

    See ARCHITECTURE.md "Database Connection Patterns" for details.
    """
    conn = _dbc.get_connection()
    try:
        pk = _upsert_model_set_transactional(conn, model_ids)
        conn.commit()
        return pk
    finally:
        conn.close()


def _get_model_set(conn: sqlite3.Connection, model_ids: list[str]) -> dict | None:
    """Fetch a model set row by its canonicalized model IDs.

    Returns a dict with pk, sorted_model_list, created_at, updated_at,
    or None if not found.

    Note: The isinstance(row, sqlite3.Row) check handles different connection
    configurations. When row_factory is set to sqlite3.Row (our default),
    we can call dict(row) directly. Otherwise, we manually construct the dict
    from cursor.description.
    """
    canonical = canonicalize_model_ids(model_ids)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT pk, sorted_model_list, created_at, updated_at
        FROM model_sets
        WHERE sorted_model_list = ?
        """,
        (canonical,),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    columns = [column[0] for column in cursor.description]
    return {column: row[index] for index, column in enumerate(columns)}


def get_model_set(model_ids: list[str]) -> dict | None:
    """Fetch a model set row by its canonicalized model IDs.

    This is a convenience wrapper that manages its own connection.
    For atomic transactions across multiple tables, use _get_model_set
    with an externally managed connection instead.

    Args:
        model_ids: List of model ID strings to canonicalize and lookup.
                   IDs are normalized (lowercased, spaces removed, deduplicated,
                   sorted) before querying.

    Returns:
        Dict with keys: pk, sorted_model_list, created_at, updated_at,
        or None if no matching model set exists.
    """
    conn = _dbc.get_connection()
    try:
        return _get_model_set(conn, model_ids)
    finally:
        conn.close()


def _upsert_models(conn: sqlite3.Connection, models: list[dict]) -> int:
    """Insert or update models in the database.

    Models come from the OpenRouter API (see openrouter.fetch_top_models).
    Each model dict contains: id, name, description, context_length,
    supported_parameters, pricing, created, canonical_slug, hugging_face_id.

    Why UPDATE-first instead of INSERT OR REPLACE?

    INSERT OR REPLACE would delete and re-insert the row, which:
    1. Resets created_at to now (losing the original insert time)
    2. Changes the PK (if auto-increment)
    3. Could cascade deletes if foreign keys reference this row

    The UPDATE-then-INSERT pattern preserves the original row's metadata
    while updating changed fields. This is important for tracking when
    models were first seen vs. when their metadata last changed.

    Manual override columns (manual_model_display_name, manual_company_display_name)
    are intentionally NOT included in the UPDATE. This ensures that human-set
    overrides are preserved when API data refreshes. The view_models view uses
    COALESCE to prefer manual overrides over API-derived values.

    Note: Does NOT commit. Caller manages the transaction.
    """
    cursor = conn.cursor()

    upserted_count = 0
    for model in models:
        model_id = model['id']
        name = model.get('name', '')
        description = model.get('description', '')
        context_length = model.get('context_length', 0)

        supported_params = _json.dumps(model.get('supported_parameters', []))
        pricing = _json.dumps(model.get('pricing', {}))

        created = model.get('created', 0)
        canonical_slug = model.get('canonical_slug')
        hugging_face_id = model.get('hugging_face_id')

        # Prefer explicit UPDATE to avoid relying on ON CONFLICT semantics
        cursor.execute(
            """
            UPDATE models SET
                name = ?,
                description = ?,
                context_length = ?,
                supported_parameters = ?,
                pricing = ?,
                created = ?,
                canonical_slug = ?,
                hugging_face_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                name,
                description,
                context_length,
                supported_params,
                pricing,
                created,
                canonical_slug,
                hugging_face_id,
                model_id,
            ),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO models (
                    id, name, description, context_length,
                    supported_parameters, pricing, created,
                    canonical_slug, hugging_face_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    name,
                    description,
                    context_length,
                    supported_params,
                    pricing,
                    created,
                    canonical_slug,
                    hugging_face_id,
                ),
            )
        upserted_count += 1

    logger.info(f"Upserted {upserted_count} models to database")
    return upserted_count


def upsert_models(models: list[dict]) -> int:
    """Insert or update models in the database.

    This is a convenience wrapper that manages its own connection.
    Models come from the OpenRouter API (see openrouter.fetch_top_models).
    Manual override columns (manual_model_display_name, manual_company_display_name)
    are preserved during API refreshes.

    See _upsert_models for implementation details including why UPDATE-first
    is used instead of INSERT OR REPLACE.

    Args:
        models: List of model dicts from OpenRouter API. Each dict should contain:
                id (required), name, description, context_length, supported_parameters,
                pricing, created, canonical_slug, hugging_face_id.

    Returns:
        Number of models successfully upserted.
    """
    conn = _dbc.get_connection()
    try:
        pk = _upsert_models(conn, models)
        conn.commit()
        return pk
    finally:
        conn.close()
