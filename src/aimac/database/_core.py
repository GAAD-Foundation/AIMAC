"""Internal. Import from aimac.database.

Core database initialization, connection management, and paths.

This module provides:
- Path resolution via environment variables (AIMAC_DATABASE_PATH, AIMAC_DATA_DIR)
- Schema file loading with idempotency tracking (_schema_version table)
- Connection factory with consistent pragmas (WAL, foreign keys, busy timeout)

All other database modules depend on get_connection() from here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3

from aimac.utils import get_env_int

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class MigrationError(DatabaseError):
    """Raised when a migration fails to apply."""
    pass


def get_database_path() -> Path:
    """Get the database path from environment or default.

    Uses AIMAC_DATABASE_PATH env var, defaulting to ./data/aimac.db
    (relative to working directory, typically project root).

    Returns:
        Path: Resolved absolute path to the database file.
    """
    db_path = os.getenv('AIMAC_DATABASE_PATH', './data/aimac.db')
    return Path(db_path).resolve()


def get_schema_directory() -> Path:
    """Get the schema directory path.

    Schema files live in {AIMAC_DATA_DIR}/schema/ (default: ./data/schema/).
    Files are named with numeric prefixes (001_*, 002_*) and applied in
    lexicographic order to ensure tables exist before views that reference them.

    Returns:
        Path: Resolved absolute path to the schema directory.
    """
    data_dir = os.getenv('AIMAC_DATA_DIR', './data')
    return Path(data_dir, 'schema').resolve()


def init_database() -> int:
    """Initialize the database and apply schema files.

    Schema loading:
    - SQL files in data/schema/*.sql are applied in lexicographic order
    - Each file is tracked in _schema_version to prevent re-application
    - On failure, the current file's changes are rolled back and MigrationError raised

    Connection pragmas applied:
    - foreign_keys=ON (SQLite default is OFF, which silently ignores FK violations)
    - journal_mode=WAL (allows concurrent readers during writes)
    - synchronous=NORMAL (good durability/performance balance with WAL)
    - busy_timeout from AIMAC_DB_TIMEOUT env var (default 30s)

    Returns:
        int: Number of newly applied schema files (0 if already up-to-date).

    Raises:
        DatabaseError: If database connection fails.
        MigrationError: If a schema file fails to apply.
    """
    db_path = get_database_path()
    schema_dir = get_schema_directory()

    logger.info(f"Initializing database at {db_path}")

    # Ensure the database directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        timeout_s = get_env_int("AIMAC_DB_TIMEOUT", 30)
        conn = sqlite3.connect(str(db_path), timeout=timeout_s)
        conn.row_factory = sqlite3.Row
        # Pragmas for reliability under concurrency
        conn.execute("PRAGMA foreign_keys = ON")  # default OFF in SQLite
        conn.execute(f"PRAGMA busy_timeout = {int(timeout_s * 1000)}")
        # WAL allows concurrent readers and a single writer; better for our workload
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            # Non-fatal if platform/filesystem disallows; proceed with default
            logger.warning("Failed to enable WAL; continuing with default journal mode")
        cursor = conn.cursor()

        # Create schema tracking table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                version_number INTEGER,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum TEXT
            )
            """
        )

        # Find already applied schema files
        cursor.execute("SELECT filename FROM _schema_version ORDER BY filename")
        applied_schemas = {row['filename'] for row in cursor.fetchall()}

        if not schema_dir.exists():
            logger.warning(f"Schema directory does not exist: {schema_dir}")
            conn.commit()
            conn.close()
            return 0

        schema_files = sorted([f for f in schema_dir.glob('*.sql') if f.is_file()])

        applied_count = 0
        for schema_file in schema_files:
            filename = schema_file.name
            if filename in applied_schemas:
                continue

            try:
                sql_content = schema_file.read_text()
                version_number = int(filename[:3]) if filename[:3].isdigit() else None
                cursor.executescript(sql_content)
                cursor.execute(
                    "INSERT INTO _schema_version (filename, version_number) VALUES (?, ?)",
                    (filename, version_number),
                )
                applied_count += 1
            except sqlite3.Error as e:
                conn.rollback()
                raise MigrationError(
                    f"Failed to apply schema file {filename}: {e!s}"
                ) from e

        conn.commit()
        logger.info(
            f"Database initialization complete. Applied {applied_count} schema files"
        )

    except sqlite3.Error as e:
        raise DatabaseError(f"Database connection failed: {e!s}") from e
    finally:
        if 'conn' in locals():
            conn.close()

    return applied_count


def get_connection() -> sqlite3.Connection:
    """Get a database connection with standard pragmas enabled.

    Returns a new connection each call. Caller is responsible for:
    - Calling conn.commit() to persist changes
    - Calling conn.close() when done (use try/finally pattern)

    Why not a connection pool? SQLite handles concurrency via file locking
    and WAL mode. For our workload (CLI process with occasional concurrent
    reads during async execution), per-call connections are simpler and
    sufficient.

    Raises DatabaseError if the database file doesn't exist.
    """
    db_path = get_database_path()
    if not db_path.exists():
        raise DatabaseError(
            f"Database does not exist at {db_path}. Run 'aimac init' first."
        )
    try:
        timeout_s = get_env_int("AIMAC_DB_TIMEOUT", 30)
        conn = sqlite3.connect(str(db_path), timeout=timeout_s)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(timeout_s * 1000)}")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            logger.debug("WAL not enabled on this connection")
        return conn
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to connect to database: {e!s}") from e


def check_database_exists() -> bool:
    """Check if the database has been initialized.

    Returns:
        bool: True if database file exists, False otherwise.
    """
    return get_database_path().exists()
