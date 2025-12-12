"""Shared test configuration and fixtures."""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile

# Set matplotlib to headless backend BEFORE any pyplot import.
# This prevents macOS from spawning a GUI window during tests.
# Optional: CLI-only tests don't need matplotlib (only web chart generation does).
try:
    import matplotlib
    matplotlib.use('Agg')
except ImportError:
    pass

import pytest

# Ensure local package imports work without install
SRC_PATH = Path("src").resolve()
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def _force_dummy_api_key(monkeypatch):
    """Ensure tests never rely on host OPENROUTER_API_KEY.

    Provides a harmless placeholder so header building doesn't fail,
    and prevents accidental use of a real API key in test runs.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")


@pytest.fixture(autouse=True)
def _disable_network(monkeypatch):
    """Block all network access during tests.

    - Patches httpx.Client to raise if instantiated (tests should mock it).
    - Patches socket.create_connection to raise if called.
    This avoids accidental real network calls even if mocks are missing.
    """
    import socket

    import httpx

    class _RaisingClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Network disabled: httpx.Client is blocked in tests")

    monkeypatch.setattr(httpx, "Client", _RaisingClient)

    def _raise(*args, **kwargs):  # pragma: no cover - safety shim
        raise RuntimeError("Network disabled: socket.create_connection is blocked in tests")

    monkeypatch.setattr(socket, "create_connection", _raise)


@pytest.fixture(autouse=True)
def _default_data_dir(monkeypatch, tmp_path):
    """Ensure filesystem writes (snapshots) go to a temp directory.

    Tests can override by patching AIMAC_DATA_DIR explicitly within the test.
    """
    monkeypatch.setenv("AIMAC_DATA_DIR", str(tmp_path))


@pytest.fixture
def temp_db():
    """Create a temporary database with schema for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = sqlite3.connect(f.name)
        conn.row_factory = sqlite3.Row

        # Load real schema
        schema_file = Path("data/schema/001_models.sql")
        if schema_file.exists():
            conn.executescript(schema_file.read_text())

        yield conn
        conn.close()


@pytest.fixture
def model_sets_db(tmp_path):
    """Provide a temporary database with the model_sets schema."""
    db_path = tmp_path / "model_sets.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    schema_file = Path("data/schema/004_model_sets.sql")
    if schema_file.exists():
        conn.executescript(schema_file.read_text())

    try:
        # Ensure code under test uses this temp DB path
        os.environ['AIMAC_DATABASE_PATH'] = str(db_path)
        yield conn
    finally:
        conn.close()


@pytest.fixture
def mock_api_response():
    """Standard mock response from OpenRouter API."""
    return {
        "data": [
            {
                "id": "test/model-1",
                "name": "Test: Model 1",
                "description": "Test model for unit tests",
                "context_length": 4096,
                "supported_parameters": ["response_format"],
                "pricing": {"prompt": "0.01", "completion": "0.02"},
                "created": 1234567890,
                "canonical_slug": "test/model-1",
                "hugging_face_id": None
            }
        ]
    }


def load_full_schema(db_path: Path) -> None:
    """Load all schema files from data/schema/ into a database.

    Loads files in numeric order (001_, 002_, etc.) to ensure correct
    dependency ordering (tables before views).

    Enables foreign key constraints so schema integrity is enforced.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        schema_dir = Path("data/schema")
        schema_files = sorted(schema_dir.glob("*.sql"))
        for schema_file in schema_files:
            conn.executescript(schema_file.read_text())
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def full_schema_db(tmp_path):
    """Provide a temporary database with the COMPLETE schema.

    Loads all schema files (001-025+) in order. Use this instead of
    manually listing schema files in each test.

    Usage:
        def test_foo(full_schema_db):
            db_path, conn = full_schema_db
            # Use conn for queries, db_path for patching AIMAC_DATABASE_PATH
    """
    db_path = tmp_path / "full_schema.db"
    load_full_schema(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield db_path, conn
    finally:
        conn.close()
