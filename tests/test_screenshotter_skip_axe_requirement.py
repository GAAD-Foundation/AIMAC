"""Regression tests: Screenshotter skip fast-path must verify DB, not just files.

These tests verify that screenshot_and_axe's skip fast-path does NOT return
axe_ok=True just because PNG and .axe.json files exist on disk. The DB
axe_runs row must also exist.

Bug context (lastmac-s4j):
- Current code returns axe_ok=True when files exist, ignoring DB state
- If a previous run wrote files but DB insert failed, subsequent runs skip
  and never insert axe_runs, leaving leaderboards with missing axe data
- Fix: skip path must verify axe_runs DB row exists before returning axe_ok=True

These tests should FAIL against current code and PASS after the fix.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aimac.screenshotter import screenshot_and_axe


def _setup_test_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Set up a test database with minimal schema for screenshotter tests.

    Returns (db_path, conn) with request row inserted but NO axe_runs.
    """
    from tests.conftest import load_full_schema

    db_path = tmp_path / "test.db"
    load_full_schema(db_path)
    conn = sqlite3.connect(db_path)

    # Insert minimal fixtures
    cursor = conn.cursor()

    # Insert model
    cursor.execute("""
        INSERT INTO models (id, name, description, context_length, supported_parameters, pricing, created)
        VALUES ('test/model', 'Test Model', '', 4096, '[]', '{}', 0)
    """)
    model_pk = cursor.lastrowid

    # Get first enabled category
    cursor.execute("SELECT pk FROM categories WHERE enabled = 1 LIMIT 1")
    category_pk = cursor.fetchone()[0]

    # Insert batch
    cursor.execute("""
        INSERT INTO batches (batch_date, batch_time, started_at)
        VALUES (20250101, 120000, CURRENT_TIMESTAMP)
    """)
    batch_pk = cursor.lastrowid

    # Get system prompt FK
    cursor.execute("SELECT system_prompts_fk_pk FROM system_prompt_active WHERE pk = 1")
    system_prompt_pk = cursor.fetchone()[0]

    # Insert request - use a specific PK that we'll use in the filename
    request_body = json.dumps({"model": "test/model"})
    cursor.execute("""
        INSERT INTO model_categories_request
        (batches_fk_pk, models_fk_pk, categories_fk_pk, system_prompts_fk_pk, openrouter_request_body)
        VALUES (?, ?, ?, ?, ?)
    """, (batch_pk, model_pk, category_pk, system_prompt_pk, request_body))
    request_pk = cursor.lastrowid

    # Insert response with valid HTML
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

    return db_path, conn, request_pk


class TestScreenshotterSkipRequiresDbRow:
    """Tests for skip fast-path requiring axe_runs DB row."""

    @pytest.mark.asyncio
    async def test_skip_returns_axe_ok_false_when_db_missing(self, tmp_path: Path):
        """When files exist but axe_runs row is missing, axe_ok must be False.

        This test encodes the bug: current code will FAIL this test because
        it returns axe_ok=True based only on file existence.

        The fix should make the skip path check the DB before claiming axe_ok=True.
        """
        _db_path, conn, request_pk = _setup_test_db(tmp_path)

        try:
            # Create files on disk using request PK as filename (how the system works)
            html_dir = tmp_path / "html"
            html_dir.mkdir()
            html_file = html_dir / f"{request_pk}.html"
            png_file = html_dir / f"{request_pk}.png"
            axe_file = html_dir / f"{request_pk}.axe.json"

            # Write files - simulating a previous run that wrote files but DB insert failed
            html_file.write_text("<html><body>Test</body></html>")
            png_file.write_bytes(b"fake png data")
            axe_file.write_text('{"violations": []}')

            # Verify files exist
            assert png_file.exists()
            assert axe_file.exists()

            # Verify NO axe_runs row in DB
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM axe_runs WHERE model_categories_request_fk_pk = ?", (request_pk,))
            assert cursor.fetchone()[0] == 0, "Test setup error: axe_runs should not exist"

            # Mock context that should NOT be called (skip path)
            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(side_effect=AssertionError("Should not create page for skip"))

            # Patch get_connection to use our test DB
            with patch("aimac.database._core.get_connection", return_value=conn):
                result = await screenshot_and_axe(
                    mock_context,
                    str(html_file),
                    str(png_file),
                    timeout_ms=5000,
                    wait_images_ms=1000,
                    wait_fonts_ms=1000,
                )

            # THE BUG: Current code returns axe_ok=True because files exist
            # THE FIX: Should return axe_ok=False because DB row is missing
            assert result.axe_ok is False, (
                "Skip fast-path returned axe_ok=True but axe_runs DB row is missing. "
                "Files on disk are NOT authoritative; DB state must be verified. "
                "This test fails with current buggy code."
            )

            # Screenshot should still be OK (file exists)
            assert result.screenshot_ok is True

            # Status could be "skipped" (if we trust screenshot file) or indicate partial success
            # The key invariant is axe_ok=False when DB row is missing

        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_skip_returns_axe_ok_true_when_db_present(self, tmp_path: Path):
        """When files exist AND axe_runs row exists, axe_ok should be True.

        This is the happy path - both disk and DB agree, skip is valid.
        """
        _db_path, conn, request_pk = _setup_test_db(tmp_path)

        try:
            # Create files on disk
            html_dir = tmp_path / "html"
            html_dir.mkdir()
            html_file = html_dir / f"{request_pk}.html"
            png_file = html_dir / f"{request_pk}.png"
            axe_file = html_dir / f"{request_pk}.axe.json"

            html_file.write_text("<html><body>Test</body></html>")
            png_file.write_bytes(b"fake png data")
            axe_file.write_text('{"violations": []}')

            # Insert axe_runs row - this time we HAVE the DB row
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO axe_runs (
                    model_categories_request_fk_pk,
                    total_violations, critical_violations, serious_violations,
                    weighted_score, axe_json_path, run_timestamp
                ) VALUES (?, 0, 0, 0, 0.0, ?, CURRENT_TIMESTAMP)
            """, (request_pk, str(axe_file)))
            conn.commit()

            # Verify axe_runs row exists
            cursor.execute("SELECT COUNT(*) FROM axe_runs WHERE model_categories_request_fk_pk = ?", (request_pk,))
            assert cursor.fetchone()[0] == 1

            # Mock context
            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(side_effect=AssertionError("Should not create page for skip"))

            with patch("aimac.database._core.get_connection", return_value=conn):
                result = await screenshot_and_axe(
                    mock_context,
                    str(html_file),
                    str(png_file),
                    timeout_ms=5000,
                    wait_images_ms=1000,
                    wait_fonts_ms=1000,
                )

            # Both disk and DB agree - skip is valid
            assert result.status == "skipped"
            assert result.screenshot_ok is True
            assert result.axe_ok is True

        finally:
            conn.close()
