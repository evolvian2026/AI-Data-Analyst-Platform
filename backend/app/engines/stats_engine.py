"""Descriptive statistics and distribution analysis."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from app.engines import profiler as P
from app.engines.formatting import format_value, safe_float

PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]


def describe_numeric(series: pd.Series) -> dict[str, Any]:
    numeric = P.to_numeric_series(series).dropna()
    if numeric.empty:
        return {}
    values = numeric.to_numpy(dtype=float)
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    mode_values = numeric.mode()
    skew = safe_float(scipy_stats.skew(values, bias=False)) if len(values) > 2 else None
    kurtosis = safe_float(scipy_stats.kurtosis(values, bias=False)) if len(values) > 3 else None
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "count": int(len(values)),
        "missing": int(series.isna().sum()),
        "sum": safe_float(values.sum()),
        "mean": safe_float(mean),
        "median": safe_float(median),
        "mode": safe_float(mode_values.iloc[0]) if len(mode_values) else None,
        "min": safe_float(values.min()),
        "max": safe_float(values.max()),
        "range": safe_float(values.max() - values.min()),
        "std": safe_float(std),
        "variance": safe_float(std ** 2),
        "cv": safe_float(std / mean * 100) if mean else None,
        "q1": safe_float(q1),
        "q3": safe_float(q3),
        "iqr": safe_float(q3 - q1),
        "skewness": skew,
        "kurtosis": kurtosis,
        "percentiles": {
            str(p): safe_float(np.percentile(values, p)) for p in PERCENTILES
        },
        "zeros": int((values == 0).sum()),
        "negatives": int((values < 0).sum()),
    }


def histogram(series: pd.Series, bins: int = 20) -> list[dict[str, Any]]:
    numeric = P.to_numeric_series(series).dropna()
    if len(numeric) < 5:
        return []
    values = numeric.to_numpy(dtype=float)
    unique_count = len(np.unique(values))
    bins = int(min(bins, max(5, unique_count)))
    counts, edges = np.histogram(values, bins=bins)
    return [
        {
            "bin": f"{edges[i]:,.4g} – {edges[i + 1]:,.4g}",
            "start": safe_float(edges[i]),
            "end": safe_float(edges[i + 1]),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]


def box_summary(series: pd.Series) -> dict[str, Any]:
    stats = describe_numeric(series)
    if not stats:
        return {}
    iqr = stats["iqr"] or 0
    lower_fence = (stats["q1"] or 0) - 1.5 * iqr
    upper_fence = (stats["q3"] or 0) + 1.5 * iqr
    numeric = P.to_numeric_series(series).dropna()
    inside = numeric[(numeric >= lower_fence) & (numeric <= upper_fence)]
    return {
        "min": stats["min"],
        "q1": stats["q1"],
        "median": stats["median"],
        "q3": stats["q3"],
        "max": stats["max"],
        "whisker_low": safe_float(inside.min()) if len(inside) else stats["min"],
        "whisker_high": safe_float(inside.max()) if len(inside) else stats["max"],
        "lower_fence": safe_float(lower_fence),
        "upper_fence": safe_float(upper_fence),
        "outlier_count": int(len(numeric) - len(inside)),
    }


def interpret_distribution(name: str, stats: dict[str, Any], semantic_type: str,
                           currency: str = "") -> dict[str, Any] | None:
    """Explain a distribution only when there is something worth saying."""
    if not stats or not stats.get("count"):
        return None
    mean, median = stats.get("mean"), stats.get("median")
    skew = stats.get("skewness")
    if mean is None or median is None:
        return None

    fmt = lambda v: format_value(v, semantic_type, currency)  # noqa: E731
    notes: list[str] = []
    shape = "roughly symmetric"
    if skew is not None:
        if skew > 1:
            shape = "strongly right-skewed"
        elif skew > 0.5:
            shape = "moderately right-skewed"
        elif skew < -1:
            shape = "strongly left-skewed"
        elif skew < -0.5:
            shape = "moderately left-skewed"

    gap_pct = abs(mean - median) / abs(median) * 100 if median else 0.0
    if gap_pct >= 10:
        direction = "above" if mean > median else "below"
        tail = "a minority of unusually high values pulls the average up" if mean > median else (
            "a minority of unusually low values pulls the average down"
        )
        notes.append(
            f"The average {name} is {fmt(mean)} but the median is {fmt(median)} - the mean sits "
            f"{gap_pct:.0f}% {direction} the midpoint, suggesting {tail}."
        )
    cv = stats.get("cv")
    if cv is not None and cv > 80:
        notes.append(
            f"{name} is highly variable (coefficient of variation {cv:.0f}%), so a single average "
            f"describes it poorly."
        )
    p90, p10 = stats["percentiles"].get("90"), stats["percentiles"].get("10")
    if p90 and p10 and p10 != 0 and p90 / max(abs(p10), 1e-9) > 5:
        notes.append(
            f"The top decile of {name} ({fmt(p90)}) is more than five times the bottom decile "
            f"({fmt(p10)})."
        )
    if not notes:
        return None
    return {
        "column": name,
        "shape": shape,
        "skewness": skew,
        "gap_pct": round(gap_pct, 1),
        "narrative": " ".join(notes),
        "stats": stats,
    }


def analyze_distributions(df: pd.DataFrame, profile: dict[str, Any],
                          max_columns: int = 12) -> dict[str, Any]:
    measures = [c for c in profile["columns"] if c["role"] == P.MEASURE][:max_columns]
    currency = profile.get("currency_symbol", "")
    results = []
    interpretations = []
    for column in measures:
        stats = describe_numeric(df[column["name"]])
        if not stats:
            continue
        entry = {
            "column": column["name"],
            "semantic_type": column["semantic_type"],
            "stats": stats,
            "box": box_summary(df[column["name"]]),
            "histogram": histogram(df[column["name"]]),
        }
        results.append(entry)
        interpretation = interpret_distribution(
            column["name"], stats, column["semantic_type"], currency
        )
        if interpretation:
            interpretations.append(interpretation)
    return {"columns": results, "interpretations": interpretations}


def categorical_summary(df: pd.DataFrame, column: str, top: int = 15) -> list[dict[str, Any]]:
    counts = df[column].dropna().astype(str).value_counts()
    total = int(counts.sum()) or 1
    return [
        {"value": str(index), "count": int(value), "pct": round(int(value) / total * 100, 2)}
        for index, value in counts.head(top).items()
    ]
