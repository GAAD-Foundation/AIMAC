"""Internal. Import from aimac.database.

Category lookups and model ID resolution.

This module provides:
- Category lookups (enabled categories with their user prompts)
- Model ID → PK resolution

For Tier 2 cache queries (model×category pairs), see _model_category.py.
"""

from __future__ import annotations

from collections.abc import Sequence
import sqlite3

import aimac.database._core as _dbc


def _get_model_pks_by_ids(
    conn: sqlite3.Connection, model_ids: Sequence[str]
) -> dict[str, int]:
    """Map OpenRouter model IDs to database PKs.

    OpenRouter uses string IDs like "anthropic/claude-3-opus". Our database
    uses integer PKs for foreign keys. This resolves the mapping for a batch
    of model IDs in a single query.
    """
    if not model_ids:
        return {}
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(model_ids))
    cursor.execute(
        f"SELECT id, pk FROM models WHERE id IN ({placeholders})",
        tuple(model_ids),
    )
    return {row[0]: int(row[1]) for row in cursor.fetchall()}


def get_model_pks_by_ids(model_ids: Sequence[str]) -> dict[str, int]:
    """Map OpenRouter model IDs to database PKs.

    OpenRouter uses string IDs like "anthropic/claude-3-opus". Our database
    uses integer PKs for foreign keys. This resolves the mapping for a batch
    of model IDs in a single query.

    Args:
        model_ids: Sequence of OpenRouter model ID strings.

    Returns:
        Dictionary mapping model ID strings to their database PKs.
        Returns empty dict if model_ids is empty.
    """
    conn = _dbc.get_connection()
    try:
        return _get_model_pks_by_ids(conn, model_ids)
    finally:
        conn.close()


def _get_enabled_categories(conn: sqlite3.Connection) -> list[tuple[int, str, str, str | None]]:
    """Return enabled categories as (pk, category_slug, user_prompt, prompt_fragments).

    The enabled flag is immutable after seeding (enforced by DB trigger). The fixed
    set of 28 enabled categories is used for all benchmark runs.

    The user_prompt is the category-specific prompt sent to each model
    (e.g., "Create a contact form page" for the forms category).
    The prompt_fragments is JSON containing interchangeable text for anti-gaming randomization.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT pk, category_slug, user_prompt, prompt_fragments
        FROM categories
        WHERE enabled = 1
        ORDER BY category_slug ASC
        """
    )
    return [(int(r[0]), str(r[1]), str(r[2]), r[3]) for r in cursor.fetchall()]


def get_enabled_categories() -> list[tuple[int, str, str, str | None]]:
    """Return enabled categories with their user prompts and prompt fragments.

    The enabled flag is immutable after seeding (enforced by DB trigger). The fixed
    set of 28 enabled categories is used for all benchmark runs.

    The user_prompt is the category-specific prompt sent to each model
    (e.g., "Create a contact form page" for the forms category).
    The prompt_fragments is JSON containing interchangeable text for anti-gaming randomization.

    Returns:
        List of tuples (pk, category_slug, user_prompt, prompt_fragments) for all enabled
        categories, sorted by category_slug ascending.
    """
    conn = _dbc.get_connection()
    try:
        return _get_enabled_categories(conn)
    finally:
        conn.close()
