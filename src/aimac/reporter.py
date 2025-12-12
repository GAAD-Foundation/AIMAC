"""AIMAC Reporting CLI - leaderboard, model, and category views.

Subcommands under `aimac r`:
- leaderboard: Ranked list of all models by median score
- model <query>: Per-category breakdown for one model (by rank, name, or ID)
- category <query>: Compare all models within one category
- help: Usage examples and tips

Output formats (--format flag or AIMAC_REPORT_FORMAT env var):
- tsv: Tab-separated, screen-reader friendly (default, accessibility-first)
- pretty: Padded columns for visual terminals
- json: Machine-readable for scripts and automation

Design notes:
- TSV default prioritizes accessibility (works with screen readers, grep, cut)
- No ANSI colors or Unicode decorations that break assistive technology
- Fuzzy search for model/category queries (case-insensitive substring match)
- Competition ranking: ties get same rank, next rank skips (1, 1, 3, not 1, 1, 2)

See also:
- src/aimac/cli.py - registers report subcommand
- src/aimac/formatting.py - score formatting helpers
- src/aimac/database/_reports.py - data queries
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import json
import math
import os
import statistics
import sys
from typing import Any

from .database import _reports as R  # Reporter-only queries (caller manages connection)
from .database import get_connection
from .formatting import compute_score_displays, fmt_cost, fmt_score

BRAND = "AIMAC by GAAD Foundation and ServiceNow"

# Column name constants (single source of truth)
COL_RANK = "Rank"
COL_COMPANY = "Company"
COL_MODEL = "Model"
COL_SCORE = "Score"
COL_VIOLATIONS = "Violations"
COL_COST = "Cost"
COL_TOTAL_COST = "Total Cost"
COL_CRITICAL = "Critical"
COL_SERIOUS = "Serious"
COL_CATEGORY = "Category"
COL_SCREENSHOT = "Screenshot"
COL_PROVIDER = "Provider"
COL_CONSISTENCY = "Consistency"
COL_P90 = "P90"


# Custom exceptions for CLI error handling.
# These are caught in run_reporting() to provide user-friendly messages.

class CliError(Exception):
    """Base class for CLI errors that should show a message without traceback."""
    pass


class NotFound(CliError):
    """Model or category not found for the given query."""
    pass


class Ambiguous(CliError):
    """Query matched multiple models/categories - user must be more specific."""
    def __init__(self, message: str, suggestions: list[str]):
        super().__init__(message)
        self.suggestions = suggestions


class IncompleteData(CliError):
    """Model doesn't have complete category coverage (shouldn't happen in production)."""
    pass


def _require_cost(data: dict[str, Any], category_name: str) -> float:
    """Extract and validate cost from category data.

    INVARIANT: Cost is NEVER optional.

    OpenRouter's API contract guarantees cost data when requested correctly.
    Missing cost indicates one of:
    - API misconfiguration (not requesting cost)
    - Upstream failure that wasn't caught
    - Data corruption

    This function intentionally has NO fallback. Do not add one.
    Missing cost invalidates Pareto front analysis and must abort the run.

    Args:
        data: Category run data dict containing 'cost' key
        category_name: Human-readable category name for error messages

    Returns:
        Cost as float (always non-negative)

    Raises:
        IncompleteData: If cost is None or missing
    """
    cost = data.get("cost")
    if cost is None:
        raise IncompleteData(
            f"Missing cost for category '{category_name}'. "
            "This is a data integrity error - OpenRouter should always provide cost. "
            "Check upstream API configuration."
        )
    return float(cost)


# ------------------------
# CLI registration
# ------------------------


def register_cli(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the 'report' (alias 'r') subcommand with argparse.

    Called by cli.py during parser setup. Adds leaderboard, model, category,
    and help subcommands with their respective arguments.
    """
    report = subparsers.add_parser("report", aliases=["r"], help="Reporting commands")
    # Allow global flags before the subcommand, so `aimac r --format tsv` works
    report.add_argument(
        "--format",
        choices=["tsv", "pretty", "json"],
        default=os.environ.get("AIMAC_REPORT_FORMAT", "tsv").lower(),
        help="Output format: tsv (default, accessible), pretty (padded), json (machine)",
    )
    report.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Include severity breakdowns and additional metrics",
    )
    report_sub = report.add_subparsers(dest="report_cmd", help="Report views")

    # Common options
    def _add_common(p: argparse.ArgumentParser) -> None:
        """Add common format and verbose arguments to a subcommand parser.

        Args:
            p: The argparse subcommand parser to add arguments to
        """
        p.add_argument(
            "--format",
            choices=["tsv", "pretty", "json"],
            default=os.environ.get("AIMAC_REPORT_FORMAT", "tsv").lower(),
            help="Output format: tsv (default, accessible), pretty (padded), json (machine)",
        )
        p.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Include severity breakdowns and additional metrics",
        )

    # leaderboard
    p_lb = report_sub.add_parser("leaderboard", help="Show ranked models for a snapshot")
    _add_common(p_lb)

    # model
    p_model = report_sub.add_parser("model", help="Per-model, per-category view")
    p_model.add_argument("query", nargs="?", help="model_id, substring, or 1-based position")
    _add_common(p_model)

    # help (discoverability and examples)
    report_sub.add_parser("help", help="Show reporting examples and flags")

    # category
    p_cat = report_sub.add_parser("category", help="Compare models within a category")
    p_cat.add_argument("query", nargs="?", help="category slug, name, or number (defaults to first enabled)")
    _add_common(p_cat)


def run_reporting(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate report subcommand handler.

    Handles CLI errors gracefully (NotFound, Ambiguous, IncompleteData) with
    user-friendly messages. Unexpected exceptions propagate for debugging.
    """
    if not getattr(args, "report_cmd", None):
        # Default to leaderboard if no subcommand given
        args.report_cmd = "leaderboard"
        # Set default attributes that leaderboard expects
        if not hasattr(args, "format"):
            args.format = "tsv"
        if not hasattr(args, "verbose"):
            args.verbose = False

    try:
        if args.report_cmd == "leaderboard":
            return _run_leaderboard(args)
        if args.report_cmd == "model":
            return _run_model(args)
        if args.report_cmd == "category":
            return _run_category(args)
        if args.report_cmd == "help":
            _print_reporting_help()
            return 0
        print(f"Unknown report subcommand: {args.report_cmd}\n")
        return 1
    except Ambiguous as e:
        print(f"{e}\n")
        if e.suggestions:
            print("Matches:")
            for s in e.suggestions:
                print(f"  - {s}")
            print()
        return 1
    except NotFound as e:
        print(f"{e}\n")
        return 1
    except IncompleteData as e:
        print(f"{e}\n")
        return 1
    # No catch-all: unexpected exceptions should show full traceback for debugging


def _print_reporting_help() -> None:
    """Print help text with usage examples for the report subcommands."""
    msg = (
        "AIMAC Reporting - Quick Reference\n"
        "\n"
        "Common Workflows\n"
        "  aimac r                    View leaderboard (all models ranked)\n"
        "  aimac r model 1            Examine top-ranked model in detail\n"
        "  aimac r category shopping  Compare all models for one category\n"
        "\n"
        "Finding Models (three ways)\n"
        "  aimac r model 1            By rank (1 = best, 2 = second, etc.)\n"
        "  aimac r model gpt          By name (fuzzy search - matches any part)\n"
        "  aimac r model gemini       By name (case-insensitive)\n"
        "\n"
        "Output Formats\n"
        "  aimac r --format tsv         Tab-separated (default, screen-reader friendly)\n"
        "  aimac r --format pretty      Padded columns, easy to read in terminals\n"
        "  aimac r --format json        JSON (for scripts, web, automation)\n"
        "\n"
        "  Set default: AIMAC_REPORT_FORMAT=tsv|pretty|json in .env file\n"
        "\n"
        "Verbose Mode (show all columns)\n"
        "  aimac r -v                 Leaderboard + violations and company\n"
        "  aimac r model 1 -v         Model + severity splits (Critical/Serious/etc.)\n"
        "  aimac r category 5 -v      Category + all severity levels\n"
        "\n"
        "Useful Patterns\n"
        "  aimac r | head -n 10                   Top 10 models only\n"
        "  aimac r -v | grep 'Google'             Filter by company (needs -v)\n"
        "  aimac r --format json | jq '.rows[0]'  Parse top model with jq\n"
        "  aimac r --format pretty > report.txt    Save pretty view to file\n"
        "  aimac r model 2 && aimac r model 3     Compare two models\n"
        "\n"
        "Navigation Hints\n"
        "  Each report suggests a 'Run next:' command to guide exploration.\n"
        "  Follow these to drill down: leaderboard → model → category\n"
    )
    print(msg)


# ------------------------
# Helpers - Ranking & Formatters
# ------------------------


def _competition_ranks(rows: list[dict[str, Any]], key_fields: Sequence[str]) -> None:
    """Apply competition-style ranking: ties get same rank, next rank skips.

    Example: scores [10, 10, 20] become ranks [1, 1, 3], not [1, 1, 2].
    Modifies rows in-place, adding a 'rank' key to each row.
    """
    def key(r: dict[str, Any]) -> tuple:
        # None values sort to the end deterministically
        vals: list[Any] = []
        for k in key_fields:
            v = r.get(k)
            if v is None:
                vals.append(math.inf)
            else:
                vals.append(v)
        # Stable display order within ties via model_pk as a fallback
        vals.append(int(r.get("model_pk", 1 << 30)))
        return tuple(vals)

    rows.sort(key=key)
    prev_tuple: tuple | None = None
    current_rank = 0
    for idx, r in enumerate(rows, start=1):
        t = tuple(r.get(k) if r.get(k) is not None else math.inf for k in key_fields)
        if prev_tuple is None or t != prev_tuple:
            current_rank = idx
            prev_tuple = t
        r["rank"] = current_rank


def _format_tsv(
    header_lines: list[str],
    columns: list[str],
    rows: list[dict[str, Any]],
    notes: list[str],
    metadata: dict[str, Any] | None = None,
    currency_decimals: int | None = 2,
) -> str:
    """Format rows as tab-separated values for accessible output.

    TSV is the default format because it works well with screen readers,
    grep, cut, and other Unix tools.

    Args:
        header_lines: Comment lines to prepend (e.g., "# AIMAC Leaderboard...")
        columns: Column headers in display order
        rows: Data rows as dicts with keys matching columns
        notes: Footer comment lines (e.g., navigation hints)
        metadata: Optional metadata for the header (model_id, category, timestamp)
        currency_decimals: Decimal places for currency (None = auto per value)

    Returns:
        Complete TSV output as a single string with trailing newline
    """
    lines: list[str] = []

    # Single compact metadata line
    if metadata:
        meta_parts = []

        # Context-specific identifier
        if "model_id" in metadata:
            meta_parts.append(f"AIMAC Model: {metadata['model_id']}")
        elif "category" in metadata:
            meta_parts.append(f"AIMAC Category: {metadata['category']}")
        else:
            meta_parts.append("AIMAC Leaderboard")

        # Timestamp
        if "timestamp" in metadata:
            meta_parts.append("generated on " + metadata['timestamp'])

        lines.append("# " + " ".join(meta_parts))

    lines.extend(header_lines)
    lines.append("")
    lines.append("\t".join(columns))
    for r in rows:
        out = []
        for c in columns:
            v = r.get(c)
            if "cost" in c.lower():
                out.append(fmt_cost(r.get("CostRaw")))
            elif "score" in c.lower() or "mean" in c.lower():
                # Use pre-computed score_display (tie-aware adaptive decimals)
                out.append(r["score_display"])
            # Format Consistency (stddev) and P90 to 2 decimals
            elif c in (COL_CONSISTENCY, COL_P90):
                out.append(fmt_score(v))
            else:
                out.append("N/A" if v is None else str(v))
        lines.append("\t".join(out))
    if notes:
        lines.append("")
        lines.extend(notes)
        lines.append("")
    return "\n".join(lines) + "\n"


def _emit_table(
    fmt: str,
    header_lines: list[str],
    columns: list[str],
    rows: list[dict[str, Any]],
    notes: list[str],
    currency_decimals: int | None = 2,
) -> str:
    """Dispatch to the appropriate table formatter (pretty or tsv).

    JSON format is handled separately in each subcommand since it has
    different metadata requirements.

    Args:
        fmt: Output format ("pretty" or "tsv")
        header_lines: Comment lines to prepend
        columns: Column headers in display order
        rows: Data rows as dicts with keys matching columns
        notes: Footer comment lines
        currency_decimals: Decimal places for currency (None = auto per value)

    Returns:
        Formatted table as a string with trailing newline
    """
    if fmt == "pretty":
        return _format_pretty(header_lines, columns, rows, notes, currency_decimals)
    # default to tsv for non-json
    return _format_tsv(header_lines, columns, rows, notes, metadata=None, currency_decimals=currency_decimals)


def _leaderboard_columns(fmt: str, verbose: bool) -> tuple[list[str], str]:
    """Return column list and cost label for leaderboard display.

    Verbose mode adds Company, Violations, Consistency (StdDev), and P90.

    Args:
        fmt: Output format ("tsv", "pretty", or "json")
        verbose: Whether to include additional columns

    Returns:
        Tuple of (column_list, cost_column_label)
    """
    cost_label = COL_TOTAL_COST
    if fmt in ("tsv", "pretty"):
        if verbose:
            cols = [COL_RANK, COL_COMPANY, COL_MODEL, cost_label, COL_VIOLATIONS, COL_SCORE, COL_CONSISTENCY, COL_P90]
        else:
            cols = [COL_RANK, COL_MODEL, cost_label, COL_SCORE]
        return cols, cost_label
    # json branch mirrors same semantic order but formatter ignores these
    if verbose:
        cols = [COL_RANK, COL_COMPANY, COL_MODEL, cost_label, COL_VIOLATIONS, COL_SCORE, COL_CONSISTENCY, COL_P90]
    else:
        cols = [COL_RANK, COL_MODEL, cost_label, COL_SCORE]
    return cols, cost_label


def _leaderboard_notes(verbose: bool, has_ties: bool, top_rank: int | None, fmt: str) -> list[str]:
    """Generate footer notes for leaderboard output.

    Includes score explanation, tie indicators, navigation hints, and format tips.

    Args:
        verbose: Whether verbose mode is enabled
        has_ties: Whether the leaderboard contains any tied ranks
        top_rank: Rank of the top model for navigation hints (None if no models)
        fmt: Output format ("tsv", "pretty", or "json")

    Returns:
        List of comment lines for footer
    """
    notes: list[str] = []
    # Single, consistent score note for all modes
    notes.append("# Score represents the median across 28 categories. Lower is better.")
    notes.append("# Total Cost equals the sum across 28 categories.")
    if verbose:
        notes.append("# Consistency = StdDev across 28 categories; P90 ≈ 90th percentile score (worst typical).")
    if has_ties:
        notes.append("# * next to a rank indicates a tie")
    if top_rank is not None:
        notes.append(f"# Run next: \"aimac report model {top_rank}\"")
    if fmt == "tsv":
        notes.append("# Tip: For aligned columns use --format=pretty or set AIMAC_REPORT_FORMAT=pretty")
    return notes


def _leaderboard_project_rows(
    rows: list[dict[str, Any]], tied_ranks: set[int], verbose: bool, cost_col_label: str
) -> list[dict[str, Any]]:
    """Project leaderboard rows to display columns.

    Transforms raw DB rows into display-ready dicts with formatted values.
    Adds '*' suffix to ranks that are tied. Includes verbose columns when requested.

    Args:
        rows: Raw database rows with rank, company, model, cost, median, etc.
        tied_ranks: Set of rank values that have ties
        verbose: Whether to include additional columns (violations, consistency, p90)
        cost_col_label: Label for the cost column (e.g., "Total Cost")

    Returns:
        List of display-ready row dicts with formatted values
    """
    projected: list[dict[str, Any]] = []
    for r in rows:
        rank_val = int(r.get("rank", 0))
        pr = {
            COL_RANK: f"{rank_val}*" if rank_val in tied_ranks else rank_val,
            COL_COMPANY: r.get("company"),
            COL_MODEL: r.get("model"),
            cost_col_label: fmt_cost(r.get("cost")),
            "CostRaw": r.get("cost"),
            COL_SCORE: r.get("median"),
        }
        if verbose:
            pr[COL_VIOLATIONS] = r.get("total_violations")
            pr[COL_CONSISTENCY] = r.get("stddev")
            pr[COL_P90] = r.get("p90")
        projected.append(pr)
    return projected


def _format_pretty(
    header_lines: list[str],
    columns: list[str],
    rows: list[dict[str, Any]],
    notes: list[str],
    currency_decimals: int | None = 2,
) -> str:
    """Format rows as padded columns for visual terminal display.

    Computes column widths dynamically and left-justifies all values.
    Adds a separator line under the header row.

    Args:
        header_lines: Comment lines to prepend
        columns: Column headers in display order
        rows: Data rows as dicts with keys matching columns
        notes: Footer comment lines
        currency_decimals: Decimal places for currency (None = auto per value)

    Returns:
        Formatted table as a single string with trailing newline
    """
    # Compute column widths
    def cell_str(row: dict[str, Any], col: str) -> str:
        v = row.get(col)
        if "cost" in col.lower():
            return fmt_cost(row.get("CostRaw"))
        if "score" in col.lower() or "mean" in col.lower():
            # Use pre-computed score_display (tie-aware adaptive decimals)
            return row["score_display"]
        # Format Consistency (stddev) and P90 to 2 decimals
        if col in (COL_CONSISTENCY, COL_P90):
            return fmt_score(v)
        return "N/A" if v is None else str(v)

    widths = [len(c) for c in columns]
    for r in rows:
        for i, c in enumerate(columns):
            s = cell_str(r, c)
            if len(s) > widths[i]:
                widths[i] = len(s)

    # Render
    lines: list[str] = []
    lines.extend(header_lines)
    lines.append("")
    header_line = "  ".join(c.ljust(w) for c, w in zip(columns, widths, strict=False))
    lines.append(header_line)
    lines.append("-" * len(header_line))
    for r in rows:
        line = "  ".join(cell_str(r, c).ljust(w) for c, w in zip(columns, widths, strict=False))
        lines.append(line)
    if notes:
        lines.append("")
        lines.extend(notes)
        lines.append("")
    return "\n".join(lines) + "\n"


def _format_json(metadata: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Format metadata and rows as compact JSON for machine consumption.

    Args:
        metadata: Report metadata (leaderboard_id, model_id, created_at, etc.)
        rows: Data rows as dicts

    Returns:
        Compact JSON string with trailing newline
    """
    return json.dumps({"metadata": metadata, "rows": rows}, separators=(",", ":")) + "\n"


def _iso_date(dt: str | None) -> str:
    """Extract date portion from an ISO datetime string (e.g., '2025-10-10').

    Args:
        dt: ISO datetime string from SQLite (e.g., "2025-10-10 14:30:00")

    Returns:
        Date portion as string (e.g., "2025-10-10"), or empty string if None
    """
    if not dt:
        return ""
    # SQLite default format is ISO, keep date part
    # str().split()[0] can't throw - string ops always succeed
    return str(dt).split(" ")[0]


def _human_datetime(dt: str | None) -> str:
    """Return human-friendly datetime like 'October 10, 2025 at 09:28:16'.

    Args:
        dt: ISO datetime string (can contain 'T' or 'Z' separators)

    Returns:
        Human-readable datetime string, or empty string if None, or original
        string if parsing fails
    """
    if not dt:
        return ""
    s = str(dt).strip()
    # Normalize common ISO forms
    s = s.replace("T", " ").replace("Z", "")
    try:
        d = datetime.fromisoformat(s)
        return d.strftime("%B %d, %Y at %H:%M:%S")
    except ValueError:
        return s


# ------------------------
# Subcommand Implementations
# ------------------------


def _require_active_leaderboard(conn) -> dict[str, Any]:
    """Get the active leaderboard or raise NotFound with actionable message.

    Args:
        conn: Database connection

    Returns:
        Active leaderboard dict with pk, created_at, model_set_id, etc.

    Raises:
        NotFound: If no active leaderboard exists (user needs to run 'aimac collect')
    """
    lb = R.get_active_leaderboard(conn)
    if not lb:
        raise NotFound("No active leaderboard. Run 'aimac collect' first.")
    return lb


def _run_leaderboard(args: argparse.Namespace) -> int:
    """Display the ranked leaderboard of all models.

    Shows models sorted by median AIMAC score (lower is better).
    Supports TSV, pretty, and JSON output formats.
    Verbose mode adds Company, Violations, Consistency, and P90 columns.
    """
    with get_connection() as conn:
        lb = _require_active_leaderboard(conn)
        # Rows come pre-sorted by rank from DB (single source of truth)
        rows = R.get_leaderboard_rows(conn, lb["pk"])

        # Project columns for output
        header_lines: list[str] = [f"# AIMAC Leaderboard generated on {_human_datetime(lb['created_at'])}"]

        verbose = bool(getattr(args, "verbose", False))
        cols, cost_label = _leaderboard_columns(args.format, verbose)

        # Compute tied ranks to annotate
        rank_counts: dict[int, int] = {}
        for r in rows:
            rk = int(r.get("rank", 0))
            rank_counts[rk] = rank_counts.get(rk, 0) + 1
        tied_ranks = {rk for rk, cnt in rank_counts.items() if cnt > 1}

        out_rows = _leaderboard_project_rows(rows, tied_ranks, verbose, cost_label)
        # Compute tie-aware score_display for each row (prevents false ties like 85.421 vs 85.418 → "85.42")
        compute_score_displays(out_rows, score_key=COL_SCORE)
        # Adaptive per-row precision in formatters (default=2 → up to 4)
        currency_dp = None  # None => auto per value

        # Navigation tip: top model_id
        top_rank = int(rows[0]["rank"]) if rows else None
        notes = _leaderboard_notes(verbose, bool(tied_ranks), top_rank, args.format)

        # No separate tie note; compact table remains deterministic

        # Output
        if args.format == "tsv":
            sys.stdout.write(_emit_table("tsv", header_lines, cols, out_rows, notes, currency_decimals=currency_dp))
        elif args.format == "json":
            metadata = {"leaderboard_id": lb["pk"], "model_set_id": lb.get("model_set_id"), "created_at": lb["created_at"]}
            json_rows: list[dict[str, Any]] = []
            for r in rows:
                json_rows.append(
                    {
                        "rank": r.get("rank"),
                        "model_id": r["model_id"],
                        "model_name": r["model"],
                        "company": r.get("company"),
                        "median_score": r["median"],
                        "stddev": r.get("stddev"),
                        "p90": r.get("p90"),
                        "violations": r["total_violations"],
                        "cost_usd": r["cost"],
                        "avg_axe_score": r.get("mean"),
                        "avg_cost_per_page": r.get("avg_cost_per_page"),
                        "created_at": r.get("created_at"),
                    }
                )
            sys.stdout.write(_format_json(metadata, json_rows))
        else:  # pretty
            sys.stdout.write(_emit_table("pretty", header_lines, cols, out_rows, notes, currency_decimals=currency_dp))
    return 0


def _run_model(args: argparse.Namespace) -> int:
    """Display per-category breakdown for a single model.

    Model can be specified by rank (1 = best), name substring, or model_id.
    Shows score, violations, and cost for each of the 28 categories.
    Requires complete category coverage - raises IncompleteData if any missing.

    Raises:
        NotFound: Model not found or position out of range
        Ambiguous: Query matches multiple models
        IncompleteData: Model missing category data or cost data
    """
    q = getattr(args, "query", None)
    with get_connection() as conn:
        lb = _require_active_leaderboard(conn)
        # Rows come pre-sorted by rank from DB (single source of truth)
        lb_rows = R.get_leaderboard_rows(conn, lb["pk"])
        # Already sorted by rank; add stable secondary sort by model_pk for ties
        lb_rows_sorted = sorted(lb_rows, key=lambda r: (r["rank"], int(r.get("model_pk", 1 << 30))))

        # Determine selected model
        selected_model = None
        selected_pos = None  # 1-based
        if q is None or q == "" or (isinstance(q, str) and q.isdigit()):
            pos = 1 if q in (None, "") else int(q)
            total = len(lb_rows_sorted)
            if pos < 1 or pos > total:
                raise NotFound(
                    f"Requested model position {pos} is out of range. This leaderboard has {total} models.\n"
                    f"Try 'aimac r leaderboard' to view positions, or 'aimac r model {min(pos, total)}'."
                )
            selected_model = lb_rows_sorted[pos - 1]
            selected_pos = pos
        else:
            matches = R.fuzzy_find_models(conn, q)
            if not matches:
                raise NotFound(f"Model not found for query: {q}")
            if len(matches) > 1:
                raise Ambiguous("Ambiguous model query", [m["model_id"] for m in matches])
            model = matches[0]
            idx = next((i for i, r in enumerate(lb_rows_sorted) if r["model_pk"] == model["model_pk"]), None)
            if idx is None:
                raise NotFound(f"Model {model['model_id']} is not in the active leaderboard snapshot")
            selected_model = lb_rows_sorted[idx]
            selected_pos = idx + 1

        # Per-category rows (must be complete: 28 categories)
        cats = R.get_enabled_category_info(conn)
        cat_pks = [c["category_pk"] for c in cats]
        latest = R.latest_success_by_category_for_model(conn, int(selected_model["model_pk"]), cat_pks)
        if len(latest) != len(cat_pks):
            # Incomplete is an error per spec
            missing = sorted({pk for pk in cat_pks if pk not in latest})
            raise IncompleteData(
                f"Model has incomplete category coverage ({len(latest)}/{len(cat_pks)}). Missing PKs: {missing}"
            )

        # Build rows
        rows: list[dict[str, Any]] = []
        scores: list[float] = []
        total_v = 0
        total_cost = 0.0
        for c in cats:
            d = latest[c["category_pk"]]
            score = d.get("weighted_score")
            viol = d.get("total_violations")
            cost = _require_cost(d, c["name"])  # Raises IncompleteData if missing
            if isinstance(score, (int, float)):
                scores.append(float(score))
            if isinstance(viol, int):
                total_v += int(viol)
            total_cost += cost
            row = {
                COL_PROVIDER: d.get("provider"),
                COL_CATEGORY: c["name"],
                COL_SCORE: score,
                COL_VIOLATIONS: viol,
                COL_COST: fmt_cost(cost),
                "CostRaw": cost,
            }
            if getattr(args, "verbose", False):
                row.update(
                    {
                        COL_CRITICAL: d.get("critical"),
                        COL_SERIOUS: d.get("serious"),
                        COL_SCREENSHOT: d.get("screenshot"),
                    }
                )
            rows.append(row)

        # Summary stats
        med = None
        stddev = None
        p90 = None
        if scores:
            s = sorted(scores)
            n = len(s)
            if n % 2 == 1:
                med = float(s[n // 2])
            else:
                med = (s[n // 2 - 1] + s[n // 2]) / 2.0
            if n > 1:
                stddev = float(statistics.stdev(s))
            # P90 (nearest-rank method) - idx bounded by max/min, can't throw
            idx = max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))
            p90 = float(s[idx])

        # Header and outputs
        # Summary uses default 2 decimals; table uses adaptive per-row
        currency_dp = None  # auto per value for table rows
        avg_cost = total_cost / float(len(cats)) if cats else 0.0
        # Summary split into separate lines; include total cost and use adaptive decimals for currency
        summary_lines = [
            "# Summary:",
            f"# Median AIMAC Score={_num(med)}",
            f"# Consistency (StdDev)={_num(stddev)}",
            f"# P90 Score={_num(p90)}",
            f"# Total Violations={total_v}",
            f"# Total Cost across 28 categories={fmt_cost(total_cost)}",
            f"# Average Cost per Category={fmt_cost(avg_cost)}",
        ]
        # Header and outputs
        # Title + model name (with rank) + generated timestamp
        title_line = f"# AIMAC Model Generated on {_human_datetime(lb['created_at'])}"
        model_name_line = f"# Model: {str(selected_model.get('model') or selected_model.get('model_id'))} (Rank #{int(selected_model.get('rank', 0))})"
        # Best/Worst category by score with tie handling
        score_pairs = [(r[COL_CATEGORY], r[COL_SCORE]) for r in rows if isinstance(r.get(COL_SCORE), (int, float))]
        header_lines = [title_line, model_name_line, ""] + summary_lines
        if score_pairs:
            min_s = min(s for _, s in score_pairs)
            max_s = max(s for _, s in score_pairs)
            best_names = [n for n, s in score_pairs if abs(s - min_s) < 1e-9]
            worst_names = [n for n, s in score_pairs if abs(s - max_s) < 1e-9]
            if len(best_names) > 1:
                header_lines.append(
                    f"# Best Category: tie between {' | '.join(best_names)} (Score {min_s:.1f})"
                )
            else:
                header_lines.append(f"# Best Category: {best_names[0]} (Score {min_s:.1f})")
            if len(worst_names) > 1:
                header_lines.append(
                    f"# Worst Category: tie between {' | '.join(worst_names)} (Score {max_s:.1f})"
                )
            else:
                header_lines.append(f"# Worst Category: {worst_names[0]} (Score {max_s:.1f})")

        # Build notes (2–3 lines max). No score footnote on model view.
        notes: list[str] = []
        if selected_pos is not None and selected_pos < len(lb_rows_sorted):
            notes.append(f"# Run next: \"aimac report model {selected_pos + 1}\"")
        else:
            notes.append("# Run next: \"aimac report category 1\"")

        # Compute tie-aware score_display for each row
        compute_score_displays(rows, score_key=COL_SCORE)

        if args.format == "tsv":
            if getattr(args, "verbose", False):
                cols = [
                    COL_PROVIDER,
                    COL_CATEGORY,
                    COL_COST,
                    COL_VIOLATIONS,
                    COL_CRITICAL,
                    COL_SERIOUS,
                    COL_SCORE,
                    COL_SCREENSHOT,
                ]
            else:
                # Place Cost immediately after Category, then Violations and Score
                cols = [COL_PROVIDER, COL_CATEGORY, COL_COST, COL_VIOLATIONS, COL_SCORE]
            notes.append("# Tip: For aligned columns use --format=pretty or set AIMAC_REPORT_FORMAT=pretty")
            sys.stdout.write(_format_tsv(header_lines, cols, rows, notes, metadata=None, currency_decimals=currency_dp))
        elif args.format == "json":
            metadata = {
                "leaderboard_id": lb["pk"],
                "model_set_id": lb.get("model_set_id"),
                "created_at": lb["created_at"],
                "model_id": selected_model.get("model_id"),
                "model_name": selected_model.get("model"),
                "total_cost_usd": total_cost,
            }
            json_rows: list[dict[str, Any]] = []
            for c in cats:
                d = latest[c["category_pk"]]
                json_rows.append(
                    {
                        "category": c["slug"],
                        "score": d.get("weighted_score"),
                        "violations": d.get("total_violations"),
                        "critical": d.get("critical"),
                        "serious": d.get("serious"),
                        "cost_usd": d.get("cost"),
                        "provider": d.get("provider"),
                        "system_fingerprint": d.get("system_fingerprint"),
                        "screenshot_path": d.get("screenshot"),
                        "html_path": d.get("html_path"),
                    }
                )
            sys.stdout.write(_format_json(metadata, json_rows))
        else:  # pretty
            if getattr(args, "verbose", False):
                cols = [
                    COL_PROVIDER,
                    COL_CATEGORY,
                    COL_COST,
                    COL_VIOLATIONS,
                    COL_CRITICAL,
                    COL_SERIOUS,
                    COL_SCORE,
                    COL_SCREENSHOT,
                ]
            else:
                # Place Cost immediately after Category, then Violations and Score
                cols = [COL_PROVIDER, COL_CATEGORY, COL_COST, COL_VIOLATIONS, COL_SCORE]
            sys.stdout.write(_format_pretty(header_lines, cols, rows, notes, currency_decimals=currency_dp))
    return 0


def _run_category(args: argparse.Namespace) -> int:
    """Compare all models within a single category.

    Category can be specified by pk number, slug, or name substring.
    Defaults to category 2 (category 1 is Adult, permanently disabled).
    Shows each model's score, violations, and cost for that category.

    Raises:
        NotFound: Category not found
        Ambiguous: Query matches multiple categories
    """
    q = args.query
    # Default unspecified category to 2 (category 1 is Adult, permanently disabled)
    if q is None or q == "":
        q = "2"
    with get_connection() as conn:
        lb = _require_active_leaderboard(conn)
        numeric_query = isinstance(q, str) and q.isdigit()
        if numeric_query:
            cat_by_pk = R.get_category_by_pk(conn, int(q))
            if not cat_by_pk:
                raise NotFound(f"Category not found for pk: {q}")
            cat = cat_by_pk
        else:
            matches = R.fuzzy_find_categories(conn, q)
            if not matches:
                raise NotFound(f"Category not found for query: {q}")
            if len(matches) > 1:
                raise Ambiguous("Ambiguous category query", [m["slug"] for m in matches])
            cat = matches[0]

        # Block disabled categories with a clear message (avoid generating or surfacing adult content)
        if int(cat.get("enabled", 0)) == 0:
            next_suggestion = (int(q) + 1) if numeric_query else 2
            print(f"Category {q} is disabled.\nTry a different category (e.g., 'aimac r category {next_suggestion}').\n")
            return 1

        models = R.get_models_for_leaderboard(conn, lb["pk"])  # model_pk, model_id, company, model
        model_pks = [m["model_pk"] for m in models]
        latest = R.latest_success_by_model_for_category(conn, cat["category_pk"], model_pks)

        # Build rows for ranking
        rows: list[dict[str, Any]] = []
        for m in models:
            d = latest.get(m["model_pk"], {})
            row = {
                "model_pk": m["model_pk"],
                COL_MODEL: m["model"],
                COL_COMPANY: m.get("company"),
                COL_SCORE: d.get("weighted_score"),
                COL_VIOLATIONS: d.get("total_violations"),
                COL_COST: fmt_cost(d.get("cost")),
                "CostRaw": d.get("cost"),
                "model_id": m["model_id"],
                COL_PROVIDER: d.get("provider"),
            }
            rows.append(row)

        # Rank by category metrics: score, violations, cost
        _competition_ranks(rows, (COL_SCORE, COL_VIOLATIONS, "CostRaw"))

        # Footer notes (no model nav; only next category when numeric)
        notes: list[str] = []
        rows_sorted = sorted(rows, key=lambda r: (r["rank"], r.get("model_pk", 1 << 30)))
        # Add next-category nav if numeric query
        if numeric_query:
            try:
                n = int(q)
                # Suggest next only if not last enabled category
                enabled_cats = R.get_enabled_category_info(conn)
                last_enabled_pk = enabled_cats[-1]["category_pk"] if enabled_cats else None
                if last_enabled_pk is None or n < int(last_enabled_pk):
                    # best effort: suggest next pk naively
                    notes.append(f"Run next: \"aimac report category {n+1}\"")
            except (TypeError, ValueError):
                pass
        # Footer lines (2-3 lines, commented)
        has_ties = False
        try:
            _ranks = [int(r.get("rank", 0)) for r in rows_sorted]
            has_ties = len(set(_ranks)) != len(_ranks)
        except (TypeError, ValueError):
            has_ties = False

        base_foot = "# Score is the AIMAC weighted score for this category (lower is better)."
        if has_ties:
            base_foot += " * next to a rank indicates a tie."
        footer: list[str] = [base_foot]
        footer.extend([f"# {n}" for n in notes])
        notes = footer

        header_lines = [f"# AIMAC Category: {cat['name']} generated on {_human_datetime(lb['created_at'])}"]

        if args.format == "tsv":
            if getattr(args, "verbose", False):
                cols = [
                    COL_PROVIDER,
                    COL_COMPANY,
                    COL_MODEL,
                    COL_COST,
                    COL_VIOLATIONS,
                    COL_CRITICAL,
                    COL_SERIOUS,
                    COL_SCORE,
                ]
            else:
                cols = [COL_PROVIDER, COL_MODEL, COL_COST, COL_VIOLATIONS, COL_SCORE]
        else:
            if getattr(args, "verbose", False):
                cols = [
                    COL_PROVIDER,
                    COL_COMPANY,
                    COL_MODEL,
                    COL_COST,
                    COL_VIOLATIONS,
                    COL_CRITICAL,
                    COL_SERIOUS,
                    COL_SCORE,
                ]
            else:
                cols = [COL_PROVIDER, COL_MODEL, COL_COST, COL_VIOLATIONS, COL_SCORE]

        # Fill verbose severity splits if requested
        if getattr(args, "verbose", False):
            for r in rows:
                d = latest.get(int(r["model_pk"])) or {}
                r.update(
                    {
                        COL_CRITICAL: d.get("critical"),
                        COL_SERIOUS: d.get("serious"),
                    }
                )

        # Project rows (format cost); no rank/ties display for category
        out_rows: list[dict[str, Any]] = []
        for r in rows_sorted:
            out = {k: r.get(k) for k in cols if k not in (COL_COST,)}
            out[COL_COST] = fmt_cost(r.get("CostRaw"))
            out["CostRaw"] = r.get("CostRaw")
            out_rows.append(out)

        # Compute tie-aware score_display for each row
        compute_score_displays(out_rows, score_key=COL_SCORE)

        # Adaptive per-row precision in formatters
        currency_dp = None

        if args.format == "tsv":
            notes.append("# Tip: For aligned columns use --format=pretty or set AIMAC_REPORT_FORMAT=pretty")
            sys.stdout.write(_format_tsv(header_lines, cols, out_rows, notes, metadata=None, currency_decimals=currency_dp))
        elif args.format == "json":
            metadata = {"leaderboard_id": lb["pk"], "model_set_id": lb.get("model_set_id"), "created_at": lb["created_at"], "category": cat["name"]}
            json_rows: list[dict[str, Any]] = []
            for r in rows_sorted:
                d = latest.get(int(r["model_pk"])) or {}
                json_rows.append(
                    {
                        "model_id": r.get("model_id"),
                        "model_name": r.get(COL_MODEL),
                        "company": r.get(COL_COMPANY),
                        "score": d.get("weighted_score"),
                        "violations": d.get("total_violations"),
                        "critical": d.get("critical"),
                        "serious": d.get("serious"),
                        "cost_usd": d.get("cost"),
                        "provider": d.get("provider"),
                        "system_fingerprint": d.get("system_fingerprint"),
                    }
                )
            sys.stdout.write(_format_json(metadata, json_rows))
        else:  # pretty
            sys.stdout.write(_format_pretty(header_lines, cols, out_rows, notes, currency_decimals=currency_dp))
    return 0


def _num(v: float | None) -> str:
    """Format a number to 2 decimal places, or 'N/A' if None.

    Args:
        v: Numeric value to format

    Returns:
        Formatted string with 2 decimal places, or "N/A" if None
    """
    if v is None:
        return "N/A"
    return f"{float(v):.2f}"


def best_category_slug(rows: list[dict[str, Any]]) -> str:
    """Return the category slug with the lowest (best) AIMAC score.

    Used for highlighting a model's strongest category. Ties are broken
    by row order (first encountered wins).
    """
    if not rows:
        return ""
    # Lowest score best; ties: deterministic by row order
    s = sorted(rows, key=lambda r: (float(r.get("AIMAC Score")) if r.get("AIMAC Score") is not None else math.inf))
    return str(s[0].get("Category"))
