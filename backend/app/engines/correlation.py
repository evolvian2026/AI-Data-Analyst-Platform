"""Correlation engine.

Pearson for linear strength plus Spearman for monotonic strength; a pair is only
reported when it has enough overlapping observations and is statistically
significant. Every result is labelled with an explicit "correlation is not
causation" caveat.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from app.engines import profiler as P
from app.engines.derived import is_tautological_pair
from app.engines.formatting import safe_float

MIN_OBSERVATIONS = 20


def strength_label(r: float) -> str:
    magnitude = abs(r)
    if magnitude >= 0.8:
        base = "very strong"
    elif magnitude >= 0.6:
        base = "strong"
    elif magnitude >= 0.4:
        base = "moderate"
    elif magnitude >= 0.2:
        base = "weak"
    else:
        return "no meaningful relationship"
    return f"{base} {'positive' if r > 0 else 'negative'}"


def _is_derived_pair(a: str, b: str) -> bool:
    """Suppress trivially self-referential pairs like Revenue vs Total Revenue."""
    left, right = a.lower().replace("_", " "), b.lower().replace("_", " ")
    return left in right or right in left


def analyze_correlations(
    df: pd.DataFrame, profile: dict[str, Any], max_columns: int = 15,
    derived: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    measures = [c["name"] for c in profile["columns"] if c["role"] == P.MEASURE][:max_columns]
    if len(measures) < 2:
        return {"available": False, "reason": "At least two numeric measures are required.",
                "matrix": [], "pairs": [], "columns": []}

    numeric = pd.DataFrame({name: P.to_numeric_series(df[name]) for name in measures})
    usable = [c for c in numeric.columns if numeric[c].notna().sum() >= MIN_OBSERVATIONS
              and numeric[c].nunique() > 2]
    numeric = numeric[usable]
    if len(usable) < 2:
        return {"available": False, "reason": "Not enough numeric variation to correlate.",
                "matrix": [], "pairs": [], "columns": []}

    matrix = numeric.corr(method="pearson", min_periods=MIN_OBSERVATIONS)
    matrix_rows = [
        {
            "column": row,
            **{
                col: safe_float(matrix.at[row, col])
                for col in matrix.columns
            },
        }
        for row in matrix.index
    ]

    pairs: list[dict[str, Any]] = []
    for left, right in combinations(usable, 2):
        joined = numeric[[left, right]].dropna()
        if len(joined) < MIN_OBSERVATIONS:
            continue
        x = joined[left].to_numpy(dtype=float)
        y = joined[right].to_numpy(dtype=float)
        if np.std(x) == 0 or np.std(y) == 0:
            continue
        pearson_r, pearson_p = scipy_stats.pearsonr(x, y)
        spearman_r, _ = scipy_stats.spearmanr(x, y)
        if not np.isfinite(pearson_r):
            continue
        pairs.append(
            {
                "x": left,
                "y": right,
                "pearson_r": safe_float(pearson_r),
                "pearson_p": safe_float(pearson_p),
                "spearman_r": safe_float(spearman_r),
                "r_squared": safe_float(pearson_r ** 2),
                "observations": int(len(joined)),
                "strength": strength_label(float(pearson_r)),
                "significant": bool(pearson_p < 0.05),
                "derived_pair": (
                    _is_derived_pair(left, right)
                    or is_tautological_pair(left, right, derived or [])
                ),
                "narrative": (
                    f"{left} and {right} show a {strength_label(float(pearson_r))} correlation of "
                    f"{pearson_r:.2f} across {len(joined):,} records"
                    + (f" (r² = {pearson_r ** 2:.2f}, p {'<' if pearson_p < 0.001 else '='} "
                       f"{'0.001' if pearson_p < 0.001 else f'{pearson_p:.3f}'})."
                       if pearson_p < 0.05 else ", which is not statistically significant.")
                ),
            }
        )

    pairs.sort(key=lambda p: -abs(p["pearson_r"] or 0))
    meaningful = [
        p for p in pairs
        if p["significant"] and abs(p["pearson_r"] or 0) >= 0.4 and not p["derived_pair"]
    ]
    return {
        "available": True,
        "columns": usable,
        "matrix": matrix_rows,
        "pairs": pairs[:40],
        "meaningful": meaningful[:10],
        "derived_columns": derived or [],
        "caveat": "Correlation measures association only. It does not establish that one variable "
                  "causes the other; both may be driven by a third factor. Pairs where one column "
                  "is calculated from the other are excluded from the reported findings.",
    }
