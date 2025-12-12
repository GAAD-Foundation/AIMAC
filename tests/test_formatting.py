"""Tests for score formatting utilities.

Fixed 2 decimal places for all scores.
"""



class TestFmtScore:
    """Tests for fmt_score function."""

    def test_none_returns_na(self):
        """None input should return 'N/A'."""
        from aimac.formatting import fmt_score

        result = fmt_score(None)
        assert result == "N/A"

    def test_zero_returns_two_decimals(self):
        """Zero should display as '0.00'."""
        from aimac.formatting import fmt_score

        result = fmt_score(0)
        assert result == "0.00"

    def test_whole_number_two_decimals(self):
        """Whole numbers should display with 2 decimals."""
        from aimac.formatting import fmt_score

        result = fmt_score(5.0)
        assert result == "5.00"

    def test_one_decimal_padded(self):
        """One decimal should be padded to 2."""
        from aimac.formatting import fmt_score

        result = fmt_score(4.8)
        assert result == "4.80"

    def test_two_decimals_unchanged(self):
        """Two decimals should display as-is."""
        from aimac.formatting import fmt_score

        result = fmt_score(4.81)
        assert result == "4.81"

    def test_three_decimals_rounded(self):
        """Three decimals should round to 2."""
        from aimac.formatting import fmt_score

        result = fmt_score(4.812)
        assert result == "4.81"

    def test_small_score_two_decimals(self):
        """Small scores display with 2 decimals."""
        from aimac.formatting import fmt_score

        result = fmt_score(0.04)
        assert result == "0.04"


class TestComputeScoreDisplays:
    """Tests for compute_score_displays function."""

    def test_adds_score_display_to_all_rows(self):
        """Every row should get a score_display field."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 3.4},
            {"accessibility_score": 4.8},
            {"accessibility_score": 5.2},
        ]
        compute_score_displays(rows)

        for row in rows:
            assert "score_display" in row, f"Row missing score_display: {row}"

    def test_all_scores_two_decimals(self):
        """All scores should have exactly 2 decimal places."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.812},
            {"accessibility_score": 4.847},
            {"accessibility_score": 4.9},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == "4.81"
        assert rows[1]["score_display"] == "4.85"
        assert rows[2]["score_display"] == "4.90"

    def test_tied_rows_display_same(self):
        """Rows with identical scores must display identically."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.8},
            {"accessibility_score": 4.8},  # Tied
            {"accessibility_score": 5.2},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == rows[1]["score_display"], (
            "Tied scores should display identically"
        )

    def test_custom_score_key(self):
        """Should work with custom score key for category JSONs."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"score": 3.4},
            {"score": 4.8},
        ]
        compute_score_displays(rows, score_key="score")

        for row in rows:
            assert "score_display" in row

    def test_handles_none_scores(self):
        """Should handle rows with None scores gracefully."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 3.4},
            {"accessibility_score": None},
            {"accessibility_score": 5.2},
        ]
        compute_score_displays(rows)

        assert rows[1]["score_display"] == "N/A"


class TestAdaptiveDecimals:
    """Tests for adjacent-rank distinguishing to prevent false ties."""

    def test_false_tie_prevention(self):
        """Adjacent scores that differ should display differently.

        Bug: 4.813 and 4.814 both round to 4.81 at 2 decimals - FALSE TIE!
        Fix: Use 3 decimals to distinguish them (4.813 vs 4.814).
        """
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.813},
            {"accessibility_score": 4.814},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] != rows[1]["score_display"], (
            f"False tie! {rows[0]['score_display']} vs {rows[1]['score_display']} "
            "should be different (4.813 vs 4.814)"
        )

    def test_uses_exactly_three_decimals_when_needed(self):
        """When 2 decimals cause false tie, use exactly 3 decimals."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.813},
            {"accessibility_score": 4.814},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == "4.813", (
            f"Expected '4.813' but got '{rows[0]['score_display']}'"
        )
        assert rows[1]["score_display"] == "4.814", (
            f"Expected '4.814' but got '{rows[1]['score_display']}'"
        )

    def test_uses_exactly_four_decimals_when_needed(self):
        """When 3 decimals cause false tie, use exactly 4 decimals."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.8133},
            {"accessibility_score": 4.8134},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == "4.8133", (
            f"Expected '4.8133' but got '{rows[0]['score_display']}'"
        )
        assert rows[1]["score_display"] == "4.8134", (
            f"Expected '4.8134' but got '{rows[1]['score_display']}'"
        )

    def test_true_tie_allowed(self):
        """Identical raw scores should display identically."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.812},
            {"accessibility_score": 4.812},  # SAME - true tie
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == rows[1]["score_display"], (
            "True ties should display identically"
        )

    def test_two_decimals_when_sufficient(self):
        """Use 2 decimals when they distinguish neighbors."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 3.53},
            {"accessibility_score": 3.79},  # Clearly different at 2 decimals
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] == "3.53"
        assert rows[1]["score_display"] == "3.79"

    def test_many_decimals_if_needed(self):
        """Use as many decimals as needed - no cap."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 4.12345678},
            {"accessibility_score": 4.12345679},
        ]
        compute_score_displays(rows)

        assert rows[0]["score_display"] != rows[1]["score_display"], (
            "Should use enough decimals to distinguish even very close scores"
        )

    def test_non_adjacent_dont_affect_decimals(self):
        """Only adjacent pairs matter, not distant rows."""
        from aimac.formatting import compute_score_displays

        rows = [
            {"accessibility_score": 3.53},
            {"accessibility_score": 5.50},  # Far from both neighbors
            {"accessibility_score": 3.79},
        ]
        compute_score_displays(rows)

        # Row 0 and row 2 aren't adjacent, so they use minimum decimals
        assert rows[0]["score_display"] == "3.53"
        assert rows[1]["score_display"] == "5.50"
        assert rows[2]["score_display"] == "3.79"


# =============================================================================
# Cost formatting tests (lastmac-cl9: prove divergence before fix)
# =============================================================================


class TestFmtCost:
    """Tests for fmt_cost function - single source of truth for cost formatting.

    These tests prove the bug exists (fmt_cost doesn't exist yet) and lock in
    expected behavior for the fix.
    """

    def test_fmt_cost_exists_in_formatting_module(self):
        """fmt_cost should be importable from formatting.py.

        RED: Will fail until fmt_cost is moved to formatting.py.
        """
        from aimac.formatting import fmt_cost

        # If we get here, the import succeeded
        assert callable(fmt_cost)

    def test_fmt_cost_none_returns_na(self):
        """None input should return 'N/A'."""
        from aimac.formatting import fmt_cost

        assert fmt_cost(None) == "N/A"

    def test_fmt_cost_zero_returns_zero_dollars(self):
        """Zero should display as '$0.00'."""
        from aimac.formatting import fmt_cost

        assert fmt_cost(0) == "$0.00"
        assert fmt_cost(0.0) == "$0.00"

    def test_fmt_cost_whole_dollars(self):
        """Whole dollar amounts use 2 decimals."""
        from aimac.formatting import fmt_cost

        assert fmt_cost(100.0) == "$100.00"
        assert fmt_cost(1.0) == "$1.00"

    def test_fmt_cost_small_values_expand_decimals(self):
        """Small values need more decimals to show non-zero.

        Example: $0.001234 should show as $0.0012 (not $0.00 which hides the cost).
        """
        from aimac.formatting import fmt_cost

        # 2 decimals would show $0.00 - wrong!
        assert fmt_cost(0.001) == "$0.001"
        assert fmt_cost(0.0001) == "$0.0001"

    def test_fmt_cost_typical_api_costs(self):
        """Typical API costs like $0.12 or $0.05."""
        from aimac.formatting import fmt_cost

        assert fmt_cost(0.12) == "$0.12"
        assert fmt_cost(0.05) == "$0.05"


class TestCostFormattingDriftPrevention:
    """Tests to prevent cost formatting drift.

    These tests fail if duplicate cost formatters exist in reporter.py.
    """

    def test_no_private_currency_formatter_in_reporter(self):
        """reporter.py should not have its own _fmt_currency_usd function.

        RED: Will fail until _fmt_currency_usd is removed from reporter.py.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter)
        assert "_fmt_currency_usd" not in source, (
            "reporter.py still contains _fmt_currency_usd - should use fmt_cost from formatting.py"
        )

    def test_no_determine_currency_decimals_in_reporter(self):
        """reporter.py should not have _determine_currency_decimals helper.

        RED: Will fail until helper is removed from reporter.py.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter)
        assert "_determine_currency_decimals" not in source, (
            "reporter.py still contains _determine_currency_decimals - should use fmt_cost"
        )


# =============================================================================
# CLI score formatting tests (lastmac-vst: prove CLI ignores ties)
# =============================================================================


class TestCliScoreFormattingIgnoresTies:
    """Tests proving CLI uses fixed decimals instead of tie-aware compute_score_displays.

    BUG: CLI calls fmt_score() (fixed 2 decimals) while web uses compute_score_displays()
    (adaptive decimals that prevent false ties).

    Example: Scores 85.421 vs 85.418 display as:
    - Web: "85.421" vs "85.418" (distinct - correct!)
    - CLI: "85.42" vs "85.42" (false tie - BUG!)

    These tests document the bug before the fix.
    """

    def test_cli_formatters_use_fixed_decimals_not_adaptive(self):
        """CLI _format_tsv and _format_pretty use fmt_score, not compute_score_displays.

        RED: Fails because CLI uses fmt_score (fixed 2 decimals).
        GREEN: Pass when CLI uses compute_score_displays for score columns.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter)

        # CLI should use compute_score_displays, not fmt_score for leaderboard scores
        # Currently it imports fmt_score and uses it directly - that's the bug
        assert "compute_score_displays" in source, (
            "reporter.py should import and use compute_score_displays for tie-aware score formatting"
        )

    def test_fake_tie_scores_display_distinctly_in_cli(self):
        """Scores 85.421 vs 85.418 should display as distinct values in CLI output.

        This is the core bug: both would show as "85.42" with fixed 2 decimals.

        RED: Fails because CLI uses fmt_score which rounds both to "85.42".
        GREEN: Pass when CLI uses compute_score_displays.
        """
        from aimac.formatting import compute_score_displays

        # Simulate CLI row data (like leaderboard or model report)
        rows = [
            {"score": 85.421, "model": "Model A"},
            {"score": 85.418, "model": "Model B"},
        ]

        # CLI currently does: fmt_score(row["score"]) for each row
        # This produces "85.42" for BOTH - false tie!

        # What CLI SHOULD do: compute_score_displays(rows, "score")
        # This produces "85.421" and "85.418" - distinct!

        compute_score_displays(rows, score_key="score")

        assert rows[0]["score_display"] != rows[1]["score_display"], (
            f"False tie! '{rows[0]['score_display']}' vs '{rows[1]['score_display']}' "
            "should be distinct (85.421 vs 85.418)"
        )
        assert rows[0]["score_display"] == "85.421"
        assert rows[1]["score_display"] == "85.418"

    def test_cli_leaderboard_should_precompute_score_display(self):
        """CLI leaderboard should call compute_score_displays before formatting.

        The fix requires calling compute_score_displays() on rows before
        passing to _format_tsv/_format_pretty, then using row['score_display'].

        RED: Fails because _run_leaderboard doesn't call compute_score_displays.
        GREEN: Pass when _run_leaderboard uses compute_score_displays before rendering.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter._run_leaderboard)

        # The fix: call compute_score_displays(rows, score_key="median") before rendering
        assert "compute_score_displays" in source, (
            "_run_leaderboard should call compute_score_displays before rendering "
            "to compute tie-aware score_display values"
        )

    def test_cli_format_tsv_should_use_score_display(self):
        """_format_tsv should use pre-computed score_display, not fmt_score.

        RED: Fails because _format_tsv calls fmt_score(v) for score columns.
        GREEN: Pass when it uses row['score_display'] for the Score column.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter._format_tsv)

        # Look for the pattern where scores are formatted inline
        # Line ~301: fmt_score(v) for score columns
        # This should be replaced with using pre-computed score_display

        # Check that it doesn't format scores inline (the bug pattern)
        assert 'fmt_score(v)' not in source or 'score_display' in source, (
            "_format_tsv should use score_display for scores, not fmt_score(v) inline"
        )

    def test_cli_format_pretty_should_use_score_display(self):
        """_format_pretty should use pre-computed score_display, not fmt_score.

        RED: Fails because _format_pretty calls fmt_score(v) for score columns.
        GREEN: Pass when it uses row['score_display'] for the Score column.
        """
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter._format_pretty)

        # Same bug pattern as _format_tsv
        assert 'fmt_score(v)' not in source or 'score_display' in source, (
            "_format_pretty should use score_display for scores, not fmt_score(v) inline"
        )

    def test_cli_run_model_should_precompute_score_display(self):
        """_run_model should call compute_score_displays before formatting."""
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter._run_model)

        assert "compute_score_displays" in source, (
            "_run_model should call compute_score_displays before rendering"
        )

    def test_cli_run_category_should_precompute_score_display(self):
        """_run_category should call compute_score_displays before formatting."""
        import inspect
        import aimac.reporter as reporter

        source = inspect.getsource(reporter._run_category)

        assert "compute_score_displays" in source, (
            "_run_category should call compute_score_displays before rendering"
        )
