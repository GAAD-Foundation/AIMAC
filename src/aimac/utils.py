"""Shared utility functions for environment parsing and statistics.

Small, reusable helpers that don't belong to any specific module.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
import statistics


def get_env_int(name: str, default: int) -> int:
    """Safely parse an integer from an environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Parsed integer or default
    """
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def compute_percentiles(values: Sequence[float]) -> dict[str, float]:
    """Compute timing percentiles for a list of values.

    Uses a simple nearest-rank-like method:
        index = round(p * (n - 1)) for p in [0, 1]
    where n is the number of values and the index is clamped into [0, n-1].

    This is intentionally simple and stable rather than matching any specific
    statistical package's exact definition.

    Args:
        values: Sequence of timing values in milliseconds (int or float)

    Returns:
        Dict with keys: avg_ms, p50_ms, p90_ms, p95_ms, p99_ms
        Returns all zeros if values sequence is empty.
    """
    if not values:
        return {"avg_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

    # Coerce to floats and sort to handle int/Decimal inputs gracefully
    vals = sorted(float(v) for v in values)
    n = len(vals)

    def pct(p: float) -> float:
        if n == 1:
            return vals[0]
        k = max(0, min(n - 1, int(round(p * (n - 1)))))
        return vals[k]

    avg = statistics.fmean(vals)
    return {
        "avg_ms": round(avg, 2),
        "p50_ms": round(pct(0.50), 2),
        "p90_ms": round(pct(0.90), 2),
        "p95_ms": round(pct(0.95), 2),
        "p99_ms": round(pct(0.99), 2),
    }
