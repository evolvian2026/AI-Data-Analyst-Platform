"""Detection of columns that are arithmetic combinations of other columns.

A dataset that carries both Revenue, Cost and Profit contains a column that is
not independent evidence: reporting "Revenue and Profit are correlated at 0.94"
as a discovery is noise, not insight. The same is true of a Total Score column
that is the mean of three subject scores.

Identifying these relationships lets the engines suppress tautological findings
and explain the structure of the dataset instead.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P

TOLERANCE = 0.005      # 0.5% relative tolerance
MIN_MATCH_RATIO = 0.97  # share of rows that must satisfy the relationship
MAX_MEASURES = 9
SAMPLE_ROWS = 2000


def _close(left: np.ndarray, right: np.ndarray) -> float:
    scale = np.maximum(np.abs(right), 1e-9)
    with np.errstate(invalid="ignore", divide="ignore"):
        matches = np.abs(left - right) / scale <= TOLERANCE
    return float(np.mean(matches))


def detect_derived_columns(df: pd.DataFrame, profile: dict[str, Any]) -> list[dict[str, Any]]:
    measures = [c["name"] for c in profile["columns"] if c["role"] == P.MEASURE][:MAX_MEASURES]
    if len(measures) < 2:
        return []

    frame = pd.DataFrame({name: P.to_numeric_series(df[name]) for name in measures}).dropna()
    if len(frame) < 20:
        return []
    if len(frame) > SAMPLE_ROWS:
        frame = frame.sample(SAMPLE_ROWS, random_state=3)

    arrays = {name: frame[name].to_numpy(dtype=float) for name in measures}
    findings: list[dict[str, Any]] = []
    involved: set[str] = set()

    # Revenue = Cost + Profit and Profit = Revenue - Cost describe one identity.
    # Test the column most likely to be the derived one first so the identity is
    # reported once, in its natural direction.
    for target in sorted(measures, key=lambda name: -_derived_name_score(name)):
        if target in involved:
            continue
        others = [m for m in measures if m != target]
        target_values = arrays[target]
        best: dict[str, Any] | None = None

        for size in (2, 3, 4):
            if len(others) < size:
                continue
            for combo in combinations(others, size):
                stacked = np.vstack([arrays[c] for c in combo])
                for label, candidate, formula in (
                    ("sum", stacked.sum(axis=0), " + ".join(combo)),
                    ("mean", stacked.mean(axis=0), f"({' + '.join(combo)}) ÷ {size}"),
                ):
                    ratio = _close(candidate, target_values)
                    if ratio >= MIN_MATCH_RATIO and (best is None or ratio > best["match_ratio"]):
                        best = {
                            "column": target, "operation": label, "sources": list(combo),
                            "formula": f"{target} = {formula}", "match_ratio": ratio,
                        }
            if best:
                break

        if not best:
            for left, right in combinations(others, 2):
                for label, candidate, formula in (
                    ("difference", arrays[left] - arrays[right], f"{left} − {right}"),
                    ("difference", arrays[right] - arrays[left], f"{right} − {left}"),
                    ("product", arrays[left] * arrays[right], f"{left} × {right}"),
                ):
                    ratio = _close(candidate, target_values)
                    if ratio >= MIN_MATCH_RATIO and (best is None or ratio > best["match_ratio"]):
                        best = {
                            "column": target, "operation": label, "sources": [left, right],
                            "formula": f"{target} = {formula}", "match_ratio": ratio,
                        }

        if best:
            best["match_ratio"] = round(best["match_ratio"], 4)
            best["narrative"] = (
                f"{best['column']} is the {best['operation']} of "
                f"{', '.join(best['sources'])} in {best['match_ratio'] * 100:.0f}% of records "
                f"({best['formula']}), so it carries no information those columns do not."
            )
            findings.append(best)
            involved.add(target)
            involved.update(best["sources"])

    return findings


_DERIVED_NAME_HINTS = (
    "total", "net", "profit", "margin", "variance", "difference", "overall", "grand",
    "balance", "sum", "gross", "aggregate", "final", "result",
)


def _derived_name_score(name: str) -> float:
    lowered = str(name).lower()
    return sum(3.0 for hint in _DERIVED_NAME_HINTS if hint in lowered)


def derived_column_names(findings: list[dict[str, Any]]) -> set[str]:
    return {f["column"] for f in findings}


def is_tautological_pair(left: str, right: str, findings: list[dict[str, Any]]) -> bool:
    """True when one column of the pair is arithmetically built from the other."""
    for finding in findings:
        if finding["column"] == left and right in finding["sources"]:
            return True
        if finding["column"] == right and left in finding["sources"]:
            return True
    return False
