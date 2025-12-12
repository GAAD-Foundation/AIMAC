"""Tests for model_categories_responses helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest


def _exec_schema(conn: sqlite3.Connection, *files: str) -> None:
    for name in files:
        sql = Path("data/schema", name).read_text()
        conn.executescript(sql)


def _seed_request(conn: sqlite3.Connection) -> int:
    conn.execute("PRAGMA foreign_keys = ON")
    _exec_schema(
        conn,
        "001_models.sql",
        "003_batches.sql",
        "005_categories.sql",
        "010_system_prompts.sql",
        "011_system_prompt_active.sql",
        "013_model_categories_request.sql",
        "014_model_categories_responses.sql",
    )

    # seed model
    conn.execute(
        """
        INSERT INTO models (
            id, name, description, context_length, supported_parameters, pricing, created,
            canonical_slug, hugging_face_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            "openai/gpt-mini",
            "OpenAI: GPT Mini",
            "desc",
            4096,
            json.dumps(["response_format"]),
            json.dumps({"prompt": "0.01", "completion": "0.02"}),
            0,
        ),
    )
    model_pk = int(conn.execute("SELECT pk FROM models WHERE id='openai/gpt-mini'").fetchone()[0])
    # batch
    conn.execute(
        "INSERT INTO batches (batch_date, batch_time, started_at) VALUES (?,?,datetime('now'))",
        (20250101, 101010),
    )
    batch_pk = int(conn.execute("SELECT pk FROM batches").fetchone()[0])
    # category
    row = conn.execute("SELECT pk FROM categories WHERE enabled=1 ORDER BY pk").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO categories (category_slug, name, description, user_prompt, enabled) VALUES (?,?,?,?,1)",
            ("test-cat", "Test Cat", "desc", "prompt"),
        )
        category_pk = int(conn.execute("SELECT pk FROM categories WHERE category_slug='test-cat'").fetchone()[0])
    else:
        category_pk = int(row[0])
    # system prompt fk
    sys_fk = int(
        conn.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk=1").fetchone()[0]
    )
    # request
    req_body = json.dumps(
        {
            "model": "openai/gpt-mini",
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
        (batch_pk, model_pk, category_pk, sys_fk, req_body),
    )
    pk = int(conn.execute("SELECT pk FROM model_categories_request").fetchone()[0])
    conn.commit()
    return pk


def test_insert_response_multiple_attempts_and_constraints(monkeypatch, tmp_path):
    from aimac import database as db

    db_path = tmp_path / "resp.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        request_pk = _seed_request(conn)
        # Return a new connection per call so wrapper can close it (with FK ON)
        def _open():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            return c
        monkeypatch.setattr("aimac.database._core.get_connection", _open)

        # Insert attempts 1, 2, 3
        pks = []
        for n in (1, 2, 3):
            pk = db.insert_response(request_pk, n, json.dumps({"ok": True, "n": n}))
            pks.append(pk)
        assert all(isinstance(x, int) and x > 0 for x in pks)

        # Verify attempts present
        attempts = [int(r[0]) for r in conn.execute(
            "SELECT attempt_number FROM model_categories_responses WHERE model_categories_request_fk_pk=? ORDER BY attempt_number",
            (request_pk,),
        ).fetchall()]
        assert attempts == [1, 2, 3]

        # Duplicate attempt should violate unique constraint
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_response(request_pk, 1, json.dumps({}))

        # Invalid FK should fail
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_response(999999, 1, json.dumps({}))
    finally:
        conn.close()
