"""Propose-and-confirm data cleaning.

Three rules govern this module, and they are the reason it exists as a separate
engine rather than a step inside the parser:

1. **Nothing is ever fixed automatically.** ``propose_fixes`` only describes
   what *could* be corrected, with the exact number of cells involved and real
   before/after examples. Until a person accepts a proposal, nothing changes.
2. **The uploaded file is never modified.** An accepted proposal is stored as a
   *recipe* on the session and replayed onto a copy of the dataframe every time
   it is loaded. The original workbook on disk is byte-for-byte untouched, so
   removing the recipe restores the original analysis exactly.
3. **Every applied fix is auditable.** ``apply_recipe`` returns a record of what
   each step actually changed, which the API attaches to the analysis so a
   reader can always see that the numbers came from cleaned data and how.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.sanitize import neutralize_text

STANDARDIZE_CATEGORIES = "standardize_categories"
PARSE_NUMERIC = "parse_numeric"
PARSE_DATES = "parse_dates"
DROP_DUPLICATE_ROWS = "drop_duplicate_rows"

# Surrounding whitespace is deliberately absent from this catalogue: the parser
# already trims every text cell on the way in, so a "trim spaces" fix could
# never have anything to do. Category standardisation covers what survives it.
FIX_TYPES = {STANDARDIZE_CATEGORIES, PARSE_NUMERIC, PARSE_DATES, DROP_DUPLICATE_ROWS}

MAX_PROPOSALS = 25
_EXAMPLE_LIMIT = 5


def _example(before: Any, after: Any) -> dict[str, str]:
    return {
        "before": neutralize_text(before, 60) if before is not None else "(blank)",
        "after": neutralize_text(after, 60) if after is not None else "(blank)",
    }


# --- proposals --------------------------------------------------------------

def propose_fixes(
    df: pd.DataFrame, profile: dict[str, Any], quality: dict[str, Any],
) -> list[dict[str, Any]]:
    """Describe the corrections this dataset would benefit from.

    Each proposal is self-contained: it carries the parameters that would be
    applied, so accepting one is a matter of storing it, not recomputing it.
    """
    proposals: list[dict[str, Any]] = []
    columns = {c["name"]: c for c in profile["columns"]}
    row_count = max(int(len(df)), 1)

    for issue in quality.get("issues", []):
        column = issue.get("column")
        if issue["type"] == "inconsistent_categories" and column in df.columns:
            proposals.append(_standardize_proposal(df, issue, column))
        elif issue["type"] == "invalid_numeric" and column in df.columns:
            proposals.append(_numeric_proposal(df, issue, column, columns.get(column, {})))
        elif issue["type"] == "invalid_date" and column in df.columns:
            proposals.append(_date_proposal(df, issue, column))
        elif issue["type"] == "duplicate_rows":
            proposals.append(_duplicate_proposal(df, issue, row_count))

    return [p for p in proposals if p and p["rows_affected"] > 0][:MAX_PROPOSALS]


def _standardize_proposal(df: pd.DataFrame, issue: dict[str, Any],
                          column: str) -> dict[str, Any] | None:
    mapping: dict[str, str] = {}
    for group in issue.get("groups", []):
        # Keep the spelling that actually occurs most often - it is the one the
        # people who produced the data treat as correct.
        counts = df[column].astype(str).value_counts()
        variants = [v for v in group["variants"] if v in counts.index] or group["variants"]
        # Most frequent wins; on a tie prefer conventional capitalisation over
        # ALL CAPS or lower case, then alphabetical so the choice is stable.
        canonical = min(
            variants,
            key=lambda v: (-int(counts.get(v, 0)), 0 if str(v).istitle() else 1, str(v)),
        )
        for variant in group["variants"]:
            if variant != canonical:
                mapping[variant] = canonical
    if not mapping:
        return None
    affected = int(df[column].astype(str).isin(mapping).sum())
    examples = [_example(k, v) for k, v in list(mapping.items())[:_EXAMPLE_LIMIT]]
    return {
        "id": f"fix_std_{issue['id']}",
        "type": STANDARDIZE_CATEGORIES,
        "column": column,
        "title": f"Merge {len(mapping)} spelling variant(s) in {column}",
        "description": (
            f"{len(mapping)} value(s) in {column} differ from another value only by case, spacing "
            f"or punctuation. Merging them into the most frequently used spelling makes each real "
            f"category count once."
        ),
        "rationale": issue.get("impact", ""),
        "rows_affected": affected,
        "cells_affected": affected,
        "examples": examples,
        "params": {"mapping": mapping},
        "risk": (
            "Low. Only values that normalise to the same text are merged, and the change is "
            "reversible - the uploaded file is not modified."
        ),
        "data_loss": False,
        "quality_issue_id": issue["id"],
    }


def _numeric_proposal(df: pd.DataFrame, issue: dict[str, Any], column: str,
                      column_profile: dict[str, Any]) -> dict[str, Any] | None:
    series = df[column]
    converted = P.to_numeric_series(series)
    unparseable = int((series.notna() & converted.isna()).sum())
    if unparseable == 0:
        return None
    examples = []
    for value in series[series.notna() & converted.isna()].astype(str).head(_EXAMPLE_LIMIT):
        examples.append(_example(value, None))
    return {
        "id": f"fix_num_{issue['id']}",
        "type": PARSE_NUMERIC,
        "column": column,
        "title": f"Convert {column} to numbers, blanking {unparseable:,} unreadable value(s)",
        "description": (
            f"{column} is analysed as a measure, but {unparseable:,} cell(s) hold text that is not "
            f"a number. Converting the column makes the type explicit and those cells become "
            f"blank, so they are excluded consistently instead of silently."
        ),
        "rationale": issue.get("impact", ""),
        "rows_affected": unparseable,
        "cells_affected": unparseable,
        "examples": examples,
        "params": {},
        "risk": (
            f"Medium. {unparseable:,} value(s) are discarded rather than corrected. Those records "
            f"are already excluded from every calculation on {column}; this makes that visible."
        ),
        "data_loss": True,
        "quality_issue_id": issue["id"],
    }


def _date_proposal(df: pd.DataFrame, issue: dict[str, Any], column: str) -> dict[str, Any] | None:
    series = df[column]
    converted = P.to_datetime_series(series)
    unparseable = int((series.notna() & converted.isna()).sum())
    if unparseable == 0:
        return None
    examples = [
        _example(value, None)
        for value in series[series.notna() & converted.isna()].astype(str).head(_EXAMPLE_LIMIT)
    ]
    return {
        "id": f"fix_date_{issue['id']}",
        "type": PARSE_DATES,
        "column": column,
        "title": f"Convert {column} to dates, blanking {unparseable:,} unreadable value(s)",
        "description": (
            f"{unparseable:,} cell(s) in {column} cannot be read as a date. Converting the column "
            f"makes those blank so every time-based calculation treats them the same way."
        ),
        "rationale": issue.get("impact", ""),
        "rows_affected": unparseable,
        "cells_affected": unparseable,
        "examples": examples,
        "params": {},
        "risk": (
            f"Medium. {unparseable:,} value(s) are discarded rather than corrected. Check the "
            f"examples first - a consistent but unusual date format is better fixed at source."
        ),
        "data_loss": True,
        "quality_issue_id": issue["id"],
    }


def _duplicate_proposal(df: pd.DataFrame, issue: dict[str, Any],
                        row_count: int) -> dict[str, Any] | None:
    duplicated = int(df.duplicated().sum())
    if duplicated == 0:
        return None
    return {
        "id": f"fix_dupes_{issue['id']}",
        "type": DROP_DUPLICATE_ROWS,
        "column": "",
        "title": f"Remove {duplicated:,} fully duplicated row(s)",
        "description": (
            f"{duplicated:,} row(s) repeat another row in every column. Unless the dataset "
            f"legitimately records the same event twice, they inflate every total and count."
        ),
        "rationale": issue.get("impact", ""),
        "rows_affected": duplicated,
        "cells_affected": duplicated * int(df.shape[1]),
        "examples": [],
        "params": {"keep": "first"},
        "risk": (
            "High if repeated rows are meaningful in this dataset - identical transactions on the "
            "same day are not always errors. Totals will fall by "
            f"{duplicated / row_count * 100:.1f}% of records."
        ),
        "data_loss": True,
        "quality_issue_id": issue["id"],
    }


# --- application ------------------------------------------------------------

def validate_recipe(recipe: list[dict[str, Any]]) -> list[str]:
    """Reject anything that is not one of the fixed, parameterised operations."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, step in enumerate(recipe):
        if not isinstance(step, dict):
            errors.append(f"Step {index + 1} is not a fix descriptor.")
            continue
        kind = step.get("type")
        if kind not in FIX_TYPES:
            errors.append(f"Step {index + 1}: unknown fix type '{kind}'.")
            continue
        if kind != DROP_DUPLICATE_ROWS and not step.get("column"):
            errors.append(f"Step {index + 1}: '{kind}' needs a column.")
        if kind == STANDARDIZE_CATEGORIES:
            mapping = (step.get("params") or {}).get("mapping")
            if not isinstance(mapping, dict) or not mapping:
                errors.append(f"Step {index + 1}: no value mapping supplied.")
            elif len(mapping) > 2000:
                errors.append(f"Step {index + 1}: too many mappings (limit 2000).")
        identifier = step.get("id") or f"{kind}:{step.get('column', '')}"
        if identifier in seen:
            errors.append(f"Step {index + 1}: duplicate fix '{identifier}'.")
        seen.add(identifier)
    if len(recipe) > MAX_PROPOSALS:
        errors.append(f"At most {MAX_PROPOSALS} fixes can be applied at once.")
    return errors


def apply_recipe(
    df: pd.DataFrame, recipe: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Replay accepted fixes onto a **copy** of the dataframe.

    Returns the cleaned frame and an audit entry per step describing what it
    actually changed - including steps that turned out to be no-ops, because
    "this fix changed nothing" is itself worth reporting.
    """
    if not recipe:
        return df, []

    working = df.copy()
    audit: list[dict[str, Any]] = []
    for step in recipe:
        kind = step.get("type")
        column = step.get("column") or ""
        params = step.get("params") or {}
        entry: dict[str, Any] = {
            "id": step.get("id", ""), "type": kind, "column": column,
            "title": step.get("title", ""), "applied": False,
            "rows_changed": 0, "cells_changed": 0, "note": "",
        }
        if kind != DROP_DUPLICATE_ROWS and column not in working.columns:
            entry["note"] = f"Skipped: {column} is not present in this dataset."
            audit.append(entry)
            continue

        if kind == STANDARDIZE_CATEGORIES:
            mapping = {str(k): str(v) for k, v in (params.get("mapping") or {}).items()}
            as_text = working[column].astype("string")
            changed = int(as_text.isin(list(mapping)).sum())
            working[column] = as_text.replace(mapping)
            entry.update(applied=True, rows_changed=changed, cells_changed=changed,
                         note=f"{changed:,} value(s) merged into {len(set(mapping.values()))} "
                              f"canonical spelling(s).")
        elif kind == PARSE_NUMERIC:
            before = working[column]
            converted = P.to_numeric_series(before)
            blanked = int((before.notna() & converted.isna()).sum())
            working[column] = converted
            entry.update(applied=True, rows_changed=blanked, cells_changed=blanked,
                         note=f"Converted to numeric; {blanked:,} unreadable value(s) are now blank.")
        elif kind == PARSE_DATES:
            before = working[column]
            converted = P.to_datetime_series(before)
            blanked = int((before.notna() & converted.isna()).sum())
            working[column] = converted
            entry.update(applied=True, rows_changed=blanked, cells_changed=blanked,
                         note=f"Converted to dates; {blanked:,} unreadable value(s) are now blank.")
        elif kind == DROP_DUPLICATE_ROWS:
            before_rows = int(len(working))
            working = working.drop_duplicates(keep=params.get("keep", "first") or "first")
            removed = before_rows - int(len(working))
            entry.update(applied=True, rows_changed=removed,
                         cells_changed=removed * int(working.shape[1]),
                         note=f"{removed:,} duplicated row(s) removed.")
        audit.append(entry)

    return working.reset_index(drop=True), audit


def summarize(audit: list[dict[str, Any]], original_rows: int, cleaned_rows: int) -> dict[str, Any]:
    """A one-glance statement of what cleaning did to this dataset."""
    applied = [a for a in audit if a["applied"]]
    return {
        "applied_count": len(applied),
        "skipped_count": len(audit) - len(applied),
        "rows_before": int(original_rows),
        "rows_after": int(cleaned_rows),
        "rows_removed": int(original_rows - cleaned_rows),
        "cells_changed": int(sum(a["cells_changed"] for a in applied)),
        "steps": audit,
        "statement": (
            "This analysis was calculated from cleaned data: "
            + "; ".join(a["note"] for a in applied if a["note"])
            + ". The uploaded file itself is unchanged."
        ) if applied else "No cleaning fixes are applied to this analysis.",
    }
