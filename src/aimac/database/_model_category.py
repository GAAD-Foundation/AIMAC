"""Internal. Import from aimac.database.

Model×Category pair operations (Tier 2 cache).

This module provides queries for checking which model×category pairs have
cached successful responses. Used to skip expensive API calls when we
already have valid HTML output and accessibility test results.

Tier 2 cache concept: Before making expensive API calls, check if we already
have successful (http_status=200 + axe_runs) responses for each model×category
pair. Pairs with cached successes can be skipped; only missing pairs need
new requests.

Primary function: get_tier2_pairs_with_costs() returns both the full cartesian
product of pairs and costs for cached pairs in a single SQL query.
"""

from __future__ import annotations

from collections.abc import Sequence
import sqlite3

import aimac.database._core as _dbc


def _get_cached_success_pairs(
    conn: sqlite3.Connection,
    model_pks: Sequence[int],
    category_pks: Sequence[int],
) -> set[tuple[int, int]]:
    """Return (model_pk, category_pk) pairs that have a cached successful response.

    "Successful" means http_status=200 AND an axe_runs row exists.
    HTTP 200 without axe data is NOT considered cached - the pair needs re-running.

    These pairs can be skipped when preparing new requests - we already have
    valid HTML output and accessibility test results for them.
    """
    if not model_pks or not category_pks:
        return set()
    cursor = conn.cursor()
    mp_ph = ",".join(["?"] * len(model_pks))
    cp_ph = ",".join(["?"] * len(category_pks))
    params = tuple(model_pks) + tuple(category_pks)
    cursor.execute(
        f"""
        SELECT DISTINCT r.models_fk_pk, r.categories_fk_pk
        FROM model_categories_responses AS resp
        JOIN model_categories_request AS r
          ON resp.model_categories_request_fk_pk = r.pk
        JOIN view_model_categories_responses AS v
          ON v.pk = resp.pk
        JOIN axe_runs AS ar
          ON ar.model_categories_request_fk_pk = r.pk
        WHERE v.http_status = 200
          AND r.models_fk_pk IN ({mp_ph})
          AND r.categories_fk_pk IN ({cp_ph})
        """,
        params,
    )
    return {(int(r[0]), int(r[1])) for r in cursor.fetchall()}


def get_cached_success_pairs(
    model_pks: Sequence[int], category_pks: Sequence[int]
) -> set[tuple[int, int]]:
    """Return (model_pk, category_pk) pairs that have cached successful responses.

    "Successful" means http_status=200 AND an axe_runs row exists.
    HTTP 200 without axe data is NOT considered cached - the pair needs re-running.

    These pairs can be skipped when preparing new requests - we already have
    valid HTML output and accessibility test results for them.

    Args:
        model_pks: Sequence of model database PKs to check.
        category_pks: Sequence of category database PKs to check.

    Returns:
        Set of (model_pk, category_pk) tuples that have complete cached data.
        Returns empty set if either input sequence is empty.
    """
    conn = _dbc.get_connection()
    try:
        return _get_cached_success_pairs(conn, model_pks, category_pks)
    finally:
        conn.close()


def _get_tier2_pairs_with_costs(
    conn: sqlite3.Connection, model_set_pk: int
) -> tuple[set[tuple[int, int]], dict[tuple[int, int], float]]:
    """Return full pairs and costs for cached pairs in a single query.

    Uses LEFT JOIN: full cartesian product left-joined to cached responses with
    costs. Uncached pairs have NULL cost in results.

    The costs dict serves double duty: keys = cached pairs, values = latest cost.
    Use `len(costs) == len(full_pairs)` to check for full cache hit.

    "Cached" requires BOTH http_status=200 AND axe_runs row. HTTP 200 without
    axe data is NOT cached - those pairs won't appear in costs dict.

    Returns (full_pairs, costs_by_pair) where:
    - full_pairs: cartesian product of models in the set × enabled categories
    - costs_by_pair: dict mapping (model_pk, category_pk) → cost for cached pairs
    """
    cursor = conn.cursor()

    # Single query: full pairs LEFT JOIN cached responses with latest cost
    cursor.execute(
        """
        WITH ms AS (
            SELECT value AS id
            FROM model_sets, json_each(model_sets.sorted_model_list)
            WHERE model_sets.pk = ?
        ),
        models_resolved AS (
            SELECT m.pk AS model_pk
            FROM models AS m
            JOIN ms ON ms.id = m.id
        ),
        enabled_categories AS (
            SELECT pk AS category_pk
            FROM categories
            WHERE enabled = 1
        ),
        full_pairs AS (
            SELECT mr.model_pk, ec.category_pk
            FROM models_resolved AS mr
            CROSS JOIN enabled_categories AS ec
        ),
        responses_ranked AS (
            SELECT
                r.models_fk_pk,
                r.categories_fk_pk,
                v.cost,
                ROW_NUMBER() OVER (
                    PARTITION BY r.models_fk_pk, r.categories_fk_pk
                    ORDER BY resp.response_timestamp DESC
                ) AS rn
            FROM model_categories_responses AS resp
            JOIN model_categories_request AS r
              ON resp.model_categories_request_fk_pk = r.pk
            JOIN view_model_categories_responses AS v
              ON v.pk = resp.pk
            JOIN axe_runs AS ar
              ON ar.model_categories_request_fk_pk = r.pk
            JOIN models_resolved AS mr
              ON r.models_fk_pk = mr.model_pk
            JOIN enabled_categories AS ec
              ON r.categories_fk_pk = ec.category_pk
            WHERE v.http_status = 200
        ),
        latest_costs AS (
            SELECT models_fk_pk, categories_fk_pk, cost
            FROM responses_ranked
            WHERE rn = 1
        )
        SELECT fp.model_pk, fp.category_pk, lc.cost
        FROM full_pairs AS fp
        LEFT JOIN latest_costs AS lc
          ON fp.model_pk = lc.models_fk_pk
         AND fp.category_pk = lc.categories_fk_pk
        """,
        (model_set_pk,),
    )

    full_pairs: set[tuple[int, int]] = set()
    costs: dict[tuple[int, int], float] = {}

    for m_pk, c_pk, cost in cursor.fetchall():
        key = (int(m_pk), int(c_pk))
        full_pairs.add(key)
        if cost is not None:
            # NOTE: cost is never NULL for cached pairs. OpenRouter always returns a cost
            # value for successful responses (either 0 for free models or a real amount).
            # NULL cost only occurs on error responses (HTTP 500/-1), which are excluded
            # by the responses_ranked CTE (requires http_status=200 + axe_runs JOIN).
            # Do NOT add a NULL→0.0 fallback here - it's unnecessary defensive code.
            # Verified 2025-12-09: zero HTTP 200 responses have NULL cost in production DB.
            costs[key] = float(cost)

    return full_pairs, costs


def get_tier2_pairs_with_costs(
    model_set_pk: int,
) -> tuple[set[tuple[int, int]], dict[tuple[int, int], float]]:
    """Return full pairs and costs for cached pairs in a single query.

    The costs dict serves double duty: keys = cached pairs, values = latest cost.
    Use `len(costs) == len(full_pairs)` to check for full cache hit.

    "Cached" requires BOTH http_status=200 AND axe_runs row. HTTP 200 without
    axe data is NOT cached - those pairs won't appear in costs dict.

    Args:
        model_set_pk: Database PK of the model_set to check coverage for.

    Returns:
        Tuple of (full_pairs, costs_by_pair) where:
        - full_pairs: set of (model_pk, category_pk) for all pairs
        - costs_by_pair: dict mapping (model_pk, category_pk) → cost for cached pairs

    Example:
        full_pairs, costs = get_tier2_pairs_with_costs(model_set_pk)
        if len(costs) == len(full_pairs):
            # Full cache hit - all pairs have cached results
            leaderboard = create_leaderboard_from_cached(model_set_pk, costs)
        else:
            # Partial cache - need to run missing pairs
            missing = full_pairs - set(costs.keys())
    """
    conn = _dbc.get_connection()
    try:
        return _get_tier2_pairs_with_costs(conn, model_set_pk)
    finally:
        conn.close()
