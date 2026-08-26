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


# --- acting on a detected relationship --------------------------------------

JOIN_KINDS = {"inner", "left", "right", "outer"}
# A many-to-many join multiplies rows. Beyond this multiple of the larger input
# the result is a cartesian artefact, not a dataset anyone meant to analyse.
MAX_FANOUT = 4.0


class JoinError(ValueError):
    """A join that cannot be performed, with a reason a user can act on."""


def describe_join(
    frames: dict[str, pd.DataFrame], left_name: str, right_name: str, key: str,
    how: str = "inner",
) -> dict[str, Any]:
    """Everything about a join except the joined table itself.

    Called before a join is run so the cost and the losses are stated up front:
    how many rows on each side find a partner, how many are dropped by the
    chosen join type, and whether the key duplicates rows.
    """
    if how not in JOIN_KINDS:
        raise JoinError(f"Unknown join type '{how}'. Choose one of: {', '.join(sorted(JOIN_KINDS))}.")
    for name in (left_name, right_name):
        if name not in frames:
            raise JoinError(f"'{name}' is not an analysable sheet in this workbook.")
    if left_name == right_name:
        raise JoinError("A sheet cannot be joined to itself.")

    left, right = frames[left_name], frames[right_name]
    if key not in left.columns or key not in right.columns:
        raise JoinError(f"'{key}' is not present in both {left_name} and {right_name}.")

    left_keys = left[key].dropna().astype(str)
    right_keys = right[key].dropna().astype(str)
    left_values, right_values = set(left_keys.unique()), set(right_keys.unique())
    shared = left_values & right_values
    if not shared:
        raise JoinError(
            f"{left_name} and {right_name} share no {key} values, so joining them would "
            f"produce an empty table."
        )

    matched_left = int(left_keys.isin(shared).sum())
    matched_right = int(right_keys.isin(shared).sum())
    left_dupes = left[key].duplicated(keep=False).sum()
    right_dupes = right[key].duplicated(keep=False).sum()

    # Expected result size: for each shared key, rows on the left times rows on
    # the right. Computed on the counts rather than by joining, so an oversized
    # join is refused before any memory is spent on it.
    left_counts = left_keys[left_keys.isin(shared)].value_counts()
    right_counts = right_keys[right_keys.isin(shared)].value_counts()
    matched_product = int((left_counts * right_counts).sum())
    if how in {"left", "outer"}:
        matched_product += int(len(left)) - matched_left
    if how in {"right", "outer"}:
        matched_product += int(len(right)) - matched_right

    largest = max(len(left), len(right), 1)
    fanout = matched_product / largest
    cardinality = (
        "one-to-one" if not left_dupes and not right_dupes
        else "one-to-many" if not left_dupes
        else "many-to-one" if not right_dupes
        else "many-to-many"
    )

    overlapping = sorted((set(left.columns) & set(right.columns)) - {key})
    # In a many-to-one join the lookup side's values are repeated across every
    # matching row. Those columns describe an entity, not an event, so totalling
    # them over the joined table measures how often each entity appears - not
    # anything about the values themselves. They are named here so the analysis
    # can refuse to treat them as additive.
    if cardinality == "many-to-one":
        duplicated = sorted(set(right.columns) - {key})
    elif cardinality == "one-to-many":
        duplicated = sorted(set(left.columns) - {key})
    else:
        duplicated = []
    warnings: list[str] = []
    if cardinality == "many-to-many":
        warnings.append(
            f"{key} repeats on both sides, so this is a many-to-many join: every measure is "
            f"duplicated {fanout:.1f}x and totals calculated from the joined table will be "
            f"inflated. Aggregate one side first if you need correct totals."
        )
    if overlapping:
        warnings.append(
            f"{len(overlapping)} column name(s) exist on both sheets "
            f"({', '.join(overlapping[:5])}); they are suffixed with the sheet name so both "
            f"are kept."
        )
    if duplicated:
        warnings.append(
            f"{len(duplicated)} column(s) from the lookup side are repeated on every matching "
            f"row ({', '.join(duplicated[:4])}). They are averaged rather than totalled, and "
            f"excluded from trends, because totalling a repeated attribute measures how often "
            f"the entity appears rather than anything about the value."
        )
    if how == "inner" and matched_left < len(left):
        warnings.append(
            f"{len(left) - matched_left:,} row(s) of {left_name} have no matching {key} and are "
            f"dropped by an inner join."
        )
    if how == "inner" and matched_right < len(right):
        warnings.append(
            f"{len(right) - matched_right:,} row(s) of {right_name} have no matching {key} and "
            f"are dropped by an inner join."
        )

    return {
        "left": left_name,
        "right": right_name,
        "key": key,
        "how": how,
        "cardinality": cardinality,
        "rows_left": int(len(left)),
        "rows_right": int(len(right)),
        "matched_rows_left": matched_left,
        "matched_rows_right": matched_right,
        "unmatched_rows_left": int(len(left)) - matched_left,
        "unmatched_rows_right": int(len(right)) - matched_right,
        "shared_key_values": len(shared),
        "coverage_left_pct": round(matched_left / max(len(left), 1) * 100, 1),
        "coverage_right_pct": round(matched_right / max(len(right), 1) * 100, 1),
        "estimated_rows": matched_product,
        "fanout": round(fanout, 2),
        "overlapping_columns": overlapping,
        "duplicated_columns": duplicated,
        "warnings": warnings,
        "safe": fanout <= MAX_FANOUT,
        "narrative": (
            f"{how.title()} join of {left_name} to {right_name} on {key} "
            f"({cardinality}) produces about {matched_product:,} row(s)."
        ),
    }


def ensure_joinable(report: dict[str, Any], max_rows: int = 1_000_000) -> None:
    """Raise unless a described join can be analysed honestly.

    Separate from :func:`describe_join` so a *preview* can show an unsafe join
    and explain why, while every path that would actually analyse the result
    refuses it. An analysis whose totals are multiplied by an unintended
    many-to-many fan-out is worse than no analysis at all.
    """
    if report["estimated_rows"] > max_rows:
        raise JoinError(
            f"This join would produce about {report['estimated_rows']:,} rows, above the "
            f"{max_rows:,} row limit. Filter or aggregate one of the sheets first."
        )
    if not report["safe"]:
        raise JoinError(
            f"{report['key']} repeats on both sheets, so this join multiplies rows "
            f"{report['fanout']:.1f}x ({report['estimated_rows']:,} rows from "
            f"{report['rows_left']:,} and {report['rows_right']:,}). Every total calculated "
            f"from the result would be overstated by that factor. Aggregate one sheet to one "
            f"row per {report['key']} first."
        )


def apply_join(
    frames: dict[str, pd.DataFrame], left_name: str, right_name: str, key: str,
    how: str = "inner", max_rows: int = 1_000_000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join two sheets into one analysable table."""
    report = describe_join(frames, left_name, right_name, key, how)
    ensure_joinable(report, max_rows)

    left, right = frames[left_name].copy(), frames[right_name].copy()
    # Join on text so 101 and "101" match, which is the common spreadsheet case.
    left["__join_key__"] = left[key].astype("string")
    right["__join_key__"] = right[key].astype("string")
    right = right.drop(columns=[key])

    joined = left.merge(
        right, on="__join_key__", how=how,
        suffixes=(f" ({left_name})", f" ({right_name})"),
    ).drop(columns=["__join_key__"])

    suffix_map = {c: f"{c} ({right_name})" for c in report["overlapping_columns"]}
    if report["duplicated_columns"]:
        lookup_side = right_name if report["cardinality"] == "many-to-one" else left_name
        report["duplicated_columns"] = [
            f"{c} ({lookup_side})" if c in suffix_map else c
            for c in report["duplicated_columns"]
        ]
    report["rows_result"] = int(len(joined))
    report["columns_result"] = int(joined.shape[1])
    report["narrative"] = (
        f"{how.title()} join of {left_name} to {right_name} on {key} ({report['cardinality']}): "
        f"{len(joined):,} row(s), {joined.shape[1]} column(s)."
    )
    return joined.reset_index(drop=True), report
