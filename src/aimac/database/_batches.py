"""Internal. Import from aimac.database.

Batch lifecycle helpers.

A batch represents a single `aimac collect` execution. It provides:
- A unique identifier (pk) for grouping related requests/responses
- Date/time stamps for organizing output files
- Timing metadata (started_at, completed_at) for performance tracking

Output files are organized as:
output/{batch_date}/{batch_time}/batch_{pk}/{company}/{model}/{category}/...
"""

from __future__ import annotations

from datetime import datetime
import sqlite3

import aimac.database._core as _dbc


def _create_batch(conn: sqlite3.Connection) -> int:
    """Create a new batch row and return its PK.

    batch_date and batch_time are stored as integers (YYYYMMDD, HHMMSS)
    for easy sorting and use in directory paths without separators.

    Args:
        conn: Active SQLite database connection.

    Returns:
        The primary key (pk) of the newly created batch row.
    """
    now = datetime.now()
    batch_date = int(now.strftime("%Y%m%d"))
    batch_time = int(now.strftime("%H%M%S"))
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO batches (batch_date, batch_time, started_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
        (batch_date, batch_time),
    )
    return int(cursor.lastrowid)


def create_batch() -> int:
    """Create a new batch with current timestamp and return its primary key.

    This is the main entry point for starting a new collection batch.
    Opens a connection, creates the batch record, commits, and closes.

    Returns:
        The primary key (pk) of the newly created batch, used to associate
        requests/responses with this execution.
    """
    conn = _dbc.get_connection()
    try:
        pk = _create_batch(conn)
        conn.commit()
        return pk
    finally:
        conn.close()


def _mark_batch_completed(conn: sqlite3.Connection, batch_pk: int) -> None:
    """Set completed_at to CURRENT_TIMESTAMP for the batch.

    Args:
        conn: Active SQLite database connection.
        batch_pk: Primary key of the batch to mark as completed.
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE batches SET completed_at = CURRENT_TIMESTAMP WHERE pk = ?",
        (batch_pk,),
    )


def mark_batch_completed(batch_pk: int) -> None:
    """Mark a batch as completed by setting its completion timestamp.

    This should be called when all collection work for a batch is finished.
    Opens a connection, updates the batch record, commits, and closes.

    Args:
        batch_pk: Primary key of the batch to mark as completed.
    """
    conn = _dbc.get_connection()
    try:
        _mark_batch_completed(conn, batch_pk)
        conn.commit()
    finally:
        conn.close()
