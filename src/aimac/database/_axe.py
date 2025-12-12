"""Internal. Import from aimac.database.

Axe-core Accessibility Test Results
====================================

Stores axe-core accessibility analysis results for AI-generated HTML pages.
Each successful benchmark request produces one axe_run record containing:

- **Violation counts**: total, critical (complete barriers), serious (significant barriers)
- **Weighted score**: logarithmically-dampened accessibility score (0 = perfect, higher = worse)
- **JSON path**: filesystem location of full axe-core report for detailed analysis
- **Rule breakdown**: per-rule violation counts for aggregate insights (axe_rule_breakdown table)
- **Rule metadata**: help text and URLs for each rule (axe_rules table)

The relationship is 1:1 with model_categories_request - each request has at most one
axe_run. UPSERT semantics ensure idempotency: re-running analysis on the same request
replaces the previous result rather than creating duplicates.

Called by screenshotter.py after generating and analyzing an HTML page.

See also:
- data/schema/016_axe_runs.sql - main axe results table
- data/schema/024_axe_rule_breakdown.sql - per-rule violation counts
- data/schema/025_axe_rules.sql - rule metadata (help text, URLs)
- src/aimac/axe_scorer.py - scoring algorithm (logarithmic dampening)
- src/aimac/screenshotter.py - caller that runs axe-core analysis
"""

from __future__ import annotations

from datetime import datetime
import logging
import sqlite3

import aimac.database._core as _dbc

logger = logging.getLogger(__name__)


def _normalize_help(rule_id: str, help_text: str | None) -> str:
    """Normalize axe rule help text for insights display.

    Axe-core always provides help text (e.g., "Elements must have sufficient
    color contrast"), so the fallback to humanized rule_id ("Color Contrast")
    is defensive and shouldn't trigger in practice.
    """
    text = (help_text or "").strip()
    if text:
        return text
    fallback = rule_id.replace("-", " ").strip()
    return fallback.title() if fallback else rule_id


def _normalize_help_url(help_url: str | None) -> str | None:
    """Normalize help URL: empty/whitespace becomes NULL."""
    text = (help_url or "").strip()
    return text or None


def _upsert_rule_metadata(
    conn: sqlite3.Connection,
    metadata: dict[str, dict[str, str | None]],
    axe_version: str | None,
) -> None:
    """Persist axe rule metadata (help text, URLs) to axe_rules table.

    This enables reporting without re-parsing axe JSON files. Rules are keyed
    by rule_id (e.g., "color-contrast"). On conflict:
    - help/help_url only update if the new value is non-empty (prefer richer data)
    - last_seen_version always updates to track axe-core version drift
    """
    if not metadata:
        return
    cursor = conn.cursor()
    rows: list[tuple[str, str, str | None, str | None, str | None]] = []
    version = (axe_version or "").strip() or None
    for rule_id, data in metadata.items():
        help_text = _normalize_help(rule_id, data.get("help"))
        help_url = _normalize_help_url(data.get("help_url"))
        rows.append((rule_id, help_text, help_url, version, version))

    cursor.executemany(
        """
        INSERT INTO axe_rules (
            rule_id,
            help,
            help_url,
            first_seen_version,
            last_seen_version
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(rule_id) DO UPDATE SET
            help = CASE
                WHEN excluded.help IS NOT NULL AND excluded.help != '' THEN excluded.help
                ELSE axe_rules.help
            END,
            help_url = CASE
                WHEN excluded.help_url IS NOT NULL AND excluded.help_url != '' THEN excluded.help_url
                ELSE axe_rules.help_url
            END,
            last_seen_version = CASE
                WHEN excluded.last_seen_version IS NOT NULL THEN excluded.last_seen_version
                ELSE axe_rules.last_seen_version
            END
        """,
        rows,
    )


def _insert_axe_run(
    conn: sqlite3.Connection,
    *,
    request_pk: int,
    total_violations: int,
    critical_violations: int,
    serious_violations: int,
    weighted_score: float,
    axe_json_path: str,
    rule_breakdown: dict[str, int] | None = None,
    rule_metadata: dict[str, dict[str, str | None]] | None = None,
    axe_version: str | None = None,
) -> int:
    """Insert or update axe run record for a request.

    UPSERT semantics via UNIQUE(model_categories_request_fk_pk) ensure:
    - First run for a request: INSERT new row
    - Re-run for same request: UPDATE existing row (e.g., after re-analysis)

    Also handles related tables:
    - axe_rule_breakdown: DELETE + INSERT (full replacement on re-run)
    - axe_rules: UPSERT metadata only if non-empty (preserve richer data)

    Returns the axe_run PK (fetched explicitly since lastrowid=0 on UPDATE).
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO axe_runs (
            model_categories_request_fk_pk,
            total_violations,
            critical_violations,
            serious_violations,
            weighted_score,
            axe_json_path,
            run_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(model_categories_request_fk_pk) DO UPDATE SET
            total_violations = excluded.total_violations,
            critical_violations = excluded.critical_violations,
            serious_violations = excluded.serious_violations,
            weighted_score = excluded.weighted_score,
            axe_json_path = excluded.axe_json_path,
            run_timestamp = excluded.run_timestamp
        """,
        (
            request_pk,
            total_violations,
            critical_violations,
            serious_violations,
            weighted_score,
            axe_json_path,
            datetime.now().isoformat(),
        ),
    )
    # lastrowid is 0 when ON CONFLICT triggers an update, so fetch pk explicitly.
    axe_run_pk_row = cursor.execute(
        "SELECT pk FROM axe_runs WHERE model_categories_request_fk_pk = ?",
        (request_pk,),
    ).fetchone()
    axe_run_pk = int(axe_run_pk_row[0]) if axe_run_pk_row else 0

    if rule_metadata:
        _upsert_rule_metadata(conn, rule_metadata, axe_version)

    # Always clean up old breakdown rows for idempotency on re-runs.
    # Even if new run has zero violations, stale data must be removed.
    if axe_run_pk:
        cursor.execute(
            "DELETE FROM axe_rule_breakdown WHERE axe_runs_fk_pk = ?",
            (axe_run_pk,)
        )

    # Insert new breakdown only if there are violations
    if rule_breakdown and axe_run_pk:
        breakdown_rows = [
            (axe_run_pk, rule_id, count)
            for rule_id, count in rule_breakdown.items()
        ]
        cursor.executemany(
            """
            INSERT INTO axe_rule_breakdown (
                axe_runs_fk_pk,
                rule_id,
                violation_count
            ) VALUES (?, ?, ?)
            """,
            breakdown_rows
        )

    return axe_run_pk


def insert_axe_run(
    *,
    request_pk: int,
    total_violations: int,
    critical_violations: int,
    serious_violations: int,
    weighted_score: float,
    axe_json_path: str,
    rule_breakdown: dict[str, int] | None = None,
    rule_metadata: dict[str, dict[str, str | None]] | None = None,
    axe_version: str | None = None,
) -> int:
    """Persist axe-core accessibility analysis results for a benchmark request.

    Stores violation counts, weighted score, and JSON path to axe_runs table.
    UPSERT semantics ensure idempotency: re-running analysis on the same request
    replaces previous results. Also handles related tables for rule breakdown
    and metadata.

    Args:
        request_pk: Foreign key to model_categories_request table.
        total_violations: Total number of accessibility violations found.
        critical_violations: Count of critical severity violations (complete barriers).
        serious_violations: Count of serious severity violations (significant barriers).
        weighted_score: Logarithmically-dampened accessibility score (0 = perfect, higher = worse).
        axe_json_path: Filesystem path to full axe-core JSON report.
        rule_breakdown: Per-rule violation counts (rule_id -> count). Inserted into
            axe_rule_breakdown table. Defaults to None.
        rule_metadata: Rule help text and URLs (rule_id -> {help, help_url}). Upserted
            into axe_rules table. Defaults to None.
        axe_version: Axe-core version string for metadata tracking. Defaults to None.

    Returns:
        Primary key of the axe_runs record (newly inserted or updated).
    """
    conn = _dbc.get_connection()
    try:
        pk = _insert_axe_run(
            conn,
            request_pk=request_pk,
            total_violations=total_violations,
            critical_violations=critical_violations,
            serious_violations=serious_violations,
            weighted_score=weighted_score,
            axe_json_path=axe_json_path,
            rule_breakdown=rule_breakdown,
            rule_metadata=rule_metadata,
            axe_version=axe_version,
        )
        conn.commit()
        return pk
    finally:
        conn.close()


def _axe_run_exists(conn: sqlite3.Connection, request_pk: int) -> bool:
    """Check if an axe_runs row exists for the given request PK.

    Used by screenshotter skip fast-path to verify DB state before claiming
    axe_ok=True. Files on disk are not authoritative; DB state must match.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM axe_runs WHERE model_categories_request_fk_pk = ? LIMIT 1",
        (request_pk,),
    )
    return cursor.fetchone() is not None


def axe_run_exists(request_pk: int) -> bool:
    """Check if axe-core analysis results exist for a benchmark request.

    Used by screenshotter skip fast-path to verify DB state before claiming
    axe_ok=True. Files on disk are not authoritative; DB state must match.

    Args:
        request_pk: Foreign key to model_categories_request table.

    Returns:
        True if an axe_runs record exists for the request, False otherwise.
    """
    conn = _dbc.get_connection()
    try:
        return _axe_run_exists(conn, request_pk)
    finally:
        conn.close()
