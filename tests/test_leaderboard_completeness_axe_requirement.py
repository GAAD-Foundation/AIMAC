"""Regression tests: Leaderboard completeness must require axe_runs for all pairs.

These tests verify that:
1. is_leaderboard_complete returns False when any model×category lacks axe_runs
2. create_leaderboard_from_cached sets is_complete=0 for models missing axe data

Bug context (lastmac-s4j):
- Current code marks leaderboards complete based on 28-category count
- This allows leaderboards with missing accessibility data to be activated
- Fix: completeness must verify axe_runs row exists for every pair

These tests should FAIL against current code and PASS after the fix.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

from aimac.database._leaderboards import _create_leaderboard_from_cached, _is_leaderboard_complete


def _insert_leaderboard_fixtures(conn: sqlite3.Connection) -> dict:
    """Insert minimal fixtures for leaderboard completeness testing.

    Creates:
    - 1 model in a model_set
    - All 28 enabled categories
    - A leaderboard for the model_set

    Returns dict with PKs for assertions.
    """
    cursor = conn.cursor()

    # Insert model
    cursor.execute("""
        INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created)
        VALUES ('test/completeness-model', 'Test Model', '', 4096, '[]', '{}', 0)
    """)
    model_pk = cursor.lastrowid

    # Create model_set with this model
    cursor.execute("""
        INSERT INTO model_sets (sorted_model_list)
        VALUES ('["test/completeness-model"]')
    """)
    model_set_pk = cursor.lastrowid

    # Get all 28 enabled category PKs
    cursor.execute("SELECT pk FROM categories WHERE enabled = 1 ORDER BY pk")
    category_pks = [row[0] for row in cursor.fetchall()]
    assert len(category_pks) == 28, f"Expected 28 enabled categories, got {len(category_pks)}"

    # Get system prompt FK
    cursor.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1")
    system_prompt_pk = cursor.fetchone()[0]

    # Insert batch
    cursor.execute("""
        INSERT INTO batches (batch_date, batch_time, started_at)
        VALUES (20250101, 120000, CURRENT_TIMESTAMP)
    """)
    batch_pk = cursor.lastrowid

    # Insert leaderboard for this model_set
    cursor.execute("""
        INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd)
        VALUES (?, 0.0)
    """, (model_set_pk,))
    leaderboard_pk = cursor.lastrowid

    conn.commit()

    return {
        "model_pk": model_pk,
        "model_set_pk": model_set_pk,
        "category_pks": category_pks,
        "system_prompt_pk": system_prompt_pk,
        "batch_pk": batch_pk,
        "leaderboard_pk": leaderboard_pk,
    }


def _insert_request_response_axe(
    conn: sqlite3.Connection,
    *,
    batch_pk: int,
    model_pk: int,
    category_pk: int,
    system_prompt_pk: int,
    include_axe: bool = True,
) -> int:
    """Insert a request + response + optionally axe_runs for a model×category pair.

    Returns the request PK.
    """
    cursor = conn.cursor()

    # Insert request
    request_body = json.dumps({"model": "test/completeness-model"})
    cursor.execute("""
        INSERT INTO model_categories_request
        (batches_fk_pk, models_fk_pk, categories_fk_pk, system_prompts_fk_pk, openrouter_request_body)
        VALUES (?, ?, ?, ?, ?)
    """, (batch_pk, model_pk, category_pk, system_prompt_pk, request_body))
    request_pk = cursor.lastrowid

    # Insert successful response (HTTP 200)
    response_json = json.dumps({
        "choices": [{"message": {"content": "<!DOCTYPE html><html><body>Test</body></html>"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300, "cost": 0.001}
    })
    cursor.execute("""
        INSERT INTO model_categories_responses
        (model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp)
        VALUES (?, 1, ?, CURRENT_TIMESTAMP)
    """, (request_pk, response_json))

    # Insert axe_runs only if requested
    if include_axe:
        cursor.execute("""
            INSERT INTO axe_runs (
                model_categories_request_fk_pk,
                total_violations, critical_violations, serious_violations,
                weighted_score, axe_json_path, run_timestamp
            ) VALUES (?, 0, 0, 0, 0.0, '/fake/path.json', CURRENT_TIMESTAMP)
        """, (request_pk,))

    conn.commit()
    return request_pk


class TestIsLeaderboardCompleteRequiresAxe:
    """Tests for is_leaderboard_complete requiring axe_runs."""

    def test_incomplete_when_one_category_missing_axe(self, full_schema_db):
        """Leaderboard with 28 responses but 27 axe_runs should be incomplete.

        This test encodes the bug: current code will FAIL because it only
        checks the is_complete flag on summary rows, not actual axe coverage.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_leaderboard_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pks = fixtures["category_pks"]
        leaderboard_pk = fixtures["leaderboard_pk"]

        # Insert responses + axe for 27 categories (all but the last)
        for cat_pk in category_pks[:-1]:
            _insert_request_response_axe(
                conn,
                batch_pk=fixtures["batch_pk"],
                model_pk=model_pk,
                category_pk=cat_pk,
                system_prompt_pk=fixtures["system_prompt_pk"],
                include_axe=True,
            )

        # Insert response WITHOUT axe for the last category
        _insert_request_response_axe(
            conn,
            batch_pk=fixtures["batch_pk"],
            model_pk=model_pk,
            category_pk=category_pks[-1],
            system_prompt_pk=fixtures["system_prompt_pk"],
            include_axe=False,  # No axe_runs!
        )

        # Insert summary row that claims is_complete=1 (this is the bug)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO model_categories_summary (
                leaderboards_fk_pk, models_fk_pk, ranking,
                median_weighted_score, total_cost_usd, avg_cost_per_page,
                is_complete, categories_array
            ) VALUES (?, ?, 1, 0.0, 0.01, 0.001, 1, ?)
        """, (leaderboard_pk, model_pk, json.dumps(category_pks)))
        conn.commit()

        # Verify we have 28 responses but only 27 axe_runs
        cursor.execute("""
            SELECT COUNT(*) FROM model_categories_responses resp
            JOIN model_categories_request req ON req.pk = resp.model_categories_request_fk_pk
            WHERE req.models_fk_pk = ?
        """, (model_pk,))
        response_count = cursor.fetchone()[0]
        assert response_count == 28, f"Expected 28 responses, got {response_count}"

        cursor.execute("""
            SELECT COUNT(*) FROM axe_runs ar
            JOIN model_categories_request req ON req.pk = ar.model_categories_request_fk_pk
            WHERE req.models_fk_pk = ?
        """, (model_pk,))
        axe_count = cursor.fetchone()[0]
        assert axe_count == 27, f"Expected 27 axe_runs, got {axe_count}"

        # THE BUG: Current code returns True because is_complete=1 on summary
        # THE FIX: Should return False because one category lacks axe_runs
        with patch("aimac.database._core.get_connection", return_value=conn):
            result = _is_leaderboard_complete(conn, leaderboard_pk)

        assert result is False, (
            "is_leaderboard_complete returned True but one category is missing axe_runs. "
            "Completeness must verify all pairs have axe data. "
            "This test fails with current buggy code."
        )

    def test_complete_when_all_categories_have_axe(self, full_schema_db):
        """Leaderboard with 28 responses AND 28 axe_runs should be complete.

        This is the happy path - all categories have full data.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_leaderboard_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pks = fixtures["category_pks"]
        leaderboard_pk = fixtures["leaderboard_pk"]

        # Insert responses + axe for ALL 28 categories
        for cat_pk in category_pks:
            _insert_request_response_axe(
                conn,
                batch_pk=fixtures["batch_pk"],
                model_pk=model_pk,
                category_pk=cat_pk,
                system_prompt_pk=fixtures["system_prompt_pk"],
                include_axe=True,
            )

        # Insert summary row with is_complete=1
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO model_categories_summary (
                leaderboards_fk_pk, models_fk_pk, ranking,
                median_weighted_score, total_cost_usd, avg_cost_per_page,
                is_complete, categories_array
            ) VALUES (?, ?, 1, 0.0, 0.01, 0.001, 1, ?)
        """, (leaderboard_pk, model_pk, json.dumps(category_pks)))
        conn.commit()

        # Should return True - all 28 categories have axe data
        with patch("aimac.database._core.get_connection", return_value=conn):
            result = _is_leaderboard_complete(conn, leaderboard_pk)

        assert result is True, "Leaderboard with all 28 axe_runs should be complete"


class TestCreateLeaderboardFromCachedRequiresAxe:
    """Tests for create_leaderboard_from_cached requiring axe_runs."""

    def test_model_marked_incomplete_when_missing_axe(self, full_schema_db):
        """Model with 28 cost entries but missing axe should have is_complete=0.

        This test encodes the bug: current code sets is_complete=1 based on
        28-category count alone, not axe coverage.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_leaderboard_fixtures(conn)

        model_pk = fixtures["model_pk"]
        model_set_pk = fixtures["model_set_pk"]
        category_pks = fixtures["category_pks"]

        # Insert responses + axe for 27 categories
        for cat_pk in category_pks[:-1]:
            _insert_request_response_axe(
                conn,
                batch_pk=fixtures["batch_pk"],
                model_pk=model_pk,
                category_pk=cat_pk,
                system_prompt_pk=fixtures["system_prompt_pk"],
                include_axe=True,
            )

        # Insert response WITHOUT axe for the last category
        _insert_request_response_axe(
            conn,
            batch_pk=fixtures["batch_pk"],
            model_pk=model_pk,
            category_pk=category_pks[-1],
            system_prompt_pk=fixtures["system_prompt_pk"],
            include_axe=False,
        )

        # Create costs dict with ALL 28 categories (simulating Tier-2 returning them)
        # The bug is that costs exist but axe doesn't for one category
        costs = {(model_pk, cat_pk): 0.001 for cat_pk in category_pks}

        # Create leaderboard from cached costs
        with patch("aimac.database._core.get_connection", return_value=conn):
            new_lb_pk = _create_leaderboard_from_cached(conn, model_set_pk, costs)
            conn.commit()

        # Check the summary row's is_complete flag
        cursor = conn.cursor()
        cursor.execute("""
            SELECT is_complete FROM model_categories_summary
            WHERE leaderboards_fk_pk = ? AND models_fk_pk = ?
        """, (new_lb_pk, model_pk))
        row = cursor.fetchone()
        assert row is not None, "Summary row should exist"

        is_complete = row[0]

        # THE BUG: Current code sets is_complete=1 because 28 categories in costs
        # THE FIX: Should set is_complete=0 because one category lacks axe_runs
        assert is_complete == 0, (
            "Model summary has is_complete=1 but one category is missing axe_runs. "
            "create_leaderboard_from_cached must verify axe coverage. "
            "This test fails with current buggy code."
        )
