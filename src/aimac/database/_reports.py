"""Internal. Import from aimac.database.

Read-Only Reporting Queries
===========================

Provides query helpers for the CLI reporter (reporter.py). All functions:

- Accept an open sqlite3.Connection (caller owns transaction scope)
- Return plain Python dicts/lists (no ORM, no custom types)
- Are read-only (SELECT queries only, no mutations)

Key query patterns:

- **Leaderboard data**: get_active_leaderboard, get_leaderboard_rows
- **Latest success lookups**: latest_success_by_category_for_model, latest_success_by_model_for_category
  (finds most recent HTTP 200 response per model×category pair)
- **Fuzzy search**: fuzzy_find_models, fuzzy_find_categories (CLI interactive selection)
- **Category lookup**: get_enabled_category_info, get_category_by_pk

These functions live in the database layer (not reporter.py) to:
1. Keep SQL centralized and testable
2. Enforce architecture layering (reporter.py has no raw SQL)

See also:
- src/aimac/reporter.py - CLI consumer
- tests/test_architecture_layering.py - enforces no SQL outside database/
"""

from __future__ import annotations

import sqlite3
from typing import Any


def get_active_leaderboard(conn: sqlite3.Connection) -> dict | None:
    """Return the active leaderboard info, or None if none is set.

    The active leaderboard is used as the default for CLI reports.

    Args:
        conn: Open sqlite3 database connection.

    Returns:
        Dict with keys: pk, created_at, model_set_id, or None if no active leaderboard.
    """
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT la.leaderboards_fk_pk AS pk, l.created_at, l.model_sets_fk_pk AS model_set_id
        FROM leaderboard_active AS la
        JOIN leaderboards AS l ON l.pk = la.leaderboards_fk_pk
        WHERE la.pk = 1
        """
    ).fetchone()
    if not row:
        return None
    return {"pk": int(row[0]), "created_at": str(row[1]), "model_set_id": int(row[2]) if row[2] is not None else None}

def get_leaderboard_rows(conn: sqlite3.Connection, leaderboard_pk: int) -> list[dict[str, Any]]:
    """Return per-model summary rows for a leaderboard, sorted by rank.

    Each row contains display-ready fields from model_categories_summary:
    - rank, model_pk, model_id, company, model (identity)
    - median, mean, stddev, p90 (score metrics)
    - total_violations, cost, avg_cost_per_page (performance metrics)
    - created_at (earliest request timestamp for this model)

    The subquery for created_at finds the first benchmark request for each model,
    giving a "when was this model first tested" date for display.

    Args:
        conn: Open sqlite3 database connection.
        leaderboard_pk: Primary key of the leaderboard to query.

    Returns:
        List of dicts with per-model summary data, sorted by rank ascending.
    """
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT
            s.ranking               AS rank,
            s.models_fk_pk AS model_pk,
            m.id           AS model_id,
            vm.company_name AS company,
            vm.model_name   AS model,
            s.median_weighted_score AS median,
            s.avg_axe_score         AS mean,
            s.stddev_weighted_score AS stddev,
            s.p90_weighted_score    AS p90,
            s.total_violations      AS total_violations,
            s.total_cost_usd        AS cost,
            s.avg_cost_per_page     AS avg_cost_per_page,
            (SELECT MIN(created_at) FROM model_categories_request
             WHERE models_fk_pk = s.models_fk_pk) AS created_at
        FROM model_categories_summary AS s
        JOIN models m ON m.pk = s.models_fk_pk
        JOIN view_models vm ON vm.pk = m.pk
        WHERE s.leaderboards_fk_pk = ?
        ORDER BY s.ranking ASC
        """,
        (leaderboard_pk,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "rank": int(r[0]) if r[0] is not None else None,
                "model_pk": int(r[1]),
                "model_id": str(r[2]),
                "company": None if r[3] is None else str(r[3]),
                "model": None if r[4] is None else str(r[4]),
                "median": None if r[5] is None else float(r[5]),
                "mean": None if r[6] is None else float(r[6]),
                "total_violations": None if r[9] is None else int(r[9]),
                "cost": None if r[10] is None else float(r[10]),
                "avg_cost_per_page": None if r[11] is None else float(r[11]),
                "stddev": None if r[7] is None else float(r[7]),
                "p90": None if r[8] is None else float(r[8]),
                "created_at": None if r[12] is None else str(r[12]),
            }
        )
    return out

def get_models_for_leaderboard(conn: sqlite3.Connection, leaderboard_pk: int) -> list[dict[str, Any]]:
    """Return all models in a leaderboard's model_set, sorted by pk.

    Used to get the full model list even before summaries exist. The model_set's
    sorted_model_list JSON is unpacked to get model IDs, then joined to models
    and view_models for display names.

    Args:
        conn: Open sqlite3 database connection.
        leaderboard_pk: Primary key of the leaderboard to query.

    Returns:
        List of dicts with model_pk, model_id, company, model fields.
    """
    cur = conn.cursor()
    rows = cur.execute(
        """
        WITH ms AS (
            SELECT value AS id
            FROM model_sets, json_each(model_sets.sorted_model_list)
            WHERE model_sets.pk = (SELECT model_sets_fk_pk FROM leaderboards WHERE pk = ?)
        )
        SELECT m.pk AS model_pk, m.id AS model_id, vm.company_name, vm.model_name
        FROM models AS m
        JOIN ms ON ms.id = m.id
        JOIN view_models vm ON vm.pk = m.pk
        ORDER BY m.pk ASC
        """,
        (leaderboard_pk,),
    ).fetchall()
    return [
        {
            "model_pk": int(r[0]),
            "model_id": str(r[1]),
            "company": None if r[2] is None else str(r[2]),
            "model": None if r[3] is None else str(r[3]),
        }
        for r in rows
    ]


def get_enabled_category_info(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return the 28 enabled benchmark categories, sorted by pk.

    Categories are immutable in AIMAC - the 28 enabled categories are fixed.
    This returns display info (pk, slug, name) for building category listings.

    Args:
        conn: Open sqlite3 database connection.

    Returns:
        List of dicts with category_pk, slug, name fields for enabled categories.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT pk, category_slug, name FROM categories WHERE enabled = 1 ORDER BY pk ASC"
    ).fetchall()
    return [
        {"category_pk": int(r[0]), "slug": str(r[1]), "name": str(r[2])}
        for r in rows
    ]


def latest_success_by_category_for_model(
    conn: sqlite3.Connection, model_pk: int, category_pks: list[int]
) -> dict[int, dict[str, Any]]:
    """Find the most recent successful response for each category, for one model.

    This is the "model detail" view: given a model, show its best result per
    category. Results are ordered by timestamp DESC and deduplicated to keep
    only the latest per category.

    Args:
        conn: Open sqlite3 database connection.
        model_pk: Primary key of the model to query.
        category_pks: List of category primary keys to filter by.

    Returns:
        Dict keyed by category_pk with the latest HTTP 200 response data including:
        request_pk, timestamp, cost, provider, weighted_score, violations, paths.
    """
    if not category_pks:
        return {}
    cp = ",".join(["?"] * len(category_pks))
    params: tuple[Any, ...] = (model_pk, *category_pks)
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT
            r.categories_fk_pk AS category_pk,
            r.pk AS request_pk,
            v.timestamp,
            v.cost,
            v.provider,
            v.system_fingerprint,
            a.weighted_score,
            a.total_violations,
            a.critical_violations,
            a.serious_violations,
            ap.png_path,
            ap.html_path,
            a.axe_json_path
        FROM model_categories_responses AS resp
        JOIN model_categories_request AS r
          ON resp.model_categories_request_fk_pk = r.pk
        JOIN view_model_categories_responses AS v
          ON v.pk = resp.pk
        LEFT JOIN axe_runs AS a
          ON a.model_categories_request_fk_pk = r.pk
        LEFT JOIN view_artifact_paths AS ap
          ON ap.request_pk = r.pk
        WHERE v.http_status = 200
          AND r.models_fk_pk = ?
          AND r.categories_fk_pk IN ({cp})
        ORDER BY r.categories_fk_pk ASC, v.timestamp DESC
        """,
        params,
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        cpk = int(r[0])
        # Keep the first (latest by timestamp) for each category
        if cpk in out:
            continue
        out[cpk] = {
            "request_pk": int(r[1]),
            "timestamp": str(r[2]) if r[2] is not None else None,
            "cost": None if r[3] is None else float(r[3]),
            "provider": None if r[4] is None else str(r[4]),
            "system_fingerprint": None if r[5] is None else str(r[5]),
            "weighted_score": None if r[6] is None else float(r[6]),
            "total_violations": None if r[7] is None else int(r[7]),
            "critical": None if r[8] is None else int(r[8]),
            "serious": None if r[9] is None else int(r[9]),
            "screenshot": None if r[10] is None else str(r[10]),
            "html_path": None if r[11] is None else str(r[11]),
            "axe_json_path": None if r[12] is None else str(r[12]),
        }
    return out


def latest_success_by_model_for_category(
    conn: sqlite3.Connection, category_pk: int, model_pks: list[int]
) -> dict[int, dict[str, Any]]:
    """Find the most recent successful response for each model, for one category.

    This is the "category detail" view: given a category, show how each model
    performed. Results are ordered by timestamp DESC and deduplicated to keep
    only the latest per model.

    Args:
        conn: Open sqlite3 database connection.
        category_pk: Primary key of the category to query.
        model_pks: List of model primary keys to filter by.

    Returns:
        Dict keyed by model_pk with the latest HTTP 200 response data including:
        request_pk, timestamp, cost, provider, weighted_score, violations, axe_json_path.
    """
    if not model_pks:
        return {}
    mp = ",".join(["?"] * len(model_pks))
    params: tuple[Any, ...] = (category_pk, *model_pks)
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT
            r.models_fk_pk AS model_pk,
            r.pk AS request_pk,
            v.timestamp,
            v.cost,
            v.provider,
            v.system_fingerprint,
            a.weighted_score,
            a.total_violations,
            a.critical_violations,
            a.serious_violations,
            a.axe_json_path
        FROM model_categories_responses AS resp
        JOIN model_categories_request AS r
          ON resp.model_categories_request_fk_pk = r.pk
        JOIN view_model_categories_responses AS v
          ON v.pk = resp.pk
        LEFT JOIN axe_runs AS a
          ON a.model_categories_request_fk_pk = r.pk
        WHERE v.http_status = 200
          AND r.categories_fk_pk = ?
          AND r.models_fk_pk IN ({mp})
        ORDER BY r.models_fk_pk ASC, v.timestamp DESC
        """,
        params,
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        mpk = int(r[0])
        if mpk in out:
            continue
        out[mpk] = {
            "request_pk": int(r[1]),
            "timestamp": str(r[2]) if r[2] is not None else None,
            "cost": None if r[3] is None else float(r[3]),
            "provider": None if r[4] is None else str(r[4]),
            "system_fingerprint": None if r[5] is None else str(r[5]),
            "weighted_score": None if r[6] is None else float(r[6]),
            "total_violations": None if r[7] is None else int(r[7]),
            "critical": None if r[8] is None else int(r[8]),
            "serious": None if r[9] is None else int(r[9]),
            "axe_json_path": None if r[10] is None else str(r[10]),
        }
    return out


def fuzzy_find_models(conn: sqlite3.Connection, q: str) -> list[dict[str, Any]]:
    """Find models matching a search query (CLI interactive selection).

    Matches against model id (exact or substring), company name, or model name.
    Case-insensitive. Used by CLI `aimac report model <query>` to resolve
    partial model names to actual model records.

    Args:
        conn: Open sqlite3 database connection.
        q: Search query string (matched against model id, company, or model name).

    Returns:
        List of dicts with model_pk, model_id, company, model fields, sorted by id.
    """
    q_norm = q.strip().lower()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT vm.pk, vm.id, vm.company_name, vm.model_name
        FROM view_models AS vm
        WHERE lower(vm.id) = ?
           OR lower(vm.id) LIKE '%' || ? || '%'
           OR (vm.company_name IS NOT NULL AND lower(vm.company_name) LIKE '%' || ? || '%')
           OR (vm.model_name   IS NOT NULL AND lower(vm.model_name)   LIKE '%' || ? || '%')
        ORDER BY vm.id ASC
        """,
        (q_norm, q_norm, q_norm, q_norm),
    ).fetchall()
    return [
        {
            "model_pk": int(r[0]),
            "model_id": str(r[1]),
            "company": None if r[2] is None else str(r[2]),
            "model": None if r[3] is None else str(r[3]),
        }
        for r in rows
    ]


def fuzzy_find_categories(conn: sqlite3.Connection, q: str) -> list[dict[str, Any]]:
    """Find categories matching a search query (CLI interactive selection).

    Matches against category slug (exact or substring) or name. Case-insensitive.
    Only searches enabled categories (the fixed 28). Used by CLI
    `aimac report category <query>` to resolve partial category names.

    Args:
        conn: Open sqlite3 database connection.
        q: Search query string (matched against category slug or name).

    Returns:
        List of dicts with category_pk, slug, name, enabled fields, sorted by slug.
    """
    q_norm = q.strip().lower()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT pk, category_slug, name, enabled
        FROM categories
        WHERE enabled = 1
          AND (lower(category_slug) = ?
           OR lower(category_slug) LIKE '%' || ? || '%'
           OR lower(name) LIKE '%' || ? || '%')
        ORDER BY category_slug ASC
        """,
        (q_norm, q_norm, q_norm),
    ).fetchall()
    return [
        {
            "category_pk": int(r[0]),
            "slug": str(r[1]),
            "name": str(r[2]),
            "enabled": int(r[3]) if r[3] is not None else 0,
        }
        for r in rows
    ]


def get_category_by_pk(conn: sqlite3.Connection, category_pk: int) -> dict | None:
    """Look up a category by numeric primary key.

    Unlike fuzzy_find_categories, this returns any category (enabled or disabled)
    and is used when the user provides a numeric ID directly.

    Args:
        conn: Open sqlite3 database connection.
        category_pk: Primary key of the category to retrieve.

    Returns:
        Dict with category_pk, slug, name, enabled fields, or None if not found.
    """
    cur = conn.cursor()
    row = cur.execute(
        "SELECT pk, category_slug, name, enabled FROM categories WHERE pk = ?",
        (category_pk,),
    ).fetchone()
    if not row:
        return None
    return {
        "category_pk": int(row[0]),
        "slug": str(row[1]),
        "name": str(row[2]),
        "enabled": int(row[3]) if row[3] is not None else 0,
    }
