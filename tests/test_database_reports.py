"""Tests for read-only reporting helpers in aimac.database._reports."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from aimac.database import _reports as R


def _exec_schema(conn: sqlite3.Connection, *files: str) -> None:
    for name in files:
        sql = Path("data/schema", name).read_text()
        conn.executescript(sql)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def test_get_active_leaderboard_none_when_unconfigured():
    conn = _conn()
    try:
        _exec_schema(conn, "006_leaderboards.sql", "008_leaderboard_active.sql")
        assert R.get_active_leaderboard(conn) is None
    finally:
        conn.close()


def test_get_active_leaderboard_returns_values():
    conn = _conn()
    try:
        _exec_schema(conn, "004_model_sets.sql", "006_leaderboards.sql", "008_leaderboard_active.sql")
        # Create a model_set for FK integrity
        conn.execute("INSERT INTO model_sets (sorted_model_list) VALUES (?)", (json.dumps(["a/b"]),))
        ms_pk = int(conn.execute("SELECT pk FROM model_sets").fetchone()[0])
        conn.execute(
            "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd) VALUES (?, ?)",
            (ms_pk, 0.0),
        )
        lb_pk = int(conn.execute("SELECT pk FROM leaderboards").fetchone()[0])
        conn.execute(
            "INSERT INTO leaderboard_active (pk, leaderboards_fk_pk) VALUES (1, ?)", (lb_pk,)
        )
        out = R.get_active_leaderboard(conn)
        assert isinstance(out, dict)
        assert out["pk"] == lb_pk
        assert out["model_set_id"] == ms_pk
        assert "created_at" in out
    finally:
        conn.close()


def test_fuzzy_find_models_various_matches():
    conn = _conn()
    try:
        _exec_schema(conn, "001_models.sql", "002_view_models.sql")
        # Seed two models
        rows = [
            ("openai/gpt-foo", "OpenAI: GPT Foo"),
            ("openai/gpt-bar", "OpenAI: GPT Bar"),
        ]
        for mid, name in rows:
            conn.execute(
                "INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created) VALUES (?,?,?,?,?,?,?)",
                (mid, name, "d", 2048, json.dumps(["response_format"]), json.dumps({"prompt": "0", "completion": "0"}), 0),
            )
        # substring and case-insensitive
        m = R.fuzzy_find_models(conn, "gpt")
        assert len(m) == 2
        m2 = R.fuzzy_find_models(conn, "OPENAI/GPT-FOO")
        assert len(m2) == 1 and m2[0]["model_id"] == "openai/gpt-foo"
    finally:
        conn.close()


def test_fuzzy_find_categories_enabled_only():
    conn = _conn()
    try:
        _exec_schema(conn, "005_categories.sql")
        # Disabled adult-content should not match
        assert R.fuzzy_find_categories(conn, "adult") == []
        # Known enabled slug from seed should match
        hits = R.fuzzy_find_categories(conn, "careers")
        assert any(h["slug"] == "careers" for h in hits)
    finally:
        conn.close()


def test_get_models_for_leaderboard_uses_model_set():
    conn = _conn()
    try:
        _exec_schema(conn, "001_models.sql", "002_view_models.sql", "004_model_sets.sql", "006_leaderboards.sql")
        # Seed models
        ids = ["acme/alpha", "beta/gamma", "openai/gpt-foo"]
        for i, mid in enumerate(ids):
            conn.execute(
                "INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created) VALUES (?,?,?,?,?,?,?)",
                (mid, f"Name {i}", "d", 1024, json.dumps([]), json.dumps({"prompt": "0", "completion": "0"}), 0),
            )
        # Model set uses specific ids
        ms_ids = sorted([ids[2], ids[0]])  # canonicalize per trigger rules
        conn.execute(
            "INSERT INTO model_sets (sorted_model_list) VALUES (?)",
            (json.dumps(ms_ids, separators=(",", ":")),),
        )
        ms_pk = int(conn.execute("SELECT pk FROM model_sets").fetchone()[0])
        conn.execute(
            "INSERT INTO leaderboards (model_sets_fk_pk, total_cost_usd) VALUES (?, 0.0)", (ms_pk,)
        )
        lb_pk = int(conn.execute("SELECT pk FROM leaderboards").fetchone()[0])
        out = R.get_models_for_leaderboard(conn, lb_pk)
        # Should include exactly the two models, sorted by model pk (insert order)
        assert [o["model_id"] for o in out] == [ids[0], ids[2]]
        assert len(out) == 2
    finally:
        conn.close()
