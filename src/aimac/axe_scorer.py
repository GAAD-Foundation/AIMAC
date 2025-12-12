"""Axe-core scoring logic with logarithmic dampening for duplicate violations.

Counts only WCAG 2.2 violations that matter for AA conformance: "critical" and
"serious". Moderate/Minor are excluded from counts and scoring.

The dampening formula prevents a single rule with many violations (e.g., 50
color-contrast failures) from dominating the score. Instead of linear scaling,
each additional violation contributes less: base * (1 + k * log2(count)).

See also:
- src/aimac/screenshotter.py - calls score_axe_results() after axe-core analysis
- src/aimac/database/_axe.py - persists the returned AxeScore to database
"""

from __future__ import annotations

import math
from typing import TypedDict


class AxeScore(TypedDict):
    """Return type for score_axe_results().

    Attributes:
        total_violations: Count of critical + serious nodes (moderate/minor excluded).
        critical_violations: Complete barriers (e.g., missing alt text, no focus indicator).
        serious_violations: Significant barriers (e.g., insufficient contrast, missing labels).
        weighted_score: Dampened score where lower is better; 0.0 = perfect accessibility.
    """

    total_violations: int
    critical_violations: int
    serious_violations: int
    weighted_score: float


# Base weights reflect severity impact on end users.
# Critical = complete barriers (can't proceed), Serious = significant obstacles.
# Research: https://github.com/dequelabs/axe-core/issues/2798
CRITICAL_WEIGHT = 5.0
SERIOUS_WEIGHT = 2.0

# Dampening factors for logarithmic scaling of duplicate violations.
# Higher k = less dampening = duplicates count more toward score.
CRITICAL_DAMPENING = 0.75
SERIOUS_DAMPENING = 0.50
COLOR_CONTRAST_DAMPENING = 0.33  # Most common violation, heavily dampened


def score_axe_results(axe_json: dict) -> AxeScore:
    """Score axe-core results using weighted severity with logarithmic dampening.

    Only counts/scores violations with impact in {"critical", "serious"}.
    Moderate and minor violations are excluded from counts and scoring.

    Scoring uses severity-aware log2 dampening per rule:
      - 1 node: base_weight
      - N nodes: base_weight * (1 + k * log2(N))
      where k=0.75 for critical, k=0.50 for serious, k=0.33 for color-contrast.

    Args:
        axe_json: Raw JSON output from axe-core analysis containing violations array.

    Returns:
        AxeScore dictionary with counts and a weighted_score (lower is better).
    """
    violations = axe_json.get("violations", []) or []

    critical_nodes = 0
    serious_nodes = 0
    total_score = 0.0

    for v in violations:
        impact = (v.get("impact") or "").lower()
        nodes = v.get("nodes", []) or []
        count = len(nodes)
        if count <= 0:
            continue

        rule_id = (v.get("id") or "").lower()

        if impact == "critical":
            base = CRITICAL_WEIGHT
            k = CRITICAL_DAMPENING
            critical_nodes += count
        elif impact == "serious":
            base = SERIOUS_WEIGHT
            k = SERIOUS_DAMPENING
            serious_nodes += count
        else:
            # Ignore moderate/minor and anything else
            continue

        # Rule-specific dampening override for color-contrast
        if rule_id == "color-contrast":
            k = COLOR_CONTRAST_DAMPENING

        # Apply logarithmic dampening for duplicates (severity-aware)
        score = base if count == 1 else base * (1 + (math.log2(count) * k))
        total_score += score

    return {
        "total_violations": critical_nodes + serious_nodes,
        "critical_violations": critical_nodes,
        "serious_violations": serious_nodes,
        "weighted_score": float(total_score),
    }
