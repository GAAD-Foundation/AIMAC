"""Tier 2 cache tests: verify reuse and preparation paths.

Pragmatic tests that focus on the observable behavior of Tier 2:
- FULL cache hit: creates a leaderboard from cached responses and activates it
- PARTIAL cache: creates a batch and inserts request rows for missing pairs

Uses load_full_schema from conftest.py to load complete DB schema.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

from aimac.collector import collect_command

# Import from conftest - pytest handles this automatically
from tests.conftest import load_full_schema


def _insert_min_model(conn: sqlite3.Connection, model_id: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO models (
            id, name, description, context_length,
            supported_parameters, pricing, created,
            canonical_slug, hugging_face_id
        ) VALUES (?, ?, ?, ?, '[]', '{}', 0, NULL, NULL)
        """,
        (model_id, "Test Model", "", 1),
    )
    conn.commit()
    return int(cur.lastrowid)


def _insert_category(conn: sqlite3.Connection, slug: str, user_prompt: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO categories (category_slug, name, description, user_prompt, enabled)
        VALUES (?, ?, '', ?, 1)
        """,
        (slug, slug.replace('-', ' ').title(), user_prompt),
    )
    conn.commit()
    return int(cur.lastrowid)


def _insert_batch(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return int(cur.lastrowid)


def _insert_axe_run(conn: sqlite3.Connection, request_pk: int) -> int:
    """Insert an axe_runs row for a request.

    Tier-2 cache now requires axe_runs to exist (not just HTTP 200).
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO axe_runs (
            model_categories_request_fk_pk,
            total_violations, critical_violations, serious_violations,
            weighted_score, axe_json_path, run_timestamp
        ) VALUES (?, 0, 0, 0, 0.0, '/fake/path.json', CURRENT_TIMESTAMP)
        """,
        (request_pk,),
    )
    conn.commit()
    return int(cur.lastrowid)


def _get_system_prompt_fk(conn: sqlite3.Connection) -> int:
    """Get the system_prompts_fk_pk from the already-seeded system_prompt_active table.

    Note: load_full_schema already loads all schema files including system_prompts
    and system_prompt_active with their default seed data.
    """
    row = conn.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1").fetchone()
    return int(row[0])


def test_tier2_full_cache_creates_and_activates_leaderboard(tmp_path, capsys):
    db_path = tmp_path / "tier2_full.db"
    load_full_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:

        # Seed model (schema already seeded 28 categories)
        model_id = "test/model-1"
        m_pk = _insert_min_model(conn, model_id)

        # Seed batch + request + successful response for ALL 28 categories
        b_pk = _insert_batch(conn)
        sp_fk = _get_system_prompt_fk(conn)
        cur = conn.cursor()

        # Get all 28 enabled categories from schema
        cur.execute("SELECT pk FROM categories WHERE enabled = 1")
        category_pks = [row[0] for row in cur.fetchall()]

        # Seed responses + axe_runs for all 28 categories (required for cache hit)
        # Tier-2 cache requires BOTH http_status=200 AND axe_runs row to exist
        for c_pk in category_pks:
            body = json.dumps({"model": model_id, "messages": []})
            cur.execute(
                """
                INSERT INTO model_categories_request (
                  batches_fk_pk, models_fk_pk, categories_fk_pk,
                  system_prompts_fk_pk, openrouter_request_body
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (b_pk, m_pk, c_pk, sp_fk, body),
            )
            req_pk = int(cur.lastrowid)
            good_resp = json.dumps({
                "choices": [{"message": {"content": "<html>ok</html>"}}],
                "usage": {"cost": 2.5}
            })
            cur.execute(
                """
                INSERT INTO model_categories_responses (
                  model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp
                ) VALUES (?, 1, ?, CURRENT_TIMESTAMP)
                """,
                (req_pk, good_resp),
            )
            # Insert axe_runs row - required for Tier-2 cache to consider this cached
            _insert_axe_run(conn, req_pk)
        conn.commit()

        with patch("aimac.collector.fetch_top_models") as mock_fetch:
            mock_fetch.return_value = [{
                "id": model_id,
                "name": "Test Model",
                "description": "",
                "context_length": 1,
                "supported_parameters": [],
                "pricing": {},
                "created": 0,
            }]

            with patch.dict(os.environ, {"AIMAC_DATA_DIR": str(tmp_path)}):
                with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                    rc = collect_command()
            assert rc == 0

        out = capsys.readouterr().out
        assert "[CACHE HIT] FULL" in out

        # Leaderboard should be created and activated
        row = conn.execute("SELECT COUNT(*) FROM leaderboards").fetchone()
        assert row[0] == 1
        row = conn.execute("SELECT COUNT(*) FROM leaderboard_active").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_tier2_partial_creates_batch_and_requests(tmp_path, capsys):
    db_path = tmp_path / "tier2_partial.db"
    load_full_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:

        # Remove any seeded categories to ensure controlled coverage
        conn.execute("DELETE FROM categories")
        conn.commit()
        # Seed model and two enabled categories; only one will have a cached success
        model_id = "test/model-2"
        m_pk = _insert_min_model(conn, model_id)
        c1 = _insert_category(conn, "tier2-a", "Prompt A")
        c2 = _insert_category(conn, "tier2-b", "Prompt B")

        # Create one cached success for (m_pk, c1) with axe_runs
        # Tier-2 cache requires BOTH http_status=200 AND axe_runs row
        b_pk = _insert_batch(conn)
        # active system prompt already seeded via schema execution above
        sp_fk = conn.execute(
            "SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1"
        ).fetchone()[0]
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO model_categories_request (
              batches_fk_pk, models_fk_pk, categories_fk_pk,
              system_prompts_fk_pk, openrouter_request_body
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (b_pk, m_pk, c1, sp_fk, json.dumps({"model": model_id})),
        )
        req_pk = int(cur.lastrowid)
        good_resp = json.dumps({
            "choices": [{"message": {"content": "<html>ok</html>"}}],
            "usage": {"cost": 1.0}
        })
        cur.execute(
            """
            INSERT INTO model_categories_responses (
              model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp
            ) VALUES (?, 1, ?, CURRENT_TIMESTAMP)
            """,
            (req_pk, good_resp),
        )
        # Insert axe_runs row - required for Tier-2 cache
        _insert_axe_run(conn, req_pk)
        conn.commit()

        with patch("aimac.collector.fetch_top_models") as mock_fetch, patch(
            "aimac.collector._execute_and_complete_batch",
            return_value={"failed": 0, "screenshot_failed": 0, "screenshot_total": 0, "screenshot_succeeded": 0},
        ):
            mock_fetch.return_value = [{
                "id": model_id,
                "name": "Test Model",
                "description": "",
                "context_length": 1,
                "supported_parameters": [],
                "pricing": {},
                "created": 0,
            }]
            with patch.dict(os.environ, {"AIMAC_DATA_DIR": str(tmp_path)}):
                with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                    rc = collect_command()
            assert rc == 0

        out = capsys.readouterr().out
        assert "[CACHE PARTIAL]" in out

        # One batch created
        row = conn.execute("SELECT COUNT(*) FROM batches").fetchone()
        assert row[0] >= 1
        # One new request inserted for the missing pair (m_pk, c2)
        row = conn.execute(
            "SELECT COUNT(*) FROM model_categories_request WHERE categories_fk_pk = ?",
            (c2,),
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()
