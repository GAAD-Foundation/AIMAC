"""Regression tests: Tier-2 cache must require axe_runs, not just HTTP 200.

These tests verify that _get_cached_success_pairs and _get_tier2_pairs_with_costs
do NOT treat a model×category pair as "cached" when there is an HTTP 200
response but no axe_runs row.

Bug context (lastmac-s4j):
- Current code considers http_status=200 sufficient for caching
- This allows leaderboards with missing accessibility data
- Fix: require axe_runs row to exist for a pair to be considered cached

These tests should FAIL against current code and PASS after the fix.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

from aimac.database._model_category import _get_cached_success_pairs, _get_tier2_pairs_with_costs


def _insert_test_fixtures(conn: sqlite3.Connection) -> dict:
    """Insert minimal fixtures for a model×category pair with HTTP 200 but no axe.

    Returns dict with PKs for assertions.
    """
    cursor = conn.cursor()

    # Insert model
    cursor.execute("""
        INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created)
        VALUES ('test/model-no-axe', 'Test Model', 'For testing', 4096, '[]', '{}', 0)
    """)
    model_pk = cursor.lastrowid

    # Get first enabled category (schema seeds 28 enabled categories)
    cursor.execute("SELECT pk FROM categories WHERE enabled = 1 LIMIT 1")
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("No enabled categories found - schema not loaded properly")
    category_pk = row[0]

    # Insert model_set with this model
    model_list_json = json.dumps(["test/model-no-axe"])
    cursor.execute("""
        INSERT INTO model_sets (sorted_model_list)
        VALUES (?)
    """, (model_list_json,))
    model_set_pk = cursor.lastrowid

    # Insert batch
    cursor.execute("""
        INSERT INTO batches (batch_date, batch_time, started_at)
        VALUES (20250101, 120000, CURRENT_TIMESTAMP)
    """)
    batch_pk = cursor.lastrowid

    # Insert system_prompt and activate it
    cursor.execute("""
        INSERT INTO system_prompts (prompt)
        VALUES ('Test prompt')
    """)
    system_prompt_pk = cursor.lastrowid
    cursor.execute("""
        INSERT INTO system_prompt_active (pk, system_prompts_fk_pk)
        VALUES (1, ?)
        ON CONFLICT(pk) DO UPDATE SET system_prompts_fk_pk = excluded.system_prompts_fk_pk
    """, (system_prompt_pk,))

    # Insert request
    request_body = json.dumps({"model": "test/model-no-axe", "messages": []})
    cursor.execute("""
        INSERT INTO model_categories_request
        (batches_fk_pk, models_fk_pk, categories_fk_pk, system_prompts_fk_pk, openrouter_request_body)
        VALUES (?, ?, ?, ?, ?)
    """, (batch_pk, model_pk, category_pk, system_prompt_pk, request_body))
    request_pk = cursor.lastrowid

    # Insert response with valid HTML (triggers http_status=200 in the view)
    # The view determines http_status=200 when valid HTML is extracted
    response_json = json.dumps({
        "choices": [{"message": {"content": "<!DOCTYPE html><html><body>Test</body></html>"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300, "cost": 0.001}
    })
    cursor.execute("""
        INSERT INTO model_categories_responses
        (model_categories_request_fk_pk, attempt_number, openrouter_response, response_timestamp)
        VALUES (?, 1, ?, CURRENT_TIMESTAMP)
    """, (request_pk, response_json))

    # Explicitly do NOT insert axe_runs row - this is the bug we're testing

    conn.commit()

    return {
        "model_pk": model_pk,
        "category_pk": category_pk,
        "model_set_pk": model_set_pk,
        "request_pk": request_pk,
    }


class TestGetCachedSuccessPairsRequiresAxe:
    """Tests for _get_cached_success_pairs requiring axe_runs."""

    def test_http200_without_axe_not_cached(self, full_schema_db):
        """Pair with HTTP 200 but no axe_runs should NOT be in cached pairs.

        This test encodes the bug: current code will FAIL this test because
        it treats HTTP 200 as sufficient for caching.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_test_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pk = fixtures["category_pk"]

        # Verify the response exists and has http_status=200
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.http_status
            FROM view_model_categories_responses v
            JOIN model_categories_request r ON r.pk = v.pk
            WHERE r.models_fk_pk = ? AND r.categories_fk_pk = ?
        """, (model_pk, category_pk))
        row = cursor.fetchone()
        assert row is not None, "Response should exist"
        assert row[0] == 200, f"Expected http_status=200, got {row[0]}"

        # Verify NO axe_runs row exists
        cursor.execute("""
            SELECT COUNT(*) FROM axe_runs ar
            JOIN model_categories_request r ON r.pk = ar.model_categories_request_fk_pk
            WHERE r.models_fk_pk = ? AND r.categories_fk_pk = ?
        """, (model_pk, category_pk))
        axe_count = cursor.fetchone()[0]
        assert axe_count == 0, "Test setup error: axe_runs row should not exist"

        # Call the function under test
        with patch("aimac.database._core.get_connection", return_value=conn):
            # Use the internal function directly with conn
            cached_pairs = _get_cached_success_pairs(
                conn,
                model_pks=[model_pk],
                category_pks=[category_pk],
            )

        # THE BUG: Current code returns this pair as cached
        # THE FIX: This pair should NOT be in cached_pairs
        assert (model_pk, category_pk) not in cached_pairs, (
            "Pair with HTTP 200 but no axe_runs should NOT be considered cached. "
            "This test fails with current buggy code."
        )


class TestTier2PairsWithCostsAxeRequirement:
    """Tests for _get_tier2_pairs_with_costs requiring axe_runs for cached status."""

    def test_http200_without_axe_appears_in_missing(self, full_schema_db):
        """Pair with HTTP 200 but no axe_runs should appear in missing_pairs.

        Tests that the costs dict (which represents cached pairs) does NOT
        include pairs that only have HTTP 200 without axe_runs.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_test_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pk = fixtures["category_pk"]
        model_set_pk = fixtures["model_set_pk"]

        # Call the function under test
        with patch("aimac.database._core.get_connection", return_value=conn):
            full_pairs, costs = _get_tier2_pairs_with_costs(conn, model_set_pk)

        # The pair should be in full_pairs (it's a valid model×category combo)
        assert (model_pk, category_pk) in full_pairs, (
            "Pair should be in full_pairs as it's a valid model×category combo"
        )

        # Cached pairs = keys of costs dict
        cached_pairs = set(costs.keys())

        # THE FIX: This pair should NOT be in cached_pairs (costs dict)
        assert (model_pk, category_pk) not in cached_pairs, (
            "Pair with HTTP 200 but no axe_runs should NOT be in cached_pairs. "
        )

        # Compute missing_pairs (what the collector uses)
        missing_pairs = full_pairs - cached_pairs

        # The pair should be in missing_pairs so it gets re-run
        assert (model_pk, category_pk) in missing_pairs, (
            "Pair with HTTP 200 but no axe_runs should be in missing_pairs "
            "so the collector will re-run it."
        )


class TestTier2PairsWithCostsRequiresAxe:
    """Tests for _get_tier2_pairs_with_costs requiring axe_runs."""

    def test_http200_without_axe_not_in_costs(self, full_schema_db):
        """Pair with HTTP 200 but no axe_runs should NOT have cost.

        The costs dict only includes cached pairs (those with axe_runs).
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_test_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pk = fixtures["category_pk"]
        model_set_pk = fixtures["model_set_pk"]

        # Call the function under test
        with patch("aimac.database._core.get_connection", return_value=conn):
            full_pairs, costs = _get_tier2_pairs_with_costs(conn, model_set_pk)

        # The pair should be in full_pairs (it's a valid model×category combo)
        assert (model_pk, category_pk) in full_pairs, (
            "Pair should be in full_pairs as it's a valid model×category combo"
        )

        # Pair with HTTP 200 but no axe_runs should NOT have a cost entry
        assert (model_pk, category_pk) not in costs, (
            "Pair with HTTP 200 but no axe_runs should NOT be in costs dict. "
            "Costs dict keys represent cached pairs."
        )

        # Compute missing_pairs from the costs dict (as the collector does)
        cached_pairs = set(costs.keys())
        missing_pairs = full_pairs - cached_pairs

        # The pair should be in missing_pairs so it gets re-run
        assert (model_pk, category_pk) in missing_pairs, (
            "Pair with HTTP 200 but no axe_runs should be in missing_pairs "
            "so the collector will re-run it."
        )

    def test_http200_with_axe_has_cost(self, full_schema_db):
        """Pair with HTTP 200 AND axe_runs SHOULD have cost in the dict."""
        _db_path, conn = full_schema_db
        fixtures = _insert_test_fixtures(conn)

        model_pk = fixtures["model_pk"]
        category_pk = fixtures["category_pk"]
        model_set_pk = fixtures["model_set_pk"]
        request_pk = fixtures["request_pk"]

        # Now ADD an axe_runs row to make this a complete cached pair
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO axe_runs (
                model_categories_request_fk_pk, total_violations, critical_violations,
                serious_violations, weighted_score, axe_json_path, run_timestamp
            )
            VALUES (?, 0, 0, 0, 0.0, 'test/path.json', CURRENT_TIMESTAMP)
        """, (request_pk,))
        conn.commit()

        # Call the function under test
        with patch("aimac.database._core.get_connection", return_value=conn):
            full_pairs, costs = _get_tier2_pairs_with_costs(conn, model_set_pk)

        # The pair should be in full_pairs
        assert (model_pk, category_pk) in full_pairs

        # With axe_runs row, pair SHOULD be in costs dict
        assert (model_pk, category_pk) in costs, (
            "Pair with HTTP 200 AND axe_runs should be in costs dict"
        )

        # Cost should be the value from the response
        assert costs[(model_pk, category_pk)] == 0.001, (
            "Cost should match the value from the test fixture response"
        )

    def test_single_query_returns_both_pairs_and_costs(self, full_schema_db):
        """Verify the function returns both full_pairs and costs correctly.

        This tests the consolidated query behavior.
        """
        _db_path, conn = full_schema_db
        fixtures = _insert_test_fixtures(conn)

        model_set_pk = fixtures["model_set_pk"]
        request_pk = fixtures["request_pk"]

        # Add axe_runs to make this a cached pair
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO axe_runs (
                model_categories_request_fk_pk, total_violations, critical_violations,
                serious_violations, weighted_score, axe_json_path, run_timestamp
            )
            VALUES (?, 0, 0, 0, 0.0, 'test/path.json', CURRENT_TIMESTAMP)
        """, (request_pk,))
        conn.commit()

        # Call the function
        with patch("aimac.database._core.get_connection", return_value=conn):
            full_pairs, costs = _get_tier2_pairs_with_costs(conn, model_set_pk)

        # Verify return types
        assert isinstance(full_pairs, set), "full_pairs should be a set"
        assert isinstance(costs, dict), "costs should be a dict"

        # With one model and 28 enabled categories, we should have 28 full pairs
        # (The test model × each enabled category)
        assert len(full_pairs) == 28, f"Expected 28 full pairs (1 model × 28 categories), got {len(full_pairs)}"

        # Only one pair has a response with axe_runs, so only one cost entry
        assert len(costs) == 1, f"Expected 1 cost entry, got {len(costs)}"

        # Cache hit check: len(costs) == len(full_pairs) means full cache
        assert len(costs) != len(full_pairs), "Should not be a full cache hit (only 1 of 28 cached)"
