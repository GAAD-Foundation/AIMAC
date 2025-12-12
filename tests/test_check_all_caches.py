"""Comprehensive tests for resolve_caches() covering all code paths.

The resolve_caches() function has these paths:
1. Leaderboard cache hit -> activates leaderboard, returns fully_cached=True
2. No models/categories -> returns (fully_cached=False, missing_pairs=empty)
3. Full response cache hit -> creates/activates leaderboard, returns fully_cached=True
4. Partial response cache -> returns missing_pairs for preparation
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from aimac import database as db
from aimac.collector import resolve_caches


def _exec_schema(conn: sqlite3.Connection, *names: str) -> None:
    """Execute schema files in order."""
    base = Path("data/schema")
    for name in names:
        sql = (base / name).read_text()
        conn.executescript(sql)


def _minimal_schema(db_path: Path) -> None:
    """Setup minimal schema for cache testing."""
    conn = sqlite3.connect(db_path)
    try:
        _exec_schema(
            conn,
            "001_models.sql",
            "002_view_models.sql",  # Required by view_latest_model_category_results
            "004_model_sets.sql",
            "005_categories.sql",
            "003_batches.sql",
            "006_leaderboards.sql",
            "008_leaderboard_active.sql",
            "015_model_categories_summary.sql",
            "010_system_prompts.sql",
            "011_system_prompt_active.sql",
            "012_view_system_prompt_active.sql",
            "013_model_categories_request.sql",
            "014_model_categories_responses.sql",
            "016_axe_runs.sql",  # Required for leaderboard summary population
            "017_view_model_categories_request.sql",
            "018_view_model_categories_responses.sql",
            "019_view_artifact_paths.sql",  # Required by view_latest_model_category_results
            "023_view_latest_model_category_results.sql",  # Required by is_leaderboard_complete
        )
        conn.commit()
    finally:
        conn.close()


def _insert_axe_run(conn: sqlite3.Connection, request_pk: int) -> int:
    """Insert an axe_runs row for a request.

    Tier-2 cache requires axe_runs to exist (not just HTTP 200).
    """
    conn.execute(
        """
        INSERT INTO axe_runs (
            model_categories_request_fk_pk,
            total_violations, critical_violations, serious_violations,
            weighted_score, axe_json_path, run_timestamp
        ) VALUES (?, 0, 0, 0, 0.0, '/fake/path.json', CURRENT_TIMESTAMP)
        """,
        (request_pk,),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_complete_axe_data(conn: sqlite3.Connection, model_pk: int) -> list[int]:
    """Insert request/response/axe_runs for all 28 enabled categories for a model.

    This is needed because is_leaderboard_complete now verifies axe_runs exist
    for all model×category pairs (DB is authoritative, not just is_complete flag).

    Returns list of category PKs that have axe data.
    """
    cursor = conn.cursor()

    # Get all enabled category PKs
    cursor.execute("SELECT pk FROM categories WHERE enabled = 1 ORDER BY pk")
    category_pks = [row[0] for row in cursor.fetchall()]

    # Get system prompt
    cursor.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1")
    system_prompt_pk = cursor.fetchone()[0]

    # Create a batch
    cursor.execute("""
        INSERT INTO batches (batch_date, batch_time, started_at)
        VALUES (20250101, 120000, CURRENT_TIMESTAMP)
    """)
    batch_pk = cursor.lastrowid

    # Insert request + response + axe_runs for each category
    for cat_pk in category_pks:
        request_body = json.dumps({"model": "test/model-1"})
        cursor.execute("""
            INSERT INTO model_categories_request
            (batches_fk_pk, models_fk_pk, categories_fk_pk, system_prompts_fk_pk, openrouter_request_body)
            VALUES (?, ?, ?, ?, ?)
        """, (batch_pk, model_pk, cat_pk, system_prompt_pk, request_body))
        request_pk = cursor.lastrowid

        # Insert successful response
        response_json = json.dumps({
            "choices": [{"message": {"content": "<!DOCTYPE html><html><body>Test</body></html>"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300, "cost": 0.001}
        })
        cursor.execute("""
            INSERT INTO model_categories_responses
            (model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp)
            VALUES (?, 1, ?, CURRENT_TIMESTAMP)
        """, (request_pk, response_json))

        # Insert axe_runs
        cursor.execute("""
            INSERT INTO axe_runs (
                model_categories_request_fk_pk,
                total_violations, critical_violations, serious_violations,
                weighted_score, axe_json_path, run_timestamp
            ) VALUES (?, 0, 0, 0, 0.0, '/fake/path.json', CURRENT_TIMESTAMP)
        """, (request_pk,))

    conn.commit()
    return category_pks


def test_leaderboard_cache_hit_path(tmp_path, capsys):
    """Path 1: Leaderboard exists -> activates it, returns fully_cached=True."""
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    model_ids = ["test/model-1"]

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        # Insert model, create model_set, and seed complete summary for Tier-1 hit
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT INTO models (
                    id, name, description, context_length,
                    supported_parameters, pricing, created
                ) VALUES ('test/model-1','M1','',1,'[]','{}',0)"""
            )
            mpk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        model_set_pk = db.upsert_model_set(model_ids)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd) VALUES (?, ?)",
                (model_set_pk, 5.50),
            )
            lbpk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert axe data for all 28 categories (required by is_leaderboard_complete)
            category_pks = _insert_complete_axe_data(conn, mpk)

            conn.execute(
                """
                INSERT INTO model_categories_summary (
                    leaderboards_fk_pk, models_fk_pk, ranking, median_weighted_score,
                    total_cost_usd, avg_cost_per_page, is_complete, categories_array,
                    avg_axe_score, total_violations
                ) VALUES (?, ?, 1, 0.0, 5.50, 0.0, 1, ?, NULL, NULL)
                """,
                (lbpk, mpk, json.dumps(category_pks)),
            )
            conn.commit()
        finally:
            conn.close()

        # Run check
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify leaderboard cache hit
    assert result.fully_cached is True
    assert result.missing_pairs == set()

    out = capsys.readouterr().out
    assert "[CACHE HIT] LEADERBOARD" in out
    assert "5.50" in out

    # Verify active leaderboard was set
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM leaderboard_active").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_no_models_or_categories_path(tmp_path, capsys):
    """Path 2: No enabled models/categories -> returns (False, empty set)."""
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    # Disable all seeded categories
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM categories")
        conn.commit()
    finally:
        conn.close()

    model_ids = []  # No models

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        model_set_pk = 1  # Doesn't matter since no models
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify nothing to do
    assert result.fully_cached is False
    assert result.missing_pairs == set()

    out = capsys.readouterr().out
    assert "No models or categories" in out


def test_full_response_cache_hit_path(tmp_path, capsys):
    """Path 3: All responses cached -> creates leaderboard, returns fully_cached=True."""
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    model_id = "test/model-1"
    model_ids = [model_id]

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        # Setup: Insert model and seed all 28 categories with responses
        conn = sqlite3.connect(db_path)
        try:
            # Insert model
            conn.execute(
                """INSERT INTO models (
                    id, name, description, context_length,
                    supported_parameters, pricing, created, canonical_slug, hugging_face_id
                ) VALUES (?, 'Test', '', 1, '[]', '{}', 0, NULL, NULL)""",
                (model_id,)
            )
            model_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert batch and system prompt
            conn.execute(
                "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
            )
            batch_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            sp_fk = conn.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1").fetchone()[0]

            # Seed successful responses + axe_runs for ALL 28 enabled categories
            # Tier-2 cache requires BOTH http_status=200 AND axe_runs row
            import json
            category_pks = conn.execute("SELECT pk FROM categories WHERE enabled = 1").fetchall()
            for (cat_pk,) in category_pks:
                conn.execute(
                    """INSERT INTO model_categories_request (
                        batches_fk_pk, models_fk_pk, categories_fk_pk,
                        system_prompts_fk_pk, openrouter_request_body
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (batch_pk, model_pk, cat_pk, sp_fk, '{"model":"test/model-1"}')
                )
                req_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                resp = json.dumps({
                    "choices": [{"message": {"content": "<html>ok</html>"}}],
                    "usage": {"cost": 3.75}
                })
                conn.execute(
                    """INSERT INTO model_categories_responses (
                        model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp
                    ) VALUES (?, 1, ?, CURRENT_TIMESTAMP)""",
                    (req_pk, resp)
                )
                # Insert axe_runs row - required for Tier-2 cache
                _insert_axe_run(conn, req_pk)
            conn.commit()
        finally:
            conn.close()

        # Create model_set (no leaderboard yet)
        model_set_pk = db.upsert_model_set(model_ids)

        # Run check
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify full response cache hit
    assert result.fully_cached is True
    assert result.missing_pairs == set()

    out = capsys.readouterr().out
    assert "[CACHE HIT] FULL" in out

    # Verify leaderboard was created and activated
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM leaderboards").fetchone()
        assert row[0] == 1
        row = conn.execute("SELECT COUNT(*) FROM leaderboard_active").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_partial_response_cache_path(tmp_path, capsys):
    """Path 4: Partial cache -> returns missing_pairs for preparation."""
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    model_id = "test/model-1"
    model_ids = [model_id]

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        conn = sqlite3.connect(db_path)
        try:
            # Disable seeded categories
            conn.execute("DELETE FROM categories")
            conn.commit()

            # Insert model
            conn.execute(
                """INSERT INTO models (
                    id, name, description, context_length,
                    supported_parameters, pricing, created, canonical_slug, hugging_face_id
                ) VALUES (?, 'Test', '', 1, '[]', '{}', 0, NULL, NULL)""",
                (model_id,)
            )
            model_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert TWO enabled categories
            conn.execute(
                """INSERT INTO categories (category_slug, name, description, user_prompt, enabled)
                VALUES ('cat-a', 'Cat A', '', 'prompt A', 1)"""
            )
            cat_a_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """INSERT INTO categories (category_slug, name, description, user_prompt, enabled)
                VALUES ('cat-b', 'Cat B', '', 'prompt B', 1)"""
            )
            _cat_b_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Cache success for only ONE pair (model_pk, cat_a_pk) with axe_runs
            # Tier-2 cache requires BOTH http_status=200 AND axe_runs row
            conn.execute(
                "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
            )
            batch_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            sp_fk = conn.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1").fetchone()[0]

            conn.execute(
                """INSERT INTO model_categories_request (
                    batches_fk_pk, models_fk_pk, categories_fk_pk,
                    system_prompts_fk_pk, openrouter_request_body
                ) VALUES (?, ?, ?, ?, ?)""",
                (batch_pk, model_pk, cat_a_pk, sp_fk, '{"model":"test/model-1"}')
            )
            req_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            import json
            resp = json.dumps({
                "choices": [{"message": {"content": "<html>ok</html>"}}],
                "usage": {"cost": 1.0}
            })
            conn.execute(
                """INSERT INTO model_categories_responses (
                    model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp
                ) VALUES (?, 1, ?, CURRENT_TIMESTAMP)""",
                (req_pk, resp)
            )
            # Insert axe_runs row - required for Tier-2 cache
            _insert_axe_run(conn, req_pk)
            conn.commit()
        finally:
            conn.close()

        # Create model_set (no leaderboard)
        model_set_pk = db.upsert_model_set(model_ids)

        # Run check
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify partial cache
    assert result.fully_cached is False
    assert len(result.missing_pairs) == 1

    # Verify the missing pair is (model_pk, cat_b_pk)
    conn = sqlite3.connect(db_path)
    try:
        model_pk_actual = conn.execute("SELECT pk FROM models WHERE id = ?", (model_id,)).fetchone()[0]
        cat_b_pk_actual = conn.execute("SELECT pk FROM categories WHERE category_slug = 'cat-b'").fetchone()[0]
        assert (model_pk_actual, cat_b_pk_actual) in result.missing_pairs
    finally:
        conn.close()

    out = capsys.readouterr().out
    assert "[CACHE PARTIAL]" in out
    assert "1/2 combos cached" in out


def test_no_false_partial_cache_message_on_empty_pairs(tmp_path, capsys):
    """Regression: Ensure PARTIAL CACHE message doesn't print when missing_pairs is empty.

    Bug scenario: When _tier2_cache_check returns (False, set()), the partial cache
    message was incorrectly printed showing "0/0 combos cached".
    This should NOT happen - partial cache message should only appear when there
    are actual missing pairs to process.
    """
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    # Disable all categories to trigger empty pairs scenario
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM categories")
        conn.commit()
    finally:
        conn.close()

    model_ids = []  # No models either

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        model_set_pk = 1
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify we got the expected result
    assert result.fully_cached is False
    assert result.missing_pairs == set()

    # The bug: "PARTIAL" cache message should NOT appear
    out = capsys.readouterr().out
    assert "[CACHE PARTIAL]" not in out
    assert "No models or categories" in out


def test_no_false_partial_cache_message_on_zero_cached(tmp_path, capsys):
    """Regression: Ensure PARTIAL CACHE message doesn't print when 0 items are cached.

    Bug scenario: Fresh DB with no cached responses would print "0/252 combos cached".
    This is a complete cache MISS, not a partial hit. Message should only appear
    when cached > 0.
    """
    db_path = tmp_path / "test.db"
    _minimal_schema(db_path)

    model_id = "test/model-1"
    model_ids = [model_id]

    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        conn = sqlite3.connect(db_path)
        try:
            # Disable seeded categories
            conn.execute("DELETE FROM categories")
            conn.commit()

            # Insert model
            conn.execute(
                """INSERT INTO models (
                    id, name, description, context_length,
                    supported_parameters, pricing, created, canonical_slug, hugging_face_id
                ) VALUES (?, 'Test', '', 1, '[]', '{}', 0, NULL, NULL)""",
                (model_id,)
            )

            # Insert enabled category
            conn.execute(
                """INSERT INTO categories (category_slug, name, description, user_prompt, enabled)
                VALUES ('test-cat', 'Test', '', 'prompt', 1)"""
            )

            conn.commit()
        finally:
            conn.close()

        # Create model_set (no leaderboard, no cached responses)
        model_set_pk = db.upsert_model_set(model_ids)

        # Run check - should have missing pairs but NO cached responses
        result = resolve_caches(model_set_pk, model_ids, old_models=set())

    # Verify we have missing work but it's not cached
    assert result.fully_cached is False
    assert len(result.missing_pairs) == 1

    # The bug: "PARTIAL" cache message should NOT appear when 0 cached
    out = capsys.readouterr().out
    assert "[CACHE PARTIAL]" not in out
    assert "0/1 combos cached" not in out
