"""Data quality engine.

Produces a 0-100 score, the reasoning behind it, concrete issues and - most
importantly - the *analytical impact* of each issue, because "Region has 8.4%
missing values" is far less useful than knowing that regional revenue will be
understated.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import plural, safe_float
from app.engines.sanitize import scan_for_injection

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _grade(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Good"
    if score >= 65:
        return "Fair"
    if score >= 50:
        return "Poor"
    return "Critical"


def _normalise_category(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _inconsistent_categories(series: pd.Series) -> list[dict[str, Any]]:
    groups: dict[str, set[str]] = {}
    for value in series.dropna().astype(str).unique()[:5000]:
        groups.setdefault(_normalise_category(value), set()).add(value)
    return [
        {"canonical": sorted(variants)[0], "variants": sorted(variants)}
        for variants in groups.values()
        if len(variants) > 1
    ]


def assess_quality(
    df: pd.DataFrame,
    profile: dict[str, Any],
    outlier_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_count = int(len(df))
    columns = profile["columns"]
    issues: list[dict[str, Any]] = []
    recommendations: list[str] = []

    total_cells = row_count * max(len(columns), 1)
    missing_cells = int(df.isna().sum().sum())
    missing_pct = (missing_cells / total_cells * 100) if total_cells else 0.0

    # --- missing values -----------------------------------------------------
    for column in columns:
        if column["missing_pct"] <= 0:
            continue
        severity = (
            "critical" if column["missing_pct"] > 50
            else "high" if column["missing_pct"] > 20
            else "medium" if column["missing_pct"] > 5
            else "low"
        )
        impact = _missing_impact(column, row_count)
        issues.append(
            {
                "id": f"dq_missing_{column['position']}",
                "type": "missing_values",
                "column": column["name"],
                "severity": severity,
                "title": f"{column['name']} has {column['missing_pct']:.1f}% missing values",
                "detail": f"{plural(column['missing'], 'record')} of {row_count:,} have no value for "
                          f"{column['name']}.",
                "impact": impact,
                "affected_records": column["missing"],
                "affected_pct": round(column["missing_pct"], 2),
            }
        )

    # --- duplicates ---------------------------------------------------------
    try:
        duplicate_rows = int(df.duplicated().sum())
    except TypeError:  # unhashable cell contents
        duplicate_rows = int(df.astype(str).duplicated().sum())
    if duplicate_rows:
        issues.append(
            {
                "id": "dq_duplicate_rows",
                "type": "duplicate_rows",
                "column": None,
                "severity": "high" if duplicate_rows / max(row_count, 1) > 0.02 else "medium",
                "title": f"{duplicate_rows:,} fully duplicated rows",
                "detail": f"{duplicate_rows:,} rows are exact copies of another row "
                          f"({duplicate_rows / max(row_count, 1) * 100:.1f}% of the dataset).",
                "impact": "Totals, counts and averages are inflated by the repeated rows; "
                          "every aggregate in this report includes them.",
                "affected_records": duplicate_rows,
                "affected_pct": round(duplicate_rows / max(row_count, 1) * 100, 2),
            }
        )

    duplicate_ids: dict[str, int] = {}
    for column in columns:
        if column["role"] != P.IDENTIFIER_ROLE:
            continue
        series = df[column["name"]].dropna()
        dupes = int(series.duplicated().sum())
        if dupes:
            duplicate_ids[column["name"]] = dupes
            issues.append(
                {
                    "id": f"dq_dupid_{column['position']}",
                    "type": "duplicate_identifier",
                    "column": column["name"],
                    "severity": "high",
                    "title": f"{column['name']} repeats {dupes:,} times",
                    "detail": f"{column['name']} looks like a unique key but {dupes:,} values occur "
                              f"more than once.",
                    "impact": "Record-level joins and distinct counts based on this key will "
                              "double count.",
                    "affected_records": dupes,
                    "affected_pct": round(dupes / max(row_count, 1) * 100, 2),
                }
            )

    # --- constant columns ---------------------------------------------------
    constant_columns = [c["name"] for c in columns if c["is_constant"]]
    if constant_columns:
        issues.append(
            {
                "id": "dq_constant",
                "type": "constant_column",
                "column": None,
                "severity": "low",
                "title": f"{len(constant_columns)} column(s) contain a single repeated value",
                "detail": "Constant columns: " + ", ".join(constant_columns[:8]),
                "impact": "These columns carry no analytical signal and are excluded from "
                          "comparisons and correlations.",
                "affected_records": 0,
                "affected_pct": 0.0,
            }
        )

    # --- inconsistent categories -------------------------------------------
    inconsistent_total = 0
    for column in columns:
        if column["role"] != P.DIMENSION or column["unique"] > 2000:
            continue
        groups = _inconsistent_categories(df[column["name"]])
        if not groups:
            continue
        inconsistent_total += len(groups)
        examples = "; ".join("/".join(g["variants"][:3]) for g in groups[:3])
        issues.append(
            {
                "id": f"dq_inconsistent_{column['position']}",
                "type": "inconsistent_categories",
                "column": column["name"],
                "severity": "medium",
                "title": f"{column['name']} has {len(groups)} inconsistent category spelling(s)",
                "detail": f"Values that differ only by case or spacing: {examples}.",
                "impact": f"Group-by results on {column['name']} split one real category across "
                          f"several rows, understating each of them.",
                "affected_records": int(
                    sum(
                        int(df[column["name"]].astype(str).isin(g["variants"]).sum())
                        for g in groups[:20]
                    )
                ),
                "affected_pct": 0.0,
                "groups": groups[:20],
            }
        )
        recommendations.append(
            f"Standardise {len(groups)} inconsistent value(s) in {column['name']} "
            f"(for example {groups[0]['variants'][0]} vs {groups[0]['variants'][1]})."
        )

    # --- conversion problems -----------------------------------------------
    invalid_numeric = 0
    invalid_dates = 0
    for column in columns:
        if column["semantic_type"] in P.NUMERIC_TYPES:
            series = df[column["name"]]
            converted = P.to_numeric_series(series)
            failed = int(series.notna().sum() - converted.notna().sum())
            if failed:
                invalid_numeric += failed
                issues.append(
                    {
                        "id": f"dq_numconv_{column['position']}",
                        "type": "invalid_numeric",
                        "column": column["name"],
                        "severity": "high" if failed / max(row_count, 1) > 0.05 else "medium",
                        "title": f"{failed:,} value(s) in {column['name']} are not numeric",
                        "detail": f"{column['name']} is treated as a measure but {failed:,} cells "
                                  f"could not be converted to a number.",
                        "impact": "Those records are dropped from every calculation involving "
                                  f"{column['name']}, so totals are understated.",
                        "affected_records": failed,
                        "affected_pct": round(failed / max(row_count, 1) * 100, 2),
                    }
                )
        elif column["semantic_type"] in {P.DATE, P.DATETIME}:
            series = df[column["name"]]
            converted = P.to_datetime_series(series)
            failed = int(series.notna().sum() - converted.notna().sum())
            if failed:
                invalid_dates += failed
                issues.append(
                    {
                        "id": f"dq_dateconv_{column['position']}",
                        "type": "invalid_date",
                        "column": column["name"],
                        "severity": "medium",
                        "title": f"{failed:,} invalid date value(s) in {column['name']}",
                        "detail": f"{failed:,} cells in {column['name']} could not be parsed as dates.",
                        "impact": "Those records are excluded from every time-based trend and "
                                  "period comparison.",
                        "affected_records": failed,
                        "affected_pct": round(failed / max(row_count, 1) * 100, 2),
                    }
                )

    # --- suspicious values --------------------------------------------------
    for column in columns:
        if column["semantic_type"] not in P.NUMERIC_TYPES:
            continue
        numeric = P.to_numeric_series(df[column["name"]]).dropna()
        if numeric.empty:
            continue
        zeros = int((numeric == 0).sum())
        if zeros / len(numeric) > 0.4 and len(numeric) > 30:
            issues.append(
                {
                    "id": f"dq_zeros_{column['position']}",
                    "type": "suspicious_values",
                    "column": column["name"],
                    "severity": "low",
                    "title": f"{column['name']} is zero in {zeros / len(numeric) * 100:.0f}% of records",
                    "detail": f"{zeros:,} of {len(numeric):,} values are exactly zero.",
                    "impact": "Averages including these zeros may not represent typical activity; "
                              "consider whether zero means 'none' or 'not recorded'.",
                    "affected_records": zeros,
                    "affected_pct": round(zeros / len(numeric) * 100, 2),
                }
            )
        negatives = int((numeric < 0).sum())
        name_lower = column["name"].lower()
        if negatives and any(k in name_lower for k in ("quantity", "units", "count", "age", "price")):
            issues.append(
                {
                    "id": f"dq_negative_{column['position']}",
                    "type": "suspicious_values",
                    "column": column["name"],
                    "severity": "medium",
                    "title": f"{negatives:,} negative value(s) in {column['name']}",
                    "detail": f"{column['name']} contains {negatives:,} values below zero, which is "
                              f"unusual for this kind of measure.",
                    "impact": "Negative values reduce totals and may indicate returns, corrections "
                              "or data-entry errors.",
                    "affected_records": negatives,
                    "affected_pct": round(negatives / len(numeric) * 100, 2),
                }
            )

    # --- untrusted content --------------------------------------------------
    samples = {
        c["name"]: df[c["name"]].dropna().astype(str).head(400).tolist()
        for c in columns
        if c["semantic_type"] in {P.TEXT, P.CATEGORICAL, P.UNKNOWN}
    }
    injection_findings = scan_for_injection(samples)
    if injection_findings:
        issues.append(
            {
                "id": "dq_injection",
                "type": "untrusted_content",
                "column": injection_findings[0]["column"],
                "severity": "high",
                "title": f"{len(injection_findings)} column(s) contain instruction-like text",
                "detail": "Some cells read like instructions to an AI system rather than data. "
                          "They have been neutralised and are treated strictly as data.",
                "impact": "No effect on the calculations, but review these cells - they may be a "
                          "prompt-injection attempt or simply pasted text.",
                "affected_records": len(injection_findings),
                "affected_pct": 0.0,
                "findings": injection_findings[:10],
            }
        )

    # --- score --------------------------------------------------------------
    components = {
        "completeness": max(0.0, 100.0 - missing_pct * 2.2),
        "uniqueness": max(0.0, 100.0 - (duplicate_rows / max(row_count, 1) * 100) * 4
                          - min(len(duplicate_ids) * 12, 40)),
        "consistency": max(0.0, 100.0 - inconsistent_total * 7),
        "validity": max(0.0, 100.0 - ((invalid_numeric + invalid_dates) / max(row_count, 1) * 100) * 3),
        "structure": max(0.0, 100.0 - len(constant_columns) * 6),
    }
    weights = {"completeness": 0.34, "uniqueness": 0.2, "consistency": 0.18,
               "validity": 0.2, "structure": 0.08}
    score = float(sum(components[k] * weights[k] for k in components))
    score = round(max(0.0, min(100.0, score)), 1)

    outliers = outlier_summary or {}
    if outliers.get("total"):
        issues.append(
            {
                "id": "dq_outliers",
                "type": "outliers",
                "column": None,
                "severity": "low",
                "title": f"{outliers['total']:,} statistical outlier(s) detected",
                "detail": f"Outliers were found in {len(outliers.get('columns', []))} numeric "
                          f"column(s) using the IQR and modified z-score methods.",
                "impact": "Averages and totals are sensitive to these records. The report reports "
                          "both mean and median so you can see the difference.",
                "affected_records": int(outliers["total"]),
                "affected_pct": round(outliers["total"] / max(row_count, 1) * 100, 2),
            }
        )

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), -i.get("affected_pct", 0)))

    # --- recommendations ----------------------------------------------------
    worst_missing = [c for c in columns if c["missing_pct"] > 3]
    worst_missing.sort(key=lambda c: -c["missing_pct"])
    for column in worst_missing[:3]:
        recommendations.append(
            f"{column['missing_pct']:.1f}% of records are missing {column['name']}; decide whether "
            f"to backfill them or exclude them from {column['name']}-based analysis."
        )
    if duplicate_rows:
        recommendations.append(
            f"Remove or investigate {duplicate_rows:,} duplicated row(s) before relying on totals."
        )
    for name, count in list(duplicate_ids.items())[:2]:
        recommendations.append(f"Investigate {count:,} repeated values in the key column {name}.")
    if invalid_numeric:
        recommendations.append(
            f"Clean {invalid_numeric:,} non-numeric value(s) stored in measure columns so they are "
            f"included in totals."
        )
    if not recommendations:
        recommendations.append("No material data quality problems were detected in this dataset.")

    explanation = _explain_score(score, components, missing_pct, duplicate_rows, inconsistent_total)

    return {
        "score": score,
        "grade": _grade(score),
        "explanation": explanation,
        "components": {k: round(v, 1) for k, v in components.items()},
        "weights": weights,
        "metrics": {
            "rows": row_count,
            "columns": len(columns),
            "total_cells": total_cells,
            "missing_cells": missing_cells,
            "missing_pct": round(missing_pct, 2),
            "duplicate_rows": duplicate_rows,
            "duplicate_identifier_columns": duplicate_ids,
            "constant_columns": constant_columns,
            "inconsistent_category_groups": inconsistent_total,
            "invalid_numeric_values": invalid_numeric,
            "invalid_date_values": invalid_dates,
            "outliers": int(outliers.get("total", 0)),
        },
        "issues": issues,
        "recommendations": recommendations[:8],
        "injection_findings": injection_findings[:10],
    }


def _missing_impact(column: dict[str, Any], row_count: int) -> str:
    name = column["name"]
    pct = column["missing_pct"]
    if column["role"] == P.DIMENSION:
        return (
            f"{pct:.1f}% of records cannot be attributed to a {name} value, so any breakdown by "
            f"{name} understates or misclassifies that share of the data."
        )
    if column["role"] == P.MEASURE:
        return (
            f"Totals and averages for {name} are calculated from {100 - pct:.1f}% of records, so the "
            f"true total is likely higher than reported."
        )
    if column["role"] == P.TIME_DIMENSION:
        return (
            f"{pct:.1f}% of records have no {name}, so they are excluded from every trend and "
            f"period-over-period comparison."
        )
    if column["role"] == P.IDENTIFIER_ROLE:
        return f"{pct:.1f}% of records cannot be identified by {name}, limiting record-level tracing."
    return f"{pct:.1f}% of records have no {name} value."


def _explain_score(
    score: float, components: dict[str, float], missing_pct: float,
    duplicate_rows: int, inconsistent: int,
) -> str:
    parts = [f"The dataset scores {score:.0f}/100 ({_grade(score)})."]
    weakest = min(components, key=components.get)
    labels = {
        "completeness": "completeness (missing values)",
        "uniqueness": "uniqueness (duplicate rows or keys)",
        "consistency": "consistency (category spellings)",
        "validity": "validity (values that do not match their column type)",
        "structure": "structure (columns with no variation)",
    }
    if components[weakest] < 95:
        parts.append(f"The weakest dimension is {labels[weakest]} at {components[weakest]:.0f}/100.")
    detail = []
    if missing_pct > 0:
        detail.append(f"{missing_pct:.1f}% of all cells are empty")
    if duplicate_rows:
        detail.append(f"{duplicate_rows:,} duplicate rows")
    if inconsistent:
        detail.append(f"{inconsistent} inconsistent category spelling group(s)")
    if detail:
        parts.append("Contributing factors: " + ", ".join(detail) + ".")
    else:
        parts.append("No missing values, duplicates or inconsistent categories were found.")
    parts.append(
        "The score is a weighted blend of completeness (34%), uniqueness (20%), validity (20%), "
        "consistency (18%) and structure (8%)."
    )
    return " ".join(parts)


def outlier_scan(df: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    """Light-weight outlier count used by the quality score."""
    affected: dict[str, int] = {}
    total = 0
    for column in profile["columns"]:
        if column["role"] != P.MEASURE:
            continue
        numeric = P.to_numeric_series(df[column["name"]]).dropna()
        if len(numeric) < 20:
            continue
        q1, q3 = np.percentile(numeric, [25, 75])
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((numeric < low) | (numeric > high)).sum())
        if count:
            affected[column["name"]] = count
            total += count
    return {"total": total, "columns": affected, "by_column": affected}
