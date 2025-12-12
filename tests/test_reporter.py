"""Tests for reporter helpers and error handling paths."""

from __future__ import annotations

from argparse import Namespace
import contextlib
from typing import Any

import pytest

from aimac import reporter as rep


def ns(**kw: Any) -> Namespace:
    return Namespace(**kw)


def test_competition_ranks_handles_nones_and_ties() -> None:
    rows = [
        {"model_pk": 1, "median": 0.5, "mean": 0.6, "total_violations": 10, "cost": 0.02},
        {"model_pk": 2, "median": 0.5, "mean": 0.7, "total_violations": 12, "cost": 0.01},
        {"model_pk": 3, "median": None, "mean": None, "total_violations": None, "cost": None},
    ]
    rep._competition_ranks(rows, ("median", "mean", "total_violations", "cost"))
    # First row should rank ahead of second due to lower mean; Nones last
    assert rows[0]["rank"] == 1
    assert rows[1]["rank"] == 2
    assert rows[2]["rank"] == 3


def test_currency_and_score_formatters() -> None:
    # Currency - now uses fmt_cost from formatting.py
    from aimac.formatting import fmt_cost, fmt_score

    assert fmt_cost(None) == "N/A"
    assert fmt_cost(0.0) == "$0.00"
    # Auto decimals for tiny amounts
    assert fmt_cost(0.0004) == "$0.0004"
    # Score - uses fmt_score from formatting.py (2 decimals)
    assert fmt_score(None) == "N/A"
    assert fmt_score(1.234) == "1.23"


def test_emit_table_tsv_and_pretty_basic() -> None:
    from aimac.formatting import compute_score_displays

    header_lines = ["# Header"]
    verbose = False
    cols, _ = rep._leaderboard_columns("tsv", verbose)
    # Minimal projected rows
    base_rows = [
        {"rank": 1, "company": "Acme", "model": "Alpha", "CostRaw": 0.01, "Score": 0.5},
        {"rank": 2, "company": "Beta", "model": "Gamma", "CostRaw": 0.0, "Score": 0.6},
    ]
    # Compute score_display (required by formatters)
    compute_score_displays(base_rows, score_key="Score")
    # Pretty
    out_pretty = rep._emit_table("pretty", header_lines, cols, base_rows, notes=["# note"], currency_decimals=2)
    assert "Rank" in out_pretty and "Model" in out_pretty
    # TSV
    out_tsv = rep._emit_table("tsv", header_lines, cols, base_rows, notes=["# note"], currency_decimals=2)
    assert "\t".join(cols) in out_tsv
    assert "$" in out_tsv


def test_run_leaderboard_navigation_and_verbose(monkeypatch: Any, capsys: Any) -> None:
    # Patch DB layer used within reporter
    fake_conn = object()
    monkeypatch.setattr(rep, "get_connection", lambda: contextlib.nullcontext(fake_conn))

    monkeypatch.setattr(
        "aimac.database._reports.get_active_leaderboard",
        lambda conn: {"pk": 1, "created_at": "2025-10-10 09:28:16", "model_set_id": 1},
    )
    # Two tied rows so rank annotation works
    rows = [
        {
            "rank": 1,
            "model_pk": 1,
            "model_id": "a/b",
            "company": "Acme",
            "model": "M1",
            "median": 0.5,
            "mean": 0.6,
            "total_violations": 10,
            "cost": 0.01,
            "avg_cost_per_page": 0.01,
        },
        {
            "rank": 1,  # tied rank
            "model_pk": 2,
            "model_id": "c/d",
            "company": "Beta",
            "model": "M2",
            "median": 0.5,
            "mean": 0.6,
            "total_violations": 10,
            "cost": 0.01,
            "avg_cost_per_page": 0.01,
        },
    ]
    monkeypatch.setattr("aimac.database._reports.get_leaderboard_rows", lambda conn, pk: [r.copy() for r in rows])

    rc = rep.run_reporting(ns(report_cmd="leaderboard", format="tsv", verbose=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Company" in out and "Violations" in out
    assert "Run next: \"aimac report model 1\"" in out


def test_run_model_ambiguous_and_notfound(monkeypatch: Any, capsys: Any) -> None:
    fake_conn = object()
    monkeypatch.setattr(rep, "get_connection", lambda: contextlib.nullcontext(fake_conn))
    monkeypatch.setattr("aimac.database._reports.get_active_leaderboard", lambda conn: {"pk": 1, "created_at": "2025-10-10 09:28:16"})
    # Minimal leaderboard rows to satisfy ranking (rank now comes from DB)
    monkeypatch.setattr(
        "aimac.database._reports.get_leaderboard_rows",
        lambda conn, pk: [{
            "rank": 1, "model_pk": 1, "model_id": "m/1", "company": "C", "model": "M",
            "median": 0.5, "mean": 0.6, "total_violations": 10, "cost": 0.01,
        }],
    )

    # Ambiguous model query triggers Ambiguous handling with suggestions
    monkeypatch.setattr(
        "aimac.database._reports.fuzzy_find_models",
        lambda conn, q: [
            {"model_pk": 1, "model_id": "x/y", "company": "X", "model": "Y"},
            {"model_pk": 2, "model_id": "x/z", "company": "X", "model": "Z"},
        ],
    )
    rc = rep.run_reporting(ns(report_cmd="model", query="x", format="tsv", verbose=False))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Ambiguous model query" in out
    assert "Matches:" in out
    assert "x/y" in out and "x/z" in out

    # NotFound category query
    monkeypatch.setattr("aimac.database._reports.fuzzy_find_categories", lambda conn, q: [])
    rc2 = rep.run_reporting(ns(report_cmd="category", query="nope", format="tsv", verbose=False))
    assert rc2 == 1
    out2 = capsys.readouterr().out
    assert "Category not found for query" in out2


def test_run_category_disabled_numeric(monkeypatch: Any, capsys: Any) -> None:
    # Numeric query path with disabled category
    fake_conn = object()
    monkeypatch.setattr(rep, "get_connection", lambda: contextlib.nullcontext(fake_conn))
    monkeypatch.setattr("aimac.database._reports.get_active_leaderboard", lambda conn: {"pk": 1, "created_at": "2025-10-10 09:28:16"})
    monkeypatch.setattr(
        "aimac.database._reports.get_category_by_pk",
        lambda conn, pk: {"category_pk": pk, "slug": "adult-content", "enabled": 0, "name": "Adult"},
    )
    rc = rep.run_reporting(ns(report_cmd="category", query="1", format="tsv", verbose=False))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Category 1 is disabled" in out


# =============================================================================
# DATA INTEGRITY INVARIANT TESTS
# =============================================================================
# These tests exist to prevent future "fixes" that add None handling.
# Cost is REQUIRED - see _require_cost() docstring for rationale.
# =============================================================================


def test_require_cost_raises_on_none() -> None:
    """Cost=None must raise IncompleteData, not silently degrade.

    This test guards against future changes that might add fallback handling
    for missing cost. Missing cost invalidates Pareto front analysis and
    indicates an upstream API error that must abort the run.

    See _require_cost() docstring for the full invariant explanation.
    """
    # None cost should raise
    with pytest.raises(rep.IncompleteData, match="Missing cost"):
        rep._require_cost({"cost": None}, "test-category")

    # Missing key should also raise
    with pytest.raises(rep.IncompleteData, match="Missing cost"):
        rep._require_cost({}, "test-category")


def test_require_cost_returns_float_for_valid_values() -> None:
    """Valid cost values should be returned as floats."""
    assert rep._require_cost({"cost": 0.01}, "cat") == 0.01
    assert rep._require_cost({"cost": 0}, "cat") == 0.0
    assert rep._require_cost({"cost": 1.5}, "cat") == 1.5
    # Integer cost should be coerced to float
    assert rep._require_cost({"cost": 1}, "cat") == 1.0
    assert isinstance(rep._require_cost({"cost": 1}, "cat"), float)


def test_run_model_fails_on_missing_cost(monkeypatch: Any, capsys: Any) -> None:
    """_run_model must fail if any category has cost=None.

    This is an integration test ensuring the _require_cost invariant
    is actually enforced in the model report flow.
    """
    fake_conn = object()
    monkeypatch.setattr(rep, "get_connection", lambda: contextlib.nullcontext(fake_conn))
    monkeypatch.setattr(
        "aimac.database._reports.get_active_leaderboard",
        lambda conn: {"pk": 1, "created_at": "2025-10-10 09:28:16", "model_set_id": 1},
    )
    monkeypatch.setattr(
        "aimac.database._reports.get_leaderboard_rows",
        lambda conn, pk: [{
            "rank": 1, "model_pk": 1, "model_id": "test/model", "company": "Test", "model": "Model",
            "median": 0.5, "mean": 0.6, "total_violations": 10, "cost": 0.01,
        }],
    )
    # Single category for simplicity
    monkeypatch.setattr(
        "aimac.database._reports.get_enabled_category_info",
        lambda conn: [{"category_pk": 2, "name": "Shopping", "slug": "shopping"}],
    )
    # Return data with cost=None - this should trigger IncompleteData
    monkeypatch.setattr(
        "aimac.database._reports.latest_success_by_category_for_model",
        lambda conn, model_pk, cat_pks: {
            2: {"weighted_score": 0.5, "total_violations": 5, "cost": None, "provider": "test"}
        },
    )

    rc = rep.run_reporting(ns(report_cmd="model", query="1", format="tsv", verbose=False))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Missing cost" in out
    assert "data integrity error" in out

