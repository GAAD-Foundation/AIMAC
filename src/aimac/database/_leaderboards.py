"""Internal. Import from aimac.database.

Leaderboards: Tier 1 Cache and Aggregate Statistics
====================================================

Leaderboards are point-in-time snapshots that summarize benchmark results for a
model_set. They serve two purposes:

1. **Tier 1 Cache** - If a complete leaderboard exists for the current model_set,
   the collector can skip all API calls and reuse cached results. This is the
   "fast path" that avoids re-running expensive benchmarks.

2. **Aggregate Statistics** - Each leaderboard contains per-model summary rows
   (model_categories_summary) with pre-computed metrics: median score, cost,
   violation counts, and reliability stats (stddev, p90).

Key concepts:

- **model_set**: An immutable, canonically-sorted list of model IDs. A leaderboard
  is always scoped to exactly one model_set.

- **Completeness**: A leaderboard is "complete" when all 28 enabled categories have
  SUCCESS results for every model in the set. Incomplete leaderboards exist during
  partial collection runs.

- **Active leaderboard**: A singleton pointer (leaderboard_active table) to the
  currently displayed leaderboard. Only complete leaderboards should be activated.

- **Rankings**: Competition-style ranking (ties share rank, next rank skips).
  Tiebreaker order: median_weighted_score → avg_axe_score → total_violations →
  total_cost_usd → model_pk.

See also:
- data/schema/006_leaderboards.sql - leaderboard header table
- data/schema/008_leaderboard_active.sql - singleton activation pointer
- data/schema/015_model_categories_summary.sql - per-model aggregate rows
- src/aimac/collector.py - orchestrates cache checks and leaderboard creation
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import statistics

import aimac.database._core as _dbc

logger = logging.getLogger(__name__)


def _get_latest_leaderboard_for_model_set(
    conn: sqlite3.Connection, model_set_pk: int
) -> int | None:
    """Return the most recent leaderboard PK for a model_set, or None.

    "Latest" is determined by created_at timestamp descending. This is used by
    the Tier 1 cache check to find the candidate leaderboard before verifying
    completeness.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT pk
        FROM leaderboards
        WHERE model_sets_fk_pk = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (model_set_pk,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return int(row[0])


def get_latest_leaderboard_for_model_set(model_set_pk: int) -> int | None:
    """Get the most recent leaderboard PK for a model_set.

    "Latest" is determined by created_at timestamp descending. This is used by
    the Tier 1 cache check to find the candidate leaderboard before verifying
    completeness.

    Args:
        model_set_pk: Primary key of the model_set to query.

    Returns:
        The leaderboard primary key, or None if no leaderboard exists for this
        model_set.
    """
    conn = _dbc.get_connection()
    try:
        return _get_latest_leaderboard_for_model_set(conn, model_set_pk)
    finally:
        conn.close()


def _set_active_leaderboard(conn: sqlite3.Connection, leaderboard_pk: int) -> None:
    """Upsert the singleton pointer in ``leaderboard_active``.

    The leaderboard_active table has a CHECK(pk=1) constraint ensuring only one
    row can exist. This uses INSERT ... ON CONFLICT to atomically update the
    pointer. FK constraints ensure the leaderboard_pk must exist.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO leaderboard_active (pk, leaderboards_fk_pk)
        VALUES (1, ?)
        ON CONFLICT(pk) DO UPDATE SET
            leaderboards_fk_pk = excluded.leaderboards_fk_pk
        """,
        (leaderboard_pk,),
    )


def set_active_leaderboard(leaderboard_pk: int) -> None:
    """Activate a leaderboard for display.

    Upserts the singleton pointer in the leaderboard_active table to point to
    the specified leaderboard. Only one leaderboard can be active at a time.

    Args:
        leaderboard_pk: Primary key of the leaderboard to activate.

    Raises:
        sqlite3.IntegrityError: If leaderboard_pk doesn't exist (FK violation).
    """
    conn = _dbc.get_connection()
    try:
        _set_active_leaderboard(conn, leaderboard_pk)
        conn.commit()
    finally:
        conn.close()


def _get_leaderboard_cost(conn: sqlite3.Connection, leaderboard_pk: int) -> float | None:
    """Return total_cost_usd for a leaderboard, or None if not found.

    Used by collector to display cumulative benchmark cost on cache hits.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT total_cost_usd FROM leaderboards WHERE pk = ?",
        (leaderboard_pk,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return float(row[0]) if row[0] is not None else None


def get_leaderboard_cost(leaderboard_pk: int) -> float | None:
    """Fetch the total cost in USD for a leaderboard.

    Used by the collector to display cumulative benchmark cost on cache hits.

    Args:
        leaderboard_pk: Primary key of the leaderboard.

    Returns:
        Total cost in USD, or None if the leaderboard doesn't exist or has no
        cost recorded.
    """
    conn = _dbc.get_connection()
    try:
        return _get_leaderboard_cost(conn, leaderboard_pk)
    finally:
        conn.close()


def _is_leaderboard_complete(conn: sqlite3.Connection, leaderboard_pk: int) -> bool:
    """Return True if all models in the leaderboard's model_set are complete.

    Completeness requires:
    1. A summary row exists for every model in the model_set
    2. Each summary row has is_complete=1 (all 28 categories succeeded)
    3. Every model×category pair has an axe_runs row (DB is authoritative)

    This is the gate for Tier 1 cache hits - only complete leaderboards can be
    activated and used to skip benchmark runs.
    """
    cursor = conn.cursor()
    # Resolve model_set and models in it
    cursor.execute("SELECT model_sets_fk_pk FROM leaderboards WHERE pk = ?", (leaderboard_pk,))
    row = cursor.fetchone()
    if not row:
        return False
    model_set_pk = int(row[0])

    cursor.execute(
        """
        WITH ms AS (
            SELECT value AS id
            FROM model_sets, json_each(model_sets.sorted_model_list)
            WHERE model_sets.pk = ?
        )
        SELECT m.pk AS model_pk
        FROM models AS m
        JOIN ms ON ms.id = m.id
        """,
        (model_set_pk,),
    )
    model_pks = {int(r[0]) for r in cursor.fetchall()}
    if not model_pks:
        return False

    # Count complete summaries and ensure one per model
    cursor.execute(
        """
        SELECT models_fk_pk, is_complete
        FROM model_categories_summary
        WHERE leaderboards_fk_pk = ?
        """,
        (leaderboard_pk,),
    )
    have: dict[int, bool] = {}
    for m_pk, is_comp in cursor.fetchall():
        have[int(m_pk)] = bool(is_comp)

    # Every model in set must have a row and be complete
    if set(have.keys()) != model_pks:
        return False
    if not all(have.values()):
        return False

    # Verify axe_runs exist for all model×category pairs (DB is authoritative)
    # Get enabled category count
    cursor.execute("SELECT COUNT(*) FROM categories WHERE enabled = 1")
    expected_categories = cursor.fetchone()[0]

    # Count axe-backed pairs per model using view_latest_model_category_results
    # This view only returns pairs that have axe_runs
    model_pks_list = list(model_pks)
    placeholders = ",".join(["?"] * len(model_pks_list))
    cursor.execute(
        f"""
        SELECT v.model_pk, COUNT(DISTINCT v.category_pk) as cat_count
        FROM view_latest_model_category_results v
        WHERE v.model_pk IN ({placeholders})
        GROUP BY v.model_pk
        """,
        tuple(model_pks_list),
    )
    axe_counts = {int(r[0]): int(r[1]) for r in cursor.fetchall()}

    # Every model must have axe data for all categories
    for model_pk in model_pks:
        if axe_counts.get(model_pk, 0) < expected_categories:
            return False

    return True


def is_leaderboard_complete(leaderboard_pk: int) -> bool:
    """Check if a leaderboard has complete data for all models.

    A leaderboard is complete when:
    1. A summary row exists for every model in the model_set
    2. Each summary row has is_complete=1 (all 28 categories succeeded)
    3. Every model×category pair has an axe_runs row (DB is authoritative)

    This is the gate for Tier 1 cache hits - only complete leaderboards can be
    activated and used to skip benchmark runs.

    Args:
        leaderboard_pk: Primary key of the leaderboard to check.

    Returns:
        True if the leaderboard is complete, False otherwise.
    """
    conn = _dbc.get_connection()
    try:
        return _is_leaderboard_complete(conn, leaderboard_pk)
    finally:
        conn.close()


def _get_summary_missing_pairs_for_model_set(
    conn: sqlite3.Connection, model_set_pk: int
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Compute which (model_pk, category_pk) pairs are missing from the latest leaderboard.

    Returns (full_pairs, missing_pairs) where:
    - full_pairs: all possible (model, category) combinations for this model_set
    - missing_pairs: subset of full_pairs not yet recorded in the summary

    This drives partial collection: the collector runs benchmarks only for
    missing_pairs rather than re-running everything. The summary's categories_array
    field (per model) tracks which categories have SUCCESS data.

    If no leaderboard exists for this model_set, returns (set(), set()) so the
    caller knows to start fresh.
    """
    lb_pk = _get_latest_leaderboard_for_model_set(conn, model_set_pk)
    if lb_pk is None:
        return set(), set()

    cursor = conn.cursor()
    # Resolve model PKs in set
    cursor.execute(
        """
        WITH ms AS (
            SELECT value AS id
            FROM model_sets, json_each(model_sets.sorted_model_list)
            WHERE model_sets.pk = ?
        )
        SELECT m.pk AS model_pk
        FROM models AS m
        JOIN ms ON ms.id = m.id
        ORDER BY m.pk
        """,
        (model_set_pk,),
    )
    model_pks = [int(r[0]) for r in cursor.fetchall()]

    # Resolve enabled category PKs (immutable 28)
    cursor.execute("SELECT pk FROM categories WHERE enabled = 1 ORDER BY pk")
    category_pks = [int(r[0]) for r in cursor.fetchall()]

    if not model_pks or not category_pks:
        return set(), set()

    full_pairs = {(m, c) for m in model_pks for c in category_pks}

    # Load categories_array per model from summary; models without rows => empty set
    cursor.execute(
        """
        SELECT models_fk_pk, categories_array
        FROM model_categories_summary
        WHERE leaderboards_fk_pk = ?
        """,
        (lb_pk,),
    )
    cats_by_model: dict[int, set[int]] = {m: set() for m in model_pks}
    for m_pk, cats_json in cursor.fetchall():
        # Our database data - if corrupt, surface the bug
        arr = json.loads(cats_json or "[]")
        cats_by_model[int(m_pk)] = {int(x) for x in arr}

    missing: set[tuple[int, int]] = set()
    all_cats = set(category_pks)
    for m in model_pks:
        have = cats_by_model.get(m, set())
        need = all_cats - have
        if need:
            missing.update({(m, c) for c in need})
    return full_pairs, missing


def get_summary_missing_pairs_for_model_set(
    model_set_pk: int,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Find (model, category) pairs needing benchmark runs.

    This drives partial collection: the collector runs benchmarks only for
    missing pairs rather than re-running everything. The summary's categories_array
    field (per model) tracks which categories have SUCCESS data.

    If no leaderboard exists for this model_set, returns (set(), set()) so the
    caller knows to start fresh.

    Args:
        model_set_pk: Primary key of the model_set to query.

    Returns:
        A tuple of (full_pairs, missing_pairs) where:
        - full_pairs: all possible (model_pk, category_pk) combinations
        - missing_pairs: subset of full_pairs not yet recorded in the summary
    """
    conn = _dbc.get_connection()
    try:
        return _get_summary_missing_pairs_for_model_set(conn, model_set_pk)
    finally:
        conn.close()


def _count_categories_with_axe_results(
    cursor: sqlite3.Cursor, model_pks: list[int]
) -> dict[int, int]:
    """Count how many categories have axe accessibility results for each model.

    Returns dict mapping model_pk → count of distinct categories with axe data.
    This eliminates the N+1 query pattern of fetching per-model inside a loop.
    """
    if not model_pks:
        return {}

    placeholders = ",".join(["?"] * len(model_pks))
    cursor.execute(
        f"""
        SELECT v.model_pk, COUNT(DISTINCT v.category_pk)
        FROM view_latest_model_category_results v
        WHERE v.model_pk IN ({placeholders})
        GROUP BY v.model_pk
        """,
        tuple(model_pks),
    )
    return {int(r[0]): int(r[1]) for r in cursor.fetchall()}


def _compute_axe_statistics(
    cursor: sqlite3.Cursor, req_pks: list[int]
) -> tuple[float | None, float, float | None, float | None, int | None]:
    """Compute axe statistics from a set of request PKs.

    Returns (avg_axe_score, median_weighted_score, stddev, p90, total_violations).
    median_weighted_score defaults to 1e9 sentinel when no data (schema requires NOT NULL).
    """
    if not req_pks:
        return None, 1e9, None, None, None

    placeholders = ",".join(["?"] * len(req_pks))
    cursor.execute(
        f"""
        SELECT weighted_score, total_violations
        FROM axe_runs
        WHERE model_categories_request_fk_pk IN ({placeholders})
        """,
        tuple(req_pks),
    )
    rows = cursor.fetchall()

    scores = [float(r[0]) for r in rows if r[0] is not None]
    if not scores:
        return None, 1e9, None, None, None

    # Compute statistics using stdlib where possible
    avg_axe_score = statistics.mean(scores)
    median_weighted_score = statistics.median(scores)

    # Standard deviation requires n > 1
    stddev_weighted_score = None
    if len(scores) > 1:
        try:
            stddev_weighted_score = statistics.stdev(scores)
        except statistics.StatisticsError:
            stddev_weighted_score = None

    # P90 (nearest-rank method)
    s = sorted(scores)
    n = len(s)
    idx = max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))
    p90_weighted_score = float(s[idx])

    # Sum violations
    tv_vals = [int(r[1]) for r in rows if r[1] is not None]
    total_violations = sum(tv_vals) if tv_vals else None

    return avg_axe_score, median_weighted_score, stddev_weighted_score, p90_weighted_score, total_violations


def _create_leaderboard_from_cached(
    conn: sqlite3.Connection,
    model_set_pk: int,
    costs: dict[tuple[int, int], float],
) -> int:
    """Create a leaderboard from cached (model, category) cost data.

    This is called by the collector after determining which pairs can be reused
    from Tier 2 cache. The costs dict contains only pairs with valid cached
    results - missing pairs mean incomplete data (is_complete=0).

    Steps:
    1. Insert leaderboard header with summed total_cost_usd
    2. For each model in the model_set, create a summary row with:
       - Aggregated costs for that model's pairs
       - Accessibility metrics (median, stddev, p90, violations) computed from
         the latest successful axe_run per (model, category)
       - categories_array listing which categories have data
       - is_complete=1 only if all 28 categories are present
    3. Compute competition-style rankings across all models

    Returns the new leaderboard PK.
    """
    total_cost = float(sum(costs.values()))
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd)
        VALUES (?, ?)
        """,
        (model_set_pk, total_cost),
    )
    lr = cursor.lastrowid
    assert lr is not None
    leaderboard_pk = int(lr)

    # Resolve models in this model_set (include models even with zero cached pairs)
    cursor.execute(
        """
        WITH ms AS (
            SELECT value AS id
            FROM model_sets, json_each(model_sets.sorted_model_list)
            WHERE model_sets.pk = ?
        )
        SELECT m.pk AS model_pk
        FROM models AS m
        JOIN ms ON ms.id = m.id
        ORDER BY m.pk
        """,
        (model_set_pk,),
    )
    model_pks = [int(r[0]) for r in cursor.fetchall()]

    # Enabled categories are immutable and fixed at 28
    cursor.execute(
        "SELECT pk FROM categories WHERE enabled = 1 ORDER BY pk"
    )
    category_pks_all = [int(r[0]) for r in cursor.fetchall()]

    # Derive participating (model, category) pairs from provided cost pairs (latest-success only)
    pairs = list(costs.keys())

    # Bulk fetch latest-success request pk per (model, category)
    latest_req_pk_by_pair: dict[tuple[int, int], int] = {}
    if model_pks and category_pks_all:
        mp_ph = ",".join(["?"] * len(model_pks))
        cp_ph = ",".join(["?"] * len(category_pks_all))
        params = tuple(model_pks) + tuple(category_pks_all)
        cursor.execute(
            f"""
            SELECT r.pk, r.models_fk_pk, r.categories_fk_pk, resp.response_timestamp
            FROM model_categories_responses AS resp
            JOIN model_categories_request AS r
              ON resp.model_categories_request_fk_pk = r.pk
            JOIN view_model_categories_responses AS v
              ON v.pk = resp.pk
            WHERE v.http_status = 200
              AND r.models_fk_pk IN ({mp_ph})
              AND r.categories_fk_pk IN ({cp_ph})
            ORDER BY r.models_fk_pk, r.categories_fk_pk, resp.response_timestamp DESC
            """,
            params,
        )
        for req_pk, m, c, _ts in cursor.fetchall():
            key = (int(m), int(c))
            if key in latest_req_pk_by_pair:
                continue
            latest_req_pk_by_pair[key] = int(req_pk)

    # Count categories with axe results per model (fixes N+1 query pattern)
    axe_counts_by_model = _count_categories_with_axe_results(cursor, model_pks)

    # Populate per-model summary rows
    for model_pk in model_pks:
        # All categories for this model included in this leaderboard
        categories_for_model = [c for (m, c) in pairs if m == model_pk]

        # Sum costs for this model (model_pairs are from costs.keys(), no redundant check needed)
        model_costs = [costs[(model_pk, c)] for c in categories_for_model]
        total_cost_for_model = float(sum(model_costs)) if model_costs else 0.0

        categories_count = len(categories_for_model)
        categories_array_json = json.dumps(sorted({int(c) for c in categories_for_model}))

        # Get axe category count from bulk-fetched data (default 0 if not present)
        axe_category_count = axe_counts_by_model.get(model_pk, 0)

        # is_complete requires both: 28 categories AND axe data for all of them
        is_complete = 1 if (categories_count == 28 and axe_category_count >= 28) else 0

        # Collect latest-success request PKs for this model's pairs
        req_pks = [
            pk for c in categories_for_model
            if (pk := latest_req_pk_by_pair.get((model_pk, c))) is not None
        ]

        # Compute axe statistics
        avg_axe_score, median_weighted_score, stddev_weighted_score, p90_weighted_score, total_violations = (
            _compute_axe_statistics(cursor, req_pks)
        )

        # Insert summary row
        cursor.execute(
            """
            INSERT INTO model_categories_summary (
                leaderboards_fk_pk,
                models_fk_pk,
                ranking,
                median_weighted_score,
                stddev_weighted_score,
                p90_weighted_score,
                total_cost_usd,
                avg_cost_per_page,
                is_complete,
                categories_array,
                avg_axe_score,
                total_violations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                leaderboard_pk,
                model_pk,
                0,   # ranking computed after inserts
                median_weighted_score,
                stddev_weighted_score,
                p90_weighted_score,
                total_cost_for_model,
                (total_cost_for_model / max(1, categories_count)) if categories_count else 0.0,
                is_complete,
                categories_array_json,
                avg_axe_score,
                total_violations,
            ),
        )

    _compute_and_update_rankings(conn, leaderboard_pk)

    return leaderboard_pk


def _compute_and_update_rankings(conn: sqlite3.Connection, leaderboard_pk: int) -> None:
    """Compute competition-style rankings for all models in a leaderboard.

    Uses "Standard Competition Ranking" (1224 pattern): ties share the same rank,
    and the next rank skips accordingly. For example, if two models tie for 1st,
    the next model is ranked 3rd.

    Tiebreaker order (all ascending - lower is better):
    1. median_weighted_score (AIMAC Score)
    2. avg_axe_score (average violations per page)
    3. total_violations (sum across all categories)
    4. total_cost_usd (benchmark cost)
    5. model_pk (stable ordering for identical models)
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT pk, median_weighted_score, avg_axe_score, total_violations, total_cost_usd, models_fk_pk
        FROM model_categories_summary
        WHERE leaderboards_fk_pk = ?
        """,
        (leaderboard_pk,),
    )
    rows = cursor.fetchall()

    def _sort_key(r: tuple) -> tuple:
        # r = (pk, median, avg, viol, cost, model_pk)
        median = float(r[1]) if r[1] is not None else float('inf')
        avg = float(r[2]) if r[2] is not None else float('inf')
        viol = int(r[3]) if r[3] is not None else 10**9
        cost = float(r[4]) if r[4] is not None else float('inf')
        model_pk_val = int(r[5])  # stable display order only
        return (median, avg, viol, cost, model_pk_val)

    sorted_rows = sorted(rows, key=_sort_key)

    # Assign competition ranks: ties share rank, next rank skips
    prev = None
    current_rank = 0
    for idx, r in enumerate(sorted_rows, start=1):
        median = float(r[1]) if r[1] is not None else float('inf')
        avg = float(r[2]) if r[2] is not None else float('inf')
        viol = int(r[3]) if r[3] is not None else 10**9
        cost = float(r[4]) if r[4] is not None else float('inf')
        tup = (median, avg, viol, cost)
        if prev is None or tup != prev:
            current_rank = idx
            prev = tup
        pk_val = int(r[0])
        cursor.execute(
            "UPDATE model_categories_summary SET ranking = ? WHERE pk = ?",
            (current_rank, pk_val),
        )


def create_leaderboard_from_cached(
    model_set_pk: int, costs: dict[tuple[int, int], float]
) -> int:
    """Create a leaderboard from Tier 2 cached cost data.

    Called by the collector after determining which (model, category) pairs can
    be reused from Tier 2 cache. The costs dict contains only pairs with valid
    cached results - missing pairs mean incomplete data (is_complete=0).

    The function:
    1. Inserts a leaderboard header with summed total_cost_usd
    2. Creates summary rows for each model with aggregated costs and accessibility
       metrics computed from latest successful axe_runs
    3. Computes competition-style rankings across all models

    Args:
        model_set_pk: Primary key of the model_set for this leaderboard.
        costs: Dict mapping (model_pk, category_pk) to cost in USD for pairs
            with cached results.

    Returns:
        The newly created leaderboard primary key.
    """
    conn = _dbc.get_connection()
    try:
        pk = _create_leaderboard_from_cached(conn, model_set_pk, costs)
        conn.commit()
        return pk
    finally:
        conn.close()


def _get_active_leaderboard_pk(conn: sqlite3.Connection) -> int | None:
    """Return the PK of the currently active leaderboard, or None if not set.

    The active leaderboard is the one displayed on the website. It's stored as
    a singleton row in leaderboard_active with pk=1.
    """
    cursor = conn.cursor()
    row = cursor.execute("SELECT leaderboards_fk_pk FROM leaderboard_active WHERE pk = 1").fetchone()
    return int(row[0]) if row else None


def get_active_leaderboard_pk() -> int | None:
    """Get the currently active leaderboard PK.

    The active leaderboard is the one displayed on the website. It's stored as
    a singleton row in leaderboard_active with pk=1.

    Returns:
        The primary key of the active leaderboard, or None if no leaderboard
        has been activated.
    """
    conn = _dbc.get_connection()
    try:
        return _get_active_leaderboard_pk(conn)
    finally:
        conn.close()


def _get_leaderboard_model_ids(conn: sqlite3.Connection, leaderboard_pk: int) -> set[str]:
    """Return the set of model IDs included in a leaderboard.

    Used by collector to detect model_set changes: if the active leaderboard's
    models differ from the current run's models, it's a cache invalidation signal.
    """
    cursor = conn.cursor()
    # Get model_set_pk
    row = cursor.execute("SELECT model_sets_fk_pk FROM leaderboards WHERE pk = ?", (leaderboard_pk,)).fetchone()
    if not row:
        return set()
    model_set_pk = row[0]

    # Get sorted_model_list (JSON)
    row = cursor.execute("SELECT sorted_model_list FROM model_sets WHERE pk = ?", (model_set_pk,)).fetchone()
    if not row:
        return set()
    return set(json.loads(row[0]))


def get_leaderboard_model_ids(leaderboard_pk: int) -> set[str]:
    """Get the set of model IDs included in a leaderboard.

    Used by the collector to detect model_set changes: if the active leaderboard's
    models differ from the current run's models, it's a cache invalidation signal.

    Args:
        leaderboard_pk: Primary key of the leaderboard.

    Returns:
        Set of model ID strings (e.g., {"gpt-4", "claude-3-opus"}) included in
        this leaderboard's model_set.
    """
    conn = _dbc.get_connection()
    try:
        return _get_leaderboard_model_ids(conn, leaderboard_pk)
    finally:
        conn.close()
