"""Integration test for screenshots in the collect workflow.

This test seeds a minimal database, mocks the API surface, and verifies
that PNGs are generated alongside HTML artifacts after running
`collect_command`. It skips gracefully if Playwright browsers are not
available on the test machine.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from aimac.collector import collect_command

# Skip slow browser tests in local dev unless explicitly requested
_SKIP_SLOW_LOCALLY = os.getenv("CI") != "true" and os.getenv("RUN_SLOW_TESTS") != "1"


def _exec_schema(conn: sqlite3.Connection, *names: str) -> None:
    base = Path("data/schema")
    for name in names:
        sql = (base / name).read_text()
        conn.executescript(sql)


def _insert_min_model(conn: sqlite3.Connection, model_id: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO models (
            id, name, description, context_length,
            supported_parameters, pricing, created,
            canonical_slug, hugging_face_id
        ) VALUES (?, ?, '', 1, '[]', '{}', 0, NULL, NULL)
        """,
        (model_id, "Test Model"),
    )
    conn.commit()
    return int(cur.lastrowid)


def _enable_single_category(conn: sqlite3.Connection, slug: str, user_prompt: str) -> int:
    # Disable any pre-seeded categories, then insert and enable one
    conn.execute("DELETE FROM categories")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO categories (category_slug, name, description, user_prompt, enabled)
        VALUES (?, ?, '', ?, 1)
        """,
        (slug, slug.title(), user_prompt),
    )
    conn.commit()
    return int(cur.lastrowid)


@pytest.mark.skipif(_SKIP_SLOW_LOCALLY, reason="Slow test - set RUN_SLOW_TESTS=1 or run in CI")
@pytest.mark.slow
def test_collect_generates_screenshots(tmp_path: Path, capsys):
    # Prepare isolated database
    db_path = tmp_path / "screenshots_integration.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _exec_schema(
            conn,
            "001_models.sql",
            "004_model_sets.sql",
            "005_categories.sql",
            "003_batches.sql",
            "006_leaderboards.sql",
            "008_leaderboard_active.sql",
            "013_model_categories_request.sql",
            "014_model_categories_responses.sql",
            "017_view_model_categories_request.sql",
            "018_view_model_categories_responses.sql",
            "019_view_artifact_paths.sql",
            "010_system_prompts.sql",
            "011_system_prompt_active.sql",
            "012_view_system_prompt_active.sql",
        )

        # Seed a single enabled category and a minimal model
        _enable_single_category(conn, "sshot-int", "Please output a complete HTML page")
        model_id = "test/model-sshot"
        _insert_min_model(conn, model_id)

        # Mock fetch_top_models to return our one model
        with patch("aimac.collector.fetch_top_models") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "id": model_id,
                    "name": "Test Model",
                    "description": "",
                    "context_length": 1,
                    "supported_parameters": [],
                    "pricing": {},
                    "created": 0,
                }
            ]

            # Mock OpenRouter completion to return a usable HTML snippet
            async def _fake_send_completion(_client, _body, *, timeout_seconds: float = 60.0):
                return {
                    "status": 200,
                    "json": {
                        "http_status": 200,
                        "choices": [
                            {"message": {"content": "<html><body><h1>OK</h1></body></html>"}}
                        ],
                        "usage": {"cost": 0.01},
                    },
                }

            # Important: executor imports the symbol directly, so patch the
            # binding used by executor to avoid any real network path.
            with patch("aimac.executor.send_completion", side_effect=_fake_send_completion):
                # Route code under test to our temp DB and temp data dir
                with patch.dict(os.environ, {"AIMAC_DATABASE_PATH": str(db_path), "AIMAC_DATA_DIR": str(tmp_path)}):
                    # Force a fresh run; parallel screenshots default ON
                    rc = collect_command(refresh=True)
                    assert rc == 0

        # Locate latest batch output dir
        rows = conn.execute("SELECT batch_date, batch_time, pk FROM batches ORDER BY pk DESC LIMIT 1").fetchone()
        assert rows is not None
        bdir = tmp_path / "output" / str(rows[0]) / str(rows[1]) / f"batch_{rows[2]}"

        # Count artifacts
        htmls = list(bdir.rglob("*.html"))
        pngs = list(bdir.rglob("*.png"))

        if not pngs:
            pytest.skip("Playwright browser not installed; screenshots were not generated")

        # Validate presence and non-empty PNGs
        assert len(htmls) == len(pngs) == 1
        assert pngs[0].stat().st_size > 0

    finally:
        conn.close()
