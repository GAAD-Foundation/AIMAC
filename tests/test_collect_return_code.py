"""Tests for collect_command() return code on failures.

Covers:
- Returns 1 when HTTP failures occur (results['failed'] > 0)
- Returns 1 when screenshot failures occur (results['screenshot_failed'] > 0)
"""

import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

from aimac.collector import collect_command


def _setup_db_with_schema(db_path: Path) -> None:
    """Load schema files to build a test database."""
    conn = sqlite3.connect(db_path)
    try:
        for fname in [
            "001_models.sql",
            "002_view_models.sql",
            "003_batches.sql",
            "004_model_sets.sql",
            "005_categories.sql",
            "006_leaderboards.sql",
            "008_leaderboard_active.sql",
            "010_system_prompts.sql",
            "011_system_prompt_active.sql",
            "012_view_system_prompt_active.sql",
            "013_model_categories_request.sql",
            "014_model_categories_responses.sql",
            "015_model_categories_summary.sql",
            "017_view_model_categories_request.sql",
            "018_view_model_categories_responses.sql",
            "019_view_artifact_paths.sql",
        ]:
            sql = Path("data/schema") / fname
            conn.executescript(sql.read_text())
        conn.commit()
    finally:
        conn.close()


def test_collect_returns_1_on_http_failures(tmp_path, capsys):
    """collect_command() should return 1 when HTTP requests fail."""
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    _setup_db_with_schema(db_path)

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
        with patch("aimac.collector.fetch_top_models") as mock_fetch, patch(
            "aimac.collector._execute_and_complete_batch",
            return_value={"failed": 5, "screenshot_failed": 0},  # HTTP failures
        ):
            mock_fetch.return_value = models

            with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                rc = collect_command(refresh=True)

    # Should return 1 because there were HTTP failures
    assert rc == 1, f"Expected rc=1 on HTTP failures, got rc={rc}"

    out = capsys.readouterr().out
    assert "[WARN]" in out, "Should print warning about failures"


def test_collect_returns_1_on_analysis_failures(tmp_path, capsys):
    """collect_command() should return 1 when analysis (screenshot/axe) fails."""
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    _setup_db_with_schema(db_path)

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
        with patch("aimac.collector.fetch_top_models") as mock_fetch, patch(
            "aimac.collector._execute_and_complete_batch",
            return_value={"failed": 0, "screenshot_failed": 3},  # Screenshot failures
        ):
            mock_fetch.return_value = models

            with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                rc = collect_command(refresh=True)

    # Should return 1 because there were analysis failures
    assert rc == 1, f"Expected rc=1 on analysis failures, got rc={rc}"


def test_collect_returns_0_on_success(tmp_path, capsys):
    """collect_command() should return 0 when no failures occur."""
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    _setup_db_with_schema(db_path)

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
        with patch("aimac.collector.fetch_top_models") as mock_fetch, patch(
            "aimac.collector._execute_and_complete_batch",
            return_value={"failed": 0, "screenshot_failed": 0},  # No failures
        ):
            mock_fetch.return_value = models

            with patch("aimac.database.get_connection", side_effect=lambda: sqlite3.connect(db_path)):
                rc = collect_command(refresh=True)

    # Should return 0 because there were no failures
    assert rc == 0, f"Expected rc=0 on success, got rc={rc}"

    out = capsys.readouterr().out
    assert "[OK] Collection complete!" in out
