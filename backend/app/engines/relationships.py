"""Cross-sheet / multi-dataset key detection.

The platform analyses one table at a time today, but the architecture is built
so several datasets can be joined later. This module detects candidate keys
shared between tables and estimates how well they overlap.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.engines import profiler as P


def _candidate_keys(df: pd.DataFrame, profile: dict[str, Any]) -> list[str]:
    keys = []
    for column in profile["columns"]:
        if column["role"] in {P.IDENTIFIER_ROLE, P.DIMENSION} and column["unique"] > 1:
            keys.append(column["name"])
    return keys


def detect_relationships(
    frames: dict[str, pd.DataFrame], profiles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    names = list(frames)
    relationships: list[dict[str, Any]] = []
    for i, left_name in enumerate(names):
        for right_name in names[i + 1:]:
            left, right = frames[left_name], frames[right_name]
            left_keys = _candidate_keys(left, profiles[left_name])
            right_keys = _candidate_keys(right, profiles[right_name])
            for key in set(left_keys) & set(right_keys):
                left_values = set(left[key].dropna().astype(str).unique()[:50_000])
                right_values = set(right[key].dropna().astype(str).unique()[:50_000])
                if not left_values or not right_values:
                    continue
                overlap = left_values & right_values
                if not overlap:
                    continue
                coverage_left = len(overlap) / len(left_values) * 100
                coverage_right = len(overlap) / len(right_values) * 100
                if max(coverage_left, coverage_right) < 40:
                    continue
                left_unique = left[key].is_unique
                right_unique = right[key].is_unique
                if left_unique and right_unique:
                    cardinality = "one-to-one"
                elif left_unique:
                    cardinality = "one-to-many"
                elif right_unique:
                    cardinality = "many-to-one"
                else:
                    cardinality = "many-to-many"
                relationships.append(
                    {
                        "left": left_name,
                        "right": right_name,
                        "key": key,
                        "overlap_values": len(overlap),
                        "coverage_left_pct": round(coverage_left, 1),
                        "coverage_right_pct": round(coverage_right, 1),
                        "cardinality": cardinality,
                        "narrative": (
                            f"{key} appears in both {left_name} and {right_name} with "
                            f"{len(overlap):,} shared value(s) - a possible {cardinality} "
                            f"relationship."
                        ),
                        "join_ready": max(coverage_left, coverage_right) >= 70,
                    }
                )
    relationships.sort(key=lambda r: -max(r["coverage_left_pct"], r["coverage_right_pct"]))
    return relationships
