"""Segment comparison and concentration (Pareto) analysis."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import format_value, percent, safe_float
from app.engines.trend import build_series, choose_frequency, pct_change

MAX_CATEGORIES = 40


def compare_segments(
    df: pd.DataFrame, profile: dict[str, Any], dimension: str, measure: str,
    time_column: str | None = None, top: int = 12,
) -> dict[str, Any] | None:
    if dimension not in df.columns or measure not in df.columns:
        return None
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame({"group": df[dimension].astype("string"), "value": values}).dropna()
    if frame.empty:
        return None
    if frame["group"].nunique() > MAX_CATEGORIES or frame["group"].nunique() < 2:
        return None

    currency = profile.get("currency_symbol", "")
    columns = {c["name"]: c for c in profile["columns"]}
    semantic = columns.get(measure, {}).get("semantic_type", "")
    aggregation = columns.get(measure, {}).get("aggregation") or "sum"
    # Shares only mean something when the measure is additive and one-signed.
    shares_valid = aggregation == "sum" and bool(columns.get(measure, {}).get("non_negative", True))

    grouped = frame.groupby("group")["value"]
    summary = pd.DataFrame(
        {
            "total": grouped.sum(),
            "mean": grouped.mean(),
            "median": grouped.median(),
            "count": grouped.count(),
            "std": grouped.std(ddof=1),
        }
    )
    summary["value"] = summary["total"] if aggregation == "sum" else summary["mean"]
    grand_total = float(summary["total"].sum())
    summary["share_pct"] = (
        summary["total"] / grand_total * 100 if shares_valid and grand_total else np.nan
    )
    summary["cv"] = (summary["std"] / summary["mean"].abs() * 100).replace([np.inf, -np.inf], np.nan)
    summary = summary.sort_values("value", ascending=False)

    growth: dict[str, float] = {}
    if time_column and time_column in df.columns:
        dates = P.to_datetime_series(df[time_column])
        freq, _ = choose_frequency(dates.dropna())
        temp = pd.DataFrame({"group": df[dimension].astype("string"), "date": dates, "value": values}).dropna()
        if not temp.empty:
            for group, part in temp.groupby("group"):
                resampled = part.set_index("date").resample(freq)["value"]
                series = resampled.sum() if aggregation == "sum" else resampled.mean()
                series = series[series.notna()]
                if len(series) >= 4:
                    half = len(series) // 2
                    first = float(series.iloc[:half].sum())
                    second = float(series.iloc[half:].sum())
                    change = pct_change(second, first)
                    if change is not None:
                        growth[str(group)] = change

    rows = []
    for group, row in summary.head(top).iterrows():
        rows.append(
            {
                "group": str(group),
                "value": safe_float(row["value"]),
                "formatted_value": format_value(safe_float(row["value"]), semantic, currency),
                "total": safe_float(row["total"]),
                "formatted_total": format_value(safe_float(row["value"]), semantic, currency),
                "mean": safe_float(row["mean"]),
                "formatted_mean": format_value(safe_float(row["mean"]), semantic, currency),
                "median": safe_float(row["median"]),
                "count": int(row["count"]),
                "share_pct": safe_float(row["share_pct"]),
                "cv_pct": safe_float(row["cv"]),
                "growth_pct": round(growth[str(group)], 1) if str(group) in growth else None,
            }
        )

    best = rows[0] if rows else None
    worst = min(rows, key=lambda r: (r["value"] if r["value"] is not None else 0)) if rows else None
    with_growth = [r for r in rows if r["growth_pct"] is not None]
    fastest = max(with_growth, key=lambda r: r["growth_pct"]) if with_growth else None
    slowest = min(with_growth, key=lambda r: r["growth_pct"]) if with_growth else None
    most_variable = max(
        (r for r in rows if r["cv_pct"] is not None), key=lambda r: r["cv_pct"], default=None
    )
    highest_average = max(rows, key=lambda r: (r["mean"] or 0)) if rows else None

    total = float(summary["total"].sum())
    spread_pct = (
        (best["value"] - worst["value"]) / abs(worst["value"]) * 100
        if best and worst and worst["value"] else None
    )

    return {
        "dimension": dimension,
        "measure": measure,
        "semantic_type": semantic,
        "aggregation": aggregation,
        "aggregation_label": "Total" if aggregation == "sum" else "Average",
        "shares_valid": shares_valid,
        "groups": rows,
        "group_count": int(summary.shape[0]),
        "total": safe_float(total if aggregation == "sum" else summary["mean"].mean()),
        "formatted_total": format_value(
            total if aggregation == "sum" else float(summary["mean"].mean()), semantic, currency
        ),
        "best": best,
        "worst": worst,
        "fastest_growing": fastest,
        "fastest_declining": slowest,
        "most_variable": most_variable,
        "highest_average": highest_average,
        "spread_pct": round(spread_pct, 1) if spread_pct is not None else None,
        "has_growth": bool(with_growth),
    }


def analyze_segments(
    df: pd.DataFrame, profile: dict[str, Any], dimensions: list[str], measures: list[str],
    time_column: str | None = None, max_results: int = 12,
) -> list[dict[str, Any]]:
    results = []
    for measure in measures[:3]:
        for dimension in dimensions[:6]:
            comparison = compare_segments(df, profile, dimension, measure, time_column)
            if comparison:
                results.append(comparison)
            if len(results) >= max_results:
                return results
    return results


def concentration_analysis(
    df: pd.DataFrame, profile: dict[str, Any], dimension: str, measure: str,
) -> dict[str, Any] | None:
    """Pareto / HHI concentration for one dimension-measure pair.

    Only meaningful for additive, single-signed measures: the share of a total
    is undefined when the "total" mixes credits and debits, and meaningless when
    the column is a rate or a score.
    """
    column = next((c for c in profile["columns"] if c["name"] == measure), {})
    if (column.get("aggregation") or "sum") != "sum" or not column.get("non_negative", True):
        return None
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame({"group": df[dimension].astype("string"), "value": values}).dropna()
    frame = frame[frame["value"] > 0]
    if frame.empty:
        return None
    totals = frame.groupby("group")["value"].sum().sort_values(ascending=False)
    if len(totals) < 2:
        return None
    grand_total = float(totals.sum())
    if grand_total <= 0:
        return None

    shares = totals / grand_total
    cumulative = shares.cumsum()
    hhi = float((shares ** 2).sum() * 10000)

    top1 = float(shares.iloc[0] * 100)
    top3 = float(cumulative.iloc[min(2, len(cumulative) - 1)] * 100)
    top5 = float(cumulative.iloc[min(4, len(cumulative) - 1)] * 100)
    top10 = float(cumulative.iloc[min(9, len(cumulative) - 1)] * 100)
    # How many groups make up 80% of the measure?
    groups_for_80 = int((cumulative < 0.8).sum() + 1)
    coverage_pct = groups_for_80 / len(totals) * 100

    if len(totals) <= 3:
        risk, severity = False, "low"
    elif top1 >= 45 or (len(totals) >= 5 and top5 >= 75 and coverage_pct <= 40) or hhi >= 2500:
        risk, severity = True, "high" if top1 >= 55 or hhi >= 3500 else "medium"
    elif top3 >= 65 and len(totals) >= 6:
        risk, severity = True, "medium"
    else:
        risk, severity = False, "low"

    currency = profile.get("currency_symbol", "")
    types = {c["name"]: c["semantic_type"] for c in profile["columns"]}
    semantic = types.get(measure, "")

    return {
        "dimension": dimension,
        "measure": measure,
        "group_count": int(len(totals)),
        "total": safe_float(grand_total),
        "formatted_total": format_value(grand_total, semantic, currency),
        "top_group": str(totals.index[0]),
        "top_group_value": safe_float(totals.iloc[0]),
        "top_group_formatted": format_value(safe_float(totals.iloc[0]), semantic, currency),
        "top1_pct": round(top1, 1),
        "top3_pct": round(top3, 1),
        "top5_pct": round(top5, 1),
        "top10_pct": round(top10, 1),
        "groups_for_80pct": groups_for_80,
        "coverage_pct": round(coverage_pct, 1),
        "hhi": round(hhi, 0),
        "is_risk": risk,
        "severity": severity,
        "pareto": [
            {
                "group": str(index),
                "value": safe_float(value),
                "share_pct": round(float(shares.loc[index] * 100), 2),
                "cumulative_pct": round(float(cumulative.loc[index] * 100), 2),
            }
            for index, value in totals.head(15).items()
        ],
        "narrative": (
            f"{groups_for_80} of {len(totals)} {dimension} value(s) account for 80% of {measure}"
            + (f", and {totals.index[0]} alone accounts for {top1:.0f}%." if top1 >= 20 else ".")
        ),
    }


def analyze_concentration(
    df: pd.DataFrame, profile: dict[str, Any], dimensions: list[str], measures: list[str],
    identifiers: list[str] | None = None, max_results: int = 8,
) -> list[dict[str, Any]]:
    candidates = list(dimensions[:6])
    # Customer/product identifiers are the classic concentration axis.
    for identifier in (identifiers or [])[:2]:
        unique = df[identifier].nunique(dropna=True)
        if 2 < unique <= max(200, len(df) * 0.5):
            candidates.append(identifier)

    results = []
    for measure in measures[:2]:
        for dimension in candidates:
            if dimension not in df.columns:
                continue
            analysis = concentration_analysis(df, profile, dimension, measure)
            if analysis:
                results.append(analysis)
    results.sort(key=lambda r: (-int(r["is_risk"]), -r["top1_pct"]))
    return results[:max_results]
