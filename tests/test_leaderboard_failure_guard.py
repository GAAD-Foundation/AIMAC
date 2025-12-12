"""Regression test: Do not create/activate leaderboard when batch has failures.

Ensures `_execute_and_complete_batch()` early-returns after marking the batch
completed, and skips leaderboard creation/activation when any failures occur.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

from aimac.collector import _execute_and_complete_batch


def _exec_schema(conn: sqlite3.Connection, *names: str) -> None:
    base = Path("data/schema")
    for name in names:
        sql = (base / name).read_text()
        conn.executescript(sql)


def test_no_leaderboard_when_batch_has_failures(tmp_path, capsys):
    # Prepare isolated DB with only batches table
    db_path = tmp_path / "fail_guard.db"
    conn = sqlite3.connect(db_path)
    try:
        _exec_schema(conn, "003_batches.sql")
        conn.execute(
            "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
        )
        batch_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    # Route DB access to our temp DB
    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        # Simulate executor summary with failures
        with patch("aimac.collector.execute_pending_requests", return_value={
            "succeeded": 559,
            "failed": 1,
            "elapsed_minutes": 15.5,
        }):
            # Ensure leaderboard creation/activation are NOT called
            with patch("aimac.collector.create_leaderboard_from_cached") as mock_create, \
                 patch("aimac.collector.set_active_leaderboard") as mock_set_active:
                _execute_and_complete_batch(batch_pk, model_set_pk=1, model_ids=["test/model"], old_models=set())

                # Output should warn and skip leaderboard
                out = capsys.readouterr().out
                assert "HTTP: 1" in out
                assert "NOT creating leaderboard" in out
                assert "Previous leaderboard remains active" in out

                # Batch must still be marked completed
                c2 = sqlite3.connect(db_path)
                try:
                    row = c2.execute("SELECT completed_at FROM batches WHERE pk = ?", (batch_pk,)).fetchone()
                    assert row is not None and row[0] is not None
                finally:
                    c2.close()

                # No leaderboard creation/activation
                mock_create.assert_not_called()
                mock_set_active.assert_not_called()


def test_no_leaderboard_when_analysis_failures(tmp_path, capsys):
    """Regression test: Analysis failures (screenshot/axe) should block leaderboard creation.

    Bug: Previously only checked HTTP failures, allowing leaderboards with missing artifacts.
    """
    # Prepare isolated DB with only batches table
    db_path = tmp_path / "analysis_fail_guard.db"
    conn = sqlite3.connect(db_path)
    try:
        _exec_schema(conn, "003_batches.sql")
        conn.execute(
            "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
        )
        batch_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    # Route DB access to our temp DB
    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        # Simulate executor summary: HTTP succeeded but screenshots failed
        with patch("aimac.collector.execute_pending_requests", return_value={
            "succeeded": 560,
            "failed": 0,  # No HTTP failures
            "elapsed_minutes": 15.5,
            "screenshot_failed": 3,  # But 3 screenshots/axe failed
            "screenshot_succeeded": 557,
        }):
            # Ensure leaderboard creation/activation are NOT called
            with patch("aimac.collector.create_leaderboard_from_cached") as mock_create, \
                 patch("aimac.collector.set_active_leaderboard") as mock_set_active:
                _execute_and_complete_batch(batch_pk, model_set_pk=1, model_ids=["test/model"], old_models=set())

                # Output should warn about screenshot failures
                out = capsys.readouterr().out
                assert "screenshots: 3" in out
                assert "NOT creating leaderboard" in out
                assert "Previous leaderboard remains active" in out

                # Batch must still be marked completed
                c2 = sqlite3.connect(db_path)
                try:
                    row = c2.execute("SELECT completed_at FROM batches WHERE pk = ?", (batch_pk,)).fetchone()
                    assert row is not None and row[0] is not None
                finally:
                    c2.close()

                # No leaderboard creation/activation
                mock_create.assert_not_called()
                mock_set_active.assert_not_called()


def test_leaderboard_created_when_no_failures(tmp_path, capsys):
    """Leaderboard should be created when both HTTP and analysis succeed."""
    # Prepare isolated DB with required tables
    db_path = tmp_path / "success_guard.db"
    conn = sqlite3.connect(db_path)
    try:
        _exec_schema(
            conn,
            "001_models.sql",
            "003_batches.sql",
            "004_model_sets.sql",
            "005_categories.sql",
            "006_leaderboards.sql",
            "015_model_categories_summary.sql",
        )
        conn.execute(
            "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (20250101, 101010, CURRENT_TIMESTAMP)"
        )
        batch_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert a model and model_set
        conn.execute("INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created) VALUES ('test/model', 'Test', 'Test', 1000, '[]', '{}', 0)")
        # sorted_model_list must be canonical: lowercase, deduped, sorted, no spaces
        conn.execute('INSERT INTO model_sets (sorted_model_list) VALUES (\'["test/model"]\')')
        model_set_pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.commit()
    finally:
        conn.close()

    # Route DB access to our temp DB
    with patch("aimac.database._core.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        # Simulate executor summary: all succeeded
        with patch("aimac.collector.execute_pending_requests", return_value={
            "succeeded": 560,
            "failed": 0,
            "elapsed_minutes": 15.5,
            "screenshot_failed": 0,
            "screenshot_succeeded": 560,
        }):
            # Mock the leaderboard creation functions
            with patch("aimac.collector.get_tier2_pairs_with_costs", return_value=(set(), {})), \
                 patch("aimac.collector.create_leaderboard_from_cached", return_value=1) as mock_create, \
                 patch("aimac.collector.is_leaderboard_complete", return_value=True), \
                 patch("aimac.collector.set_active_leaderboard") as mock_set_active:
                _execute_and_complete_batch(batch_pk, model_set_pk=model_set_pk, model_ids=["test/model"], old_models=set())

                # Should create and activate leaderboard
                mock_create.assert_called_once()
                mock_set_active.assert_called_once_with(1)
