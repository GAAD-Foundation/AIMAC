"""Tier 1 cache tests: pragmatic and focused.

Covers:
- Cache HIT: sets active leaderboard and prints cost info
- Refresh flag: skips cache, does not set active

Uses full_schema_db fixture from conftest.py to load complete DB schema.
"""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import patch

import pytest

from aimac import database as db
from aimac.collector import collect_command

# Import from conftest - pytest handles this automatically
from tests.conftest import load_full_schema


def _insert_complete_axe_data(conn: sqlite3.Connection, model_pk: int) -> None:
    """Insert request/response/axe_runs for all 28 categories for a model.

    This is needed because is_leaderboard_complete now verifies axe_runs exist
    for all model×category pairs (DB is authoritative, not just is_complete flag).
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


def test_tier1_cache_hit_sets_active_and_prints_cost(tmp_path, capsys):
    db_path = tmp_path / "cache.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    load_full_schema(db_path)

    models = [
        {
            "id": "test/model-1",
            "name": "M1",
            "description": "",
            "context_length": 1,
            "supported_parameters": [],
            "pricing": {},
            "created": 0,
        }
    ]

    with patch.dict(os.environ, {
        "AIMAC_DATABASE_PATH": str(db_path),
        "AIMAC_DATA_DIR": str(data_dir),
    }):
        # Upsert model and model_set
        db.upsert_models(models)
        mspk = db.upsert_model_set([m["id"] for m in models])

        # Seed a leaderboard for that model_set
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd) VALUES (?, ?)",
                (mspk, 12.34),
            )
            lbpk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Seed complete summary row for the single model to enable Tier-1 hit
            mpk = conn.execute("SELECT pk FROM models WHERE id = ?", (models[0]["id"],)).fetchone()[0]

            # Insert axe data for all 28 categories (required by is_leaderboard_complete)
            _insert_complete_axe_data(conn, mpk)

            # Get all category PKs for categories_array
            category_pks = [r[0] for r in conn.execute("SELECT pk FROM categories WHERE enabled = 1").fetchall()]

            conn.execute(
                """
                INSERT INTO model_categories_summary (
                    leaderboards_fk_pk, models_fk_pk, ranking, median_weighted_score,
                    total_cost_usd, avg_cost_per_page, is_complete, categories_array,
                    avg_axe_score, total_violations
                ) VALUES (?, ?, 1, 0.0, ?, 0.0, 1, ?, NULL, NULL)
                """,
                (lbpk, mpk, 12.34, json.dumps(category_pks)),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("aimac.collector.fetch_top_models") as mock_fetch:
            mock_fetch.return_value = models

            # Patch connection factory so internal DB helpers use our temp DB
            with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                rc = collect_command()
                assert rc == 0

    out = capsys.readouterr().out
    assert "[CACHE HIT] LEADERBOARD" in out
    assert "previous_cost=$12.34" in out

    # Verify active pointer set
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT leaderboards_fk_pk FROM leaderboard_active WHERE pk = 1").fetchone()
        assert row is not None
        assert isinstance(row[0], int)
    finally:
        conn.close()


def test_refresh_skips_tier1_and_does_not_set_active(tmp_path, capsys):
    db_path = tmp_path / "cache.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    load_full_schema(db_path)

    models = [
        {
            "id": "test/model-1",
            "name": "M1",
            "description": "",
            "context_length": 1,
            "supported_parameters": [],
            "pricing": {},
            "created": 0,
        }
    ]

    with patch.dict(os.environ, {
        "AIMAC_DATABASE_PATH": str(db_path),
        "AIMAC_DATA_DIR": str(data_dir),
    }):
        # Seed a leaderboard even though we will refresh
        mspk = db.upsert_model_set([m["id"] for m in models])
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd) VALUES (?, ?)",
                (mspk, 1.23),
            )
            conn.commit()
        finally:
            conn.close()

            with patch("aimac.collector.fetch_top_models") as mock_fetch, patch(
                "aimac.collector._execute_and_complete_batch",
                return_value={"failed": 0, "screenshot_failed": 0},
            ):
                mock_fetch.return_value = models

                with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                    rc = collect_command(refresh=True)
                assert rc == 0

    out = capsys.readouterr().out
    assert "Refresh requested — skipping all caches" in out
    assert "LEADERBOARD CACHE HIT" not in out

    # active should remain unset because we skipped cache usage
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM leaderboard_active").fetchone()
        assert row[0] == 0
    finally:
        conn.close()


def test_multiple_leaderboards_selects_latest(tmp_path, capsys):
    db_path = tmp_path / "cache.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    load_full_schema(db_path)

    models = [
        {
            "id": "test/model-1",
            "name": "M1",
            "description": "",
            "context_length": 1,
            "supported_parameters": [],
            "pricing": {},
            "created": 0,
        }
    ]

    with patch.dict(os.environ, {
        "AIMAC_DATABASE_PATH": str(db_path),
        "AIMAC_DATA_DIR": str(data_dir),
    }):
        mspk = db.upsert_model_set([m["id"] for m in models])

        conn = sqlite3.connect(db_path)
        try:
            # Insert three leaderboards with explicit created_at
            rows = [
                (mspk, 1.00, "2025-01-01 00:00:00"),
                (mspk, 2.00, "2025-01-02 00:00:00"),
                (mspk, 3.00, "2025-01-03 00:00:00"),
            ]
            for r in rows:
                conn.execute(
                    "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd, created_at) VALUES (?, ?, ?)",
                    r,
                )
            conn.commit()

            # Get pk for latest by created_at
            latest_pk = conn.execute(
                "SELECT pk FROM leaderboards WHERE model_sets_fk_pk = ? ORDER BY created_at DESC LIMIT 1",
                (mspk,),
            ).fetchone()[0]

            # Seed summary rows: only latest leaderboard is complete
            db.upsert_models(models)
            mpk = conn.execute("SELECT pk FROM models WHERE id = ?", (models[0]["id"],)).fetchone()[0]

            # Insert axe data for all 28 categories (required by is_leaderboard_complete)
            _insert_complete_axe_data(conn, mpk)

            # Get all category PKs for categories_array
            category_pks = [r[0] for r in conn.execute("SELECT pk FROM categories WHERE enabled = 1").fetchall()]

            # Mark only latest as complete; earlier boards incomplete
            conn.execute(
                """
                INSERT INTO model_categories_summary (
                    leaderboards_fk_pk, models_fk_pk, ranking, median_weighted_score,
                    total_cost_usd, avg_cost_per_page, is_complete, categories_array,
                    avg_axe_score, total_violations
                )
                SELECT pk, ?, 1, 0.0, total_cost_usd, 0.0,
                       CASE WHEN pk = ? THEN 1 ELSE 0 END,
                       ?, NULL, NULL
                FROM leaderboards WHERE model_sets_fk_pk = ?
                """,
                (mpk, latest_pk, json.dumps(category_pks), mspk),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("aimac.collector.fetch_top_models") as mock_fetch:
            mock_fetch.return_value = models

            # Use our DB connection factory
            def _conn_factory():
                c = sqlite3.connect(db_path)
                c.execute("PRAGMA foreign_keys = ON")
                return c

            with patch("aimac.database._core.get_connection", side_effect=_conn_factory):
                rc = collect_command()
                assert rc == 0

    out = capsys.readouterr().out
    assert "[CACHE HIT] LEADERBOARD" in out

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT leaderboards_fk_pk FROM leaderboard_active WHERE pk = 1").fetchone()
        assert row is not None
        assert row[0] == latest_pk
    finally:
        conn.close()


def test_cache_miss_outputs_and_no_active(tmp_path, capsys):
    db_path = tmp_path / "cache.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    load_full_schema(db_path)

    models = [
        {
            "id": "test/model-1",
            "name": "M1",
            "description": "",
            "context_length": 1,
            "supported_parameters": [],
            "pricing": {},
            "created": 0,
        }
    ]

    with patch.dict(os.environ, {
        "AIMAC_DATABASE_PATH": str(db_path),
        "AIMAC_DATA_DIR": str(data_dir),
    }):
        with patch(
            "aimac.collector.fetch_top_models"
        ) as mock_fetch, patch(
            "aimac.collector._execute_and_complete_batch",
            return_value={"failed": 0, "screenshot_failed": 0},
        ):
            mock_fetch.return_value = models

            with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                rc = collect_command()
                assert rc == 0

    out = capsys.readouterr().out
    assert "LEADERBOARD CACHE MISS" in out

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM leaderboard_active").fetchone()
        assert row[0] == 0
    finally:
        conn.close()


def test_set_active_leaderboard_fk_violation(tmp_path):
    """set_active_leaderboard should enforce FK constraints and raise on invalid PK."""
    db_path = tmp_path / "cache.db"
    load_full_schema(db_path)

    # We only need leaderboards + leaderboard_active schema for this test
    # No rows are inserted into leaderboards, so any FK will fail.

    # Factory that ensures FK enforcement is ON
    def _conn_factory():
        c = sqlite3.connect(db_path)
        c.execute("PRAGMA foreign_keys = ON")
        return c

    with patch("aimac.database._core.get_connection", side_effect=_conn_factory):
        with pytest.raises(sqlite3.IntegrityError):
            db.set_active_leaderboard(9999)
