"""Tests for axe run database helpers (UPSERT + FK)."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest


def _exec_schema(conn: sqlite3.Connection, *files: str) -> None:
    for name in files:
        sql = Path("data/schema", name).read_text()
        conn.executescript(sql)


def _seed_minimal_request(conn: sqlite3.Connection) -> int:
    """Create a minimal valid model_categories_request and return its pk."""
    # Foreign keys ON for FK tests
    conn.execute("PRAGMA foreign_keys = ON")

    # Minimal core tables
    _exec_schema(
        conn,
        "001_models.sql",
        "003_batches.sql",
        "005_categories.sql",
        "010_system_prompts.sql",
        "011_system_prompt_active.sql",
        "013_model_categories_request.sql",
        "016_axe_runs.sql",
        "024_axe_rule_breakdown.sql",
        "025_axe_rules.sql",
    )

    # Seed one model
    conn.execute(
        """
        INSERT INTO models (
            id, name, description, context_length, supported_parameters, pricing, created,
            canonical_slug, hugging_face_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            "openai/gpt-4o",
            "OpenAI: GPT-4o",
            "desc",
            8192,
            json.dumps(["response_format"]),
            json.dumps({"prompt": "0.01", "completion": "0.02"}),
            0,
        ),
    )
    model_pk = int(conn.execute("SELECT pk FROM models WHERE id='openai/gpt-4o'").fetchone()[0])

    # Seed one batch
    conn.execute(
        "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (?,?,datetime('now'))",
        (20250101, 123456),
    )
    batch_pk = int(conn.execute("SELECT pk FROM batches").fetchone()[0])

    # Ensure one enabled category exists (use seeded set or insert a simple one)
    # The seed file includes many enabled categories; pick first enabled
    row = conn.execute("SELECT pk FROM categories WHERE enabled = 1 ORDER BY pk ASC").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO categories (category_slug, name, description, user_prompt, enabled) VALUES (?,?,?,?,1)",
            ("test-cat", "Test Cat", "desc", "prompt"),
        )
        category_pk = int(conn.execute("SELECT pk FROM categories WHERE category_slug='test-cat'").fetchone()[0])
    else:
        category_pk = int(row[0])

    # Active system prompt fk
    sys_fk = int(
        conn.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk=1").fetchone()[0]
    )

    # Insert a request row
    request_body = json.dumps(
        {
            "model": "openai/gpt-4o",
            "messages": [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
            ],
            "usage": {"include": True},
            "reasoning": {"exclude": True},
            "provider": {"sort": "throughput"},
        }
    )
    conn.execute(
        """
        INSERT INTO model_categories_request (
            batches_fk_pk, models_fk_pk, categories_fk_pk, system_prompts_fk_pk, openrouter_request_body
        ) VALUES (?,?,?,?,?)
        """,
        (batch_pk, model_pk, category_pk, sys_fk, request_body),
    )
    request_pk = int(conn.execute("SELECT pk FROM model_categories_request").fetchone()[0])
    conn.commit()
    return request_pk


def test_insert_axe_run_upsert_and_fk(monkeypatch, tmp_path):
    """insert_axe_run should be idempotent and enforce FK constraints."""
    from aimac import database as db

    # Temp sqlite db and schema
    db_path = tmp_path / "axe.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        request_pk = _seed_minimal_request(conn)

        # Patch connection factory so public API uses our temp db
        # Return a new connection each time with FK enforcement so wrapper can close safely
        def _open():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            return c
        monkeypatch.setattr("aimac.database._core.get_connection", _open)

        # First insert
        pk1 = db.insert_axe_run(
            request_pk=request_pk,
            total_violations=10,
            critical_violations=2,
            serious_violations=8,
            weighted_score=1.23,
            axe_json_path="out/1.axe.json",
            rule_breakdown={"color-contrast": 3, "link-name": 1},
            rule_metadata={
                "color-contrast": {"help": "Color contrast issue", "help_url": "https://example.com/color"},
                "link-name": {"help": "Links must have text", "help_url": ""},
            },
            axe_version="4.10.2",
        )
        row = conn.execute(
            "SELECT total_violations, critical_violations, serious_violations, weighted_score, axe_json_path FROM axe_runs WHERE model_categories_request_fk_pk=?",
            (request_pk,),
        ).fetchone()
        assert row is not None
        assert (row[0], row[1], row[2]) == (10, 2, 8)
        assert pytest.approx(row[3], rel=1e-6) == 1.23
        assert row[4] == "out/1.axe.json"

        # Rule breakdown rows should exist for both rules
        breakdown_rows = conn.execute(
            """
            SELECT rule_id, violation_count
            FROM axe_rule_breakdown
            WHERE axe_runs_fk_pk = ?
            ORDER BY rule_id
            """,
            (pk1,),
        ).fetchall()
        assert [tuple(r) for r in breakdown_rows] == [
            ("color-contrast", 3),
            ("link-name", 1),
        ]

        # Axe rules metadata persisted with first/last version
        rule_row = conn.execute(
            "SELECT help, help_url, first_seen_version, last_seen_version FROM axe_rules WHERE rule_id = ?",
            ("color-contrast",),
        ).fetchone()
        assert tuple(rule_row) == ("Color contrast issue", "https://example.com/color", "4.10.2", "4.10.2")

        # Second insert with different values should update same row (UPSERT)
        pk2 = db.insert_axe_run(
            request_pk=request_pk,
            total_violations=5,
            critical_violations=1,
            serious_violations=4,
            weighted_score=0.5,
            axe_json_path="out/1b.axe.json",
            rule_breakdown={"color-contrast": 1, "label": 5},
            rule_metadata={
                "color-contrast": {"help": "Color contrast still failing", "help_url": "https://example.com/color2"},
                "label": {"help": None, "help_url": None},
            },
            axe_version="4.11.0",
        )
        rows = conn.execute(
            "SELECT COUNT(*) FROM axe_runs WHERE model_categories_request_fk_pk=?",
            (request_pk,),
        ).fetchone()
        assert int(rows[0]) == 1
        row2 = conn.execute(
            "SELECT total_violations, critical_violations, serious_violations, weighted_score, axe_json_path FROM axe_runs WHERE model_categories_request_fk_pk=?",
            (request_pk,),
        ).fetchone()
        assert (row2[0], row2[1], row2[2]) == (5, 1, 4)
        assert pytest.approx(row2[3], rel=1e-6) == 0.5
        assert row2[4] == "out/1b.axe.json"

        # Rule breakdown rows should reflect latest data only
        breakdown_rows_updated = conn.execute(
            """
            SELECT rule_id, violation_count
            FROM axe_rule_breakdown
            WHERE axe_runs_fk_pk = ?
            ORDER BY rule_id
            """,
            (pk2,),
        ).fetchall()
        assert [tuple(r) for r in breakdown_rows_updated] == [
            ("color-contrast", 1),
            ("label", 5),
        ]

        # Axe rule metadata should update last_seen_version and help text
        color_row = conn.execute(
            "SELECT help, help_url, first_seen_version, last_seen_version FROM axe_rules WHERE rule_id = ?",
            ("color-contrast",),
        ).fetchone()
        assert tuple(color_row) == (
            "Color contrast still failing",
            "https://example.com/color2",
            "4.10.2",
            "4.11.0",
        )
        label_row = conn.execute(
            "SELECT help FROM axe_rules WHERE rule_id = ?",
            ("label",),
        ).fetchone()
        assert label_row[0] == "Label"

        # Return value may be 0 on update; both calls should be ints
        assert isinstance(pk1, int)
        assert isinstance(pk2, int)

        # Invalid FK should raise
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_axe_run(
                request_pk=999999,
                total_violations=1,
                critical_violations=0,
                serious_violations=1,
                weighted_score=0.1,
                axe_json_path="out/x.axe.json",
            )
    finally:
        conn.close()


def test_insert_axe_run_clears_breakdown_on_zero_violations(monkeypatch, tmp_path):
    """Re-running with zero violations should delete stale breakdown rows."""
    from aimac import database as db

    db_path = tmp_path / "axe.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        request_pk = _seed_minimal_request(conn)

        def _open():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            return c
        monkeypatch.setattr("aimac.database._core.get_connection", _open)

        # First insert with violations
        pk1 = db.insert_axe_run(
            request_pk=request_pk,
            total_violations=5,
            critical_violations=1,
            serious_violations=4,
            weighted_score=1.0,
            axe_json_path="out/1.axe.json",
            rule_breakdown={"color-contrast": 3, "link-name": 2},
        )

        # Verify breakdown rows exist
        count = conn.execute(
            "SELECT COUNT(*) FROM axe_rule_breakdown WHERE axe_runs_fk_pk = ?",
            (pk1,),
        ).fetchone()[0]
        assert count == 2

        # Re-run with zero violations (empty breakdown)
        pk2 = db.insert_axe_run(
            request_pk=request_pk,
            total_violations=0,
            critical_violations=0,
            serious_violations=0,
            weighted_score=0.0,
            axe_json_path="out/1b.axe.json",
            rule_breakdown=None,  # Zero violations = no breakdown
        )

        # PK should be the same (UPSERT)
        assert pk1 == pk2

        # Stale breakdown rows must be deleted
        count_after = conn.execute(
            "SELECT COUNT(*) FROM axe_rule_breakdown WHERE axe_runs_fk_pk = ?",
            (pk2,),
        ).fetchone()[0]
        assert count_after == 0, "Stale breakdown rows should be deleted on zero-violation re-run"
    finally:
        conn.close()
