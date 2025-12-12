"""Formatting utilities - single source of truth for score and cost display.

All formatted scores and costs should originate here for consistent display
across CLI reports and JSON exports.

Adaptive Decimals: Prevents false ties by using minimum decimals (starting at 2)
needed to distinguish adjacent rows. This ensures different scores never display
identically while keeping most displays clean at 2 decimals.

Example:
    Scores [4.81, 4.812, 4.82] would display as ["4.81", "4.812", "4.82"]
    because 4.81 and 4.812 need 3 decimals to distinguish.

See also:
- src/aimac/reporter.py - CLI reports
"""

from typing import Any


def fmt_score(score: float | None) -> str:
    """Format score with fixed 2 decimal places.

    Args:
        score: The score to format

    Returns:
        Formatted score string (e.g., "4.81", "0.00", "N/A")
    """
    if score is None:
        return "N/A"
    return f"{score:.2f}"


def fmt_cost(value: float | None) -> str:
    """Format cost as dollars with 2-4 decimals as needed.

    Uses minimum decimals to show a non-zero value:
    - $100.00 for whole dollars
    - $0.12 for typical costs
    - $0.001 for very small costs (avoids showing $0.00)

    For extremely small non-zero values (< 0.0001), shows a lower bound:
    - <$0.0001

    Args:
        value: Cost in USD, or None

    Returns:
        Formatted cost string (e.g., "$1.23", "$0.001", "<$0.0001", "N/A")
    """
    if value is None:
        return "N/A"
    f = float(value)
    if f == 0:
        return "$0.00"

    sign = "-" if f < 0 else ""
    f = abs(f)

    # Extremely small non-zero values would otherwise format as $0.00
    if 0 < f < 1e-4:
        return f"{sign}<$0.0001"

    # Use minimum decimals (2-4) to show non-zero
    for d in range(2, 5):
        if round(f, d) > 0:
            return f"{sign}${f:.{d}f}"

    # Fallback (should be unreachable due to above logic)
    return f"{sign}$0.00"


def _decimals_needed(a: float, b: float) -> int:
    """Find minimum decimals (starting at 2) to distinguish two scores.

    Args:
        a: First score
        b: Second score

    Returns:
        Minimum decimal places needed (2-15) to show different values
    """
    if a == b:
        return 2  # Truly equal - use default
    # Float precision limit ~15 digits; go up to 15 decimal places inclusive
    for d in range(2, 16):  # 2..15 inclusive
        if round(a, d) != round(b, d):
            return d
    return 2  # Fallback if somehow identical at all precisions


def compute_score_displays(
    rows: list[dict[str, Any]],
    score_key: str = "accessibility_score",
) -> None:
    """Mutate rows to add score_display with adaptive decimals.

    Uses minimum decimals (starting at 2) needed to distinguish each row
    from its adjacent neighbors. This prevents false ties where different
    raw scores would display identically.

    Args:
        rows: List of row dicts, assumed to be in rank order
        score_key: Key to read raw score from (default: "accessibility_score")

    Side effects:
        Adds "score_display" key to each row dict
    """
    scores = [row.get(score_key) for row in rows]
    n = len(scores)

    for i, row in enumerate(rows):
        score = scores[i]
        if score is None:
            row["score_display"] = "N/A"
            continue

        # Find decimals needed to distinguish from neighbors
        decimals = 2
        if i > 0 and scores[i - 1] is not None:
            decimals = max(decimals, _decimals_needed(score, scores[i - 1]))
        if i < n - 1 and scores[i + 1] is not None:
            decimals = max(decimals, _decimals_needed(score, scores[i + 1]))

        row["score_display"] = f"{score:.{decimals}f}"
