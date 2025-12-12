"""Smoke tests - Basic functionality verification.

Quick tests to verify the core commands work end-to-end.
"""

from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from aimac.cli import init_command
from aimac.collector import collect_command


def test_init_creates_schema():
    """Verify aimac init creates a working database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        schema_dir = Path(tmpdir) / "schema"
        schema_dir.mkdir()

        # Copy schema files to temp dir
        real_schema = Path("data/schema")
        for sql_file in real_schema.glob("*.sql"):
            (schema_dir / sql_file.name).write_text(sql_file.read_text())

        # Mock environment to use temp paths
        with patch.dict('os.environ', {
            'AIMAC_DATABASE_PATH': str(db_path),
            'AIMAC_DATA_DIR': tmpdir
        }):
            with patch('aimac.database.get_schema_directory') as mock_schema:
                mock_schema.return_value = schema_dir

                # Run init
                result = init_command()

                assert result == 0  # Success
                assert db_path.exists()

                # Verify tables exist
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='models'
                """)
                assert cursor.fetchone() is not None
                conn.close()


def test_collect_command_happy_path():
    """Verify collect command works with mocked API."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Setup database (models + model_sets)
        conn = sqlite3.connect(db_path)
        conn.executescript(Path("data/schema/001_models.sql").read_text())
        conn.executescript(Path("data/schema/002_view_models.sql").read_text())
        conn.executescript(Path("data/schema/003_batches.sql").read_text())
        conn.executescript(Path("data/schema/004_model_sets.sql").read_text())
        conn.executescript(Path("data/schema/005_categories.sql").read_text())
        conn.executescript(Path("data/schema/006_leaderboards.sql").read_text())
        conn.executescript(Path("data/schema/008_leaderboard_active.sql").read_text())
        conn.executescript(Path("data/schema/010_system_prompts.sql").read_text())
        conn.executescript(Path("data/schema/011_system_prompt_active.sql").read_text())
        conn.executescript(Path("data/schema/012_view_system_prompt_active.sql").read_text())
        conn.executescript(Path("data/schema/013_model_categories_request.sql").read_text())
        conn.executescript(Path("data/schema/014_model_categories_responses.sql").read_text())
        conn.executescript(Path("data/schema/015_model_categories_summary.sql").read_text())
        conn.executescript(Path("data/schema/016_axe_runs.sql").read_text())
        conn.executescript(Path("data/schema/017_view_model_categories_request.sql").read_text())
        conn.executescript(Path("data/schema/018_view_model_categories_responses.sql").read_text())
        conn.executescript(Path("data/schema/019_view_artifact_paths.sql").read_text())
        conn.close()

        # Mock all dependencies
        mock_models = [
            {
                "id": "test/model-1",
                "name": "Test: Model 1",
                "description": "Test model",
                "context_length": 4096,
                "supported_parameters": ["response_format"],
                "pricing": {"prompt": "0.0000002", "completion": "0.0000003"},  # $0.50/M total
                "created": 1234567890
            }
        ]

        with patch('aimac.collector.fetch_top_models') as mock_fetch:
            mock_fetch.return_value = mock_models

            with patch('aimac.database._core.get_connection') as mock_get_conn:
                # Return a fresh connection per call so functions that
                # own-and-close connections don't break subsequent calls
                mock_get_conn.side_effect = lambda: sqlite3.connect(db_path)

                with patch('aimac.collector._execute_and_complete_batch',
                           return_value={"failed": 0, "screenshot_failed": 0}):
                    with patch.dict('os.environ', {'AIMAC_DATA_DIR': tmpdir}):
                        # Run collect
                        result = collect_command()

                        assert result == 0  # Success

                        # Verify model was inserted
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM models")
                        count = cursor.fetchone()[0]
                        assert count == 1

                        cursor.execute("SELECT id, name FROM models")
                        row = cursor.fetchone()
                        assert row[0] == "test/model-1"
                        assert row[1] == "Test: Model 1"
                        conn.close()

                        # Verify snapshot file was created
                        snapshot_dir = Path(tmpdir) / "snapshots" / "models"
                        json_files = list(snapshot_dir.glob("*.json"))
                        assert len(json_files) == 1
