"""Tests for the Axe accessibility scoring module.

Validates the weighted scoring algorithm that converts Axe violation counts
into a single weighted score. Key behaviors tested:
- Empty violations yield zero score
- Impact-based weights (critical=5.0, serious=2.0)
- Logarithmic dampening for multiple instances of the same rule
- Filtering of moderate/minor violations (only critical/serious counted)
"""

from __future__ import annotations

import math

from aimac.axe_scorer import score_axe_results


def test_score_empty_violations() -> None:
    """Empty violations list should produce all-zero metrics."""
    axe_json = {"violations": []}
    result = score_axe_results(axe_json)
    assert result["total_violations"] == 0
    assert result["critical_violations"] == 0
    assert result["serious_violations"] == 0
    assert result["weighted_score"] == 0.0


def test_score_single_critical() -> None:
    """Single critical violation scores at base weight (5.0)."""
    axe_json = {"violations": [{"id": "image-alt", "impact": "critical", "nodes": [{}]}]}
    result = score_axe_results(axe_json)
    assert result["total_violations"] == 1
    assert result["critical_violations"] == 1
    assert result["serious_violations"] == 0
    assert result["weighted_score"] == 5.0


def test_score_multiple_instances_dampening_color_contrast() -> None:
    """Serious violations apply log2 dampening with 0.33 factor for repeated nodes."""
    axe_json = {"violations": [{"id": "color-contrast", "impact": "serious", "nodes": [{} for _ in range(10)]}]}
    result = score_axe_results(axe_json)
    assert result["total_violations"] == 10
    assert result["serious_violations"] == 10
    # 2.0 * (1 + 0.33 * log2(10)) ~= 4.19
    expected = 2.0 * (1.0 + 0.33 * math.log2(10))
    assert abs(result["weighted_score"] - expected) < 0.2


def test_score_multiple_instances_dampening_critical() -> None:
    """Critical violations apply log2 dampening with 0.75 factor for repeated nodes."""
    axe_json = {"violations": [{"id": "button-name", "impact": "critical", "nodes": [{} for _ in range(10)]}]}
    result = score_axe_results(axe_json)
    assert result["total_violations"] == 10
    assert result["critical_violations"] == 10
    # 5.0 * (1 + 0.75 * log2(10)) ~= 17.46
    expected = 5.0 * (1.0 + 0.75 * math.log2(10))
    assert abs(result["weighted_score"] - expected) < 0.3


def test_moderate_minor_ignored() -> None:
    """Moderate and minor violations are filtered out of scoring entirely."""
    axe_json = {
        "violations": [
            {"id": "rule-critical", "impact": "critical", "nodes": [{}]},
            {"id": "rule-moderate", "impact": "moderate", "nodes": [{}, {}]},
            {"id": "rule-minor", "impact": "minor", "nodes": [{}]},
        ]
    }
    result = score_axe_results(axe_json)
    assert result["total_violations"] == 1
    assert result["critical_violations"] == 1
    assert result["serious_violations"] == 0
    assert result["weighted_score"] == 5.0
    assert result["serious_violations"] == 0
    assert result["weighted_score"] == 5.0

