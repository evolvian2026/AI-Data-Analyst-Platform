"""Trend, seasonality and period-over-period change detection.

Nothing here runs unless a valid time dimension exists - the spec explicitly
forbids inventing time comparisons for datasets that have no dates.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from app.engines import profiler as P
from app.engines.formatting import format_value, safe_float

FREQ_LABELS = {"D": "day", "W": "week", "MS": "month", "QS": "quarter", "YS": "year"}


PERIOD_ALIAS = {"D": "D", "W": "W", "MS": "M", "QS": "Q", "YS": "Y"}
_CANDIDATE_FREQS = ["D", "W", "MS", "QS", "YS"]
IDEAL_MIN_BUCKETS = 8
IDEAL_MAX_BUCKETS = 60


def choose_frequency(dates: pd.Series) -> tuple[str, str]:
    """Pick the finest grain that produces a well-populated series.

    Choosing purely on the calendar span breaks on year-stamped data: a column
    holding 2023, 2024 and 2025 spans two years, but resampling it monthly
    manufactures 22 empty months and a series of artificial zeros. The grain is
    therefore chosen from how densely the actual values fill each candidate.
    """
    valid = dates.dropna()
    if valid.empty:
        return "MS", "month"
    if valid.min() == valid.max():
        return "D", "day"

    best: tuple[str, float] | None = None
    for freq in _CANDIDATE_FREQS:
        alias = PERIOD_ALIAS[freq]
        periods = valid.dt.to_period(alias)
        distinct = int(periods.nunique())
        span = int((periods.max() - periods.min()).n) + 1
        if span <= 0:
            continue
        fill = distinct / span
        if distinct < 3 or span > 3000:
            continue
        if IDEAL_MIN_BUCKETS <= span <= IDEAL_MAX_BUCKETS and fill >= 0.5:
            return freq, FREQ_LABELS[freq]
        # remember the least-bad option in case nothing lands in the ideal band
        penalty = abs(span - 24) / 24 + (1 - fill) * 3
        if best is None or penalty < best[1]:
            best = (freq, penalty)
    if best:
        return best[0], FREQ_LABELS[best[0]]
    return "YS", "year"


def build_series(
    df: pd.DataFrame, time_column: str, measure: str, agg: str = "sum",
    freq: str | None = None,
) -> pd.DataFrame:
    dates = P.to_datetime_series(df[time_column])
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame({"date": dates, "value": values}).dropna()
    if frame.empty:
        return frame
    if freq is None:
        freq, _ = choose_frequency(frame["date"])
    grouped = frame.set_index("date").resample(freq)["value"]
    series = grouped.sum() if agg == "sum" else grouped.mean()
    counts = grouped.count()
    result = pd.DataFrame({"period": series.index, "value": series.to_numpy(), "records": counts.to_numpy()})
    # Drop leading/trailing empty periods so the trend isn't distorted.
    non_empty = result.index[result["records"] > 0]
    if len(non_empty):
        result = result.loc[non_empty.min(): non_empty.max()].reset_index(drop=True)
    return trim_partial_periods(result, freq, frame["date"].min(), frame["date"].max())


def date_granularity(dates: pd.Series) -> str:
    """How precisely the source dates are recorded: day, month or year."""
    valid = dates.dropna()
    if valid.empty:
        return "D"
    normalized = valid.dt.normalize()
    if not bool((normalized == valid).all()):
        return "D"
    if bool((valid.dt.dayofyear == 1).all()):
        return "Y"
    if bool((valid.dt.day == 1).all()):
        return "M"
    return "D"


def trim_partial_periods(
    series: pd.DataFrame, freq: str, data_min: pd.Timestamp, data_max: pd.Timestamp,
    threshold: float = 0.25,
) -> pd.DataFrame:
    """Remove buckets the dataset does not actually cover end to end.

    A month holding three days of data is not a decline - it is an artefact of
    where the dataset happens to start or stop. Boundary buckets are dropped
    when the observed data does not span the whole calendar bucket, judged at
    the granularity the dates are actually recorded at (a month-stamped column
    covers its month completely even though its only value is the 1st).
    """
    if len(series) < 3 or pd.isna(data_min) or pd.isna(data_max):
        return series.reset_index(drop=True)

    alias = PERIOD_ALIAS.get(freq, "M")
    granularity = date_granularity(pd.Series([data_min, data_max]))

    def _floor(value: pd.Timestamp) -> pd.Timestamp:
        if granularity == "Y":
            return value.to_period("Y").start_time
        if granularity == "M":
            return value.to_period("M").start_time
        return value.normalize()

    first_period = series["period"].iloc[0].to_period(alias)
    last_period = series["period"].iloc[-1].to_period(alias)
    if _floor(first_period.start_time) < _floor(data_min):
        series = series.iloc[1:]
    if len(series) >= 3 and _floor(last_period.end_time) > _floor(data_max):
        series = series.iloc[:-1]

    # Secondary guard for irregular data: a boundary bucket with a tiny fraction
    # of the typical record count is still an edge artefact.
    if len(series) >= 4:
        typical = float(series["records"].median())
        if typical > 0 and float(series["records"].iloc[0]) < typical * threshold:
            series = series.iloc[1:]
    if len(series) >= 4:
        typical = float(series["records"].median())
        if typical > 0 and float(series["records"].iloc[-1]) < typical * threshold:
            series = series.iloc[:-1]
    return series.reset_index(drop=True)


def _label(period: pd.Timestamp, freq: str) -> str:
    if freq == "D":
        return period.strftime("%d %b %Y")
    if freq == "W":
        return period.strftime("W%V %Y")
    if freq == "MS":
        return period.strftime("%b %Y")
    if freq == "QS":
        return f"Q{((period.month - 1) // 3) + 1} {period.year}"
    return period.strftime("%Y")


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Percentage change, defined only when the baseline is strictly positive.

    A change from -30 to +12 is not a "140% increase" and a change from 0 to
    anything is not a percentage at all, so those cases return None and the
    caller reports the absolute movement instead.
    """
    if current is None or previous is None:
        return None
    if previous <= 0 or current < 0:
        return None
    return (current - previous) / previous * 100


def classify_trend(series: pd.DataFrame) -> dict[str, Any]:
    """Ordinary least squares slope + significance on the aggregated series."""
    if len(series) < 3:
        return {"direction": "insufficient", "confidence": "low"}
    y = series["value"].to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    result = scipy_stats.linregress(x, y)
    mean_value = float(np.mean(y)) or 1.0
    slope_pct = result.slope / abs(mean_value) * 100
    r_squared = float(result.rvalue ** 2)
    p_value = float(result.pvalue)

    if p_value < 0.05 and abs(slope_pct) >= 1.0:
        direction = "increasing" if result.slope > 0 else "decreasing"
    elif abs(slope_pct) < 0.5 or p_value >= 0.2:
        direction = "stable"
    else:
        direction = "increasing" if result.slope > 0 else "decreasing"

    confidence = "high" if p_value < 0.01 and r_squared > 0.5 else (
        "medium" if p_value < 0.05 else "low"
    )
    volatility = float(np.std(y, ddof=1) / abs(mean_value) * 100) if len(y) > 1 and mean_value else 0.0
    return {
        "direction": direction,
        "slope": safe_float(result.slope),
        "slope_pct_per_period": safe_float(slope_pct),
        "r_squared": safe_float(r_squared),
        "p_value": safe_float(p_value),
        "confidence": confidence,
        "volatility_pct": safe_float(volatility),
        "periods": int(len(y)),
    }


def detect_seasonality(series: pd.DataFrame, freq: str) -> dict[str, Any] | None:
    """Month-of-year (or quarter) effect detection - needs >= 2 full cycles."""
    if freq not in {"MS", "QS"} or len(series) < 8:
        return None
    frame = series.copy()
    frame["cycle"] = frame["period"].dt.month if freq == "MS" else frame["period"].dt.quarter
    cycles = frame["period"].dt.year.nunique()
    if cycles < 2:
        return None
    grouped = frame.groupby("cycle")["value"].mean()
    if len(grouped) < 3:
        return None
    overall = float(frame["value"].mean()) or 1.0
    deviation = (grouped - overall) / abs(overall) * 100
    peak_cycle = int(deviation.idxmax())
    trough_cycle = int(deviation.idxmin())
    strength = float(deviation.abs().max())
    if strength < 12:
        return None
    labels = (
        {i: pd.Timestamp(2024, i, 1).strftime("%B") for i in range(1, 13)}
        if freq == "MS" else {i: f"Q{i}" for i in range(1, 5)}
    )
    return {
        "detected": True,
        "peak": labels.get(peak_cycle, str(peak_cycle)),
        "peak_deviation_pct": round(float(deviation.max()), 1),
        "trough": labels.get(trough_cycle, str(trough_cycle)),
        "trough_deviation_pct": round(float(deviation.min()), 1),
        "strength_pct": round(strength, 1),
        "cycles_observed": int(cycles),
        "profile": [
            {"cycle": labels.get(int(idx), str(idx)), "average": safe_float(val),
             "deviation_pct": round(float(deviation.loc[idx]), 1)}
            for idx, val in grouped.items()
        ],
    }


def detect_runs(series: pd.DataFrame, freq: str) -> dict[str, Any]:
    """Longest consecutive growth / decline stretches."""
    if len(series) < 4:
        return {}
    values = series["value"].to_numpy(dtype=float)
    diffs = np.diff(values)
    best = {"growth": (0, 0, 0), "decline": (0, 0, 0)}  # (length, start, end)
    for sign, key in ((1, "growth"), (-1, "decline")):
        length = start = 0
        for i, delta in enumerate(diffs):
            if (delta > 0) if sign > 0 else (delta < 0):
                if length == 0:
                    start = i
                length += 1
                if length > best[key][0]:
                    best[key] = (length, start, i + 1)
            else:
                length = 0
    output: dict[str, Any] = {}
    for key in ("growth", "decline"):
        length, start, end = best[key]
        if length >= 2:
            change = pct_change(float(values[end]), float(values[start]))
            output[key] = {
                "periods": int(length),
                "from": _label(series["period"].iloc[start], freq),
                "to": _label(series["period"].iloc[end], freq),
                "change_pct": round(change, 1) if change is not None else None,
                "change": safe_float(values[end] - values[start]),
            }
    return output


def detect_sudden_changes(series: pd.DataFrame, freq: str, threshold: float = 25.0) -> list[dict[str, Any]]:
    """Period-over-period jumps far outside the typical movement."""
    if len(series) < 5:
        return []
    values = series["value"].to_numpy(dtype=float)
    changes = []
    pct_changes = []
    for i in range(1, len(values)):
        change = pct_change(float(values[i]), float(values[i - 1]))
        if change is not None:
            pct_changes.append(change)
    if not pct_changes:
        return []
    typical = float(np.median(np.abs(pct_changes))) or 1.0
    records = series["records"].to_numpy(dtype=float)
    typical_records = float(np.median(records)) or 1.0
    for i in range(1, len(values)):
        previous = values[i - 1]
        change = pct_change(float(values[i]), float(previous))
        if change is None:
            continue
        # A swing between two sparsely populated periods is sampling noise.
        if min(records[i], records[i - 1]) < max(5.0, typical_records * 0.25):
            continue
        if abs(change) >= max(threshold, typical * 2.5):
            changes.append(
                {
                    "period": _label(series["period"].iloc[i], freq),
                    "previous_period": _label(series["period"].iloc[i - 1], freq),
                    "value": safe_float(values[i]),
                    "previous_value": safe_float(previous),
                    "change_pct": round(float(change), 1),
                    "direction": "increase" if change > 0 else "decrease",
                    "typical_movement_pct": round(typical, 1),
                }
            )
    changes.sort(key=lambda c: -abs(c["change_pct"]))
    return changes[:6]


def period_comparison(series: pd.DataFrame, freq: str) -> list[dict[str, Any]]:
    """Latest vs previous, and same period last year where available."""
    comparisons: list[dict[str, Any]] = []
    if len(series) < 2:
        return comparisons
    values = series["value"].to_numpy(dtype=float)
    periods = series["period"]
    unit = FREQ_LABELS.get(freq, "period")

    current, previous = values[-1], values[-2]
    if pct_change(float(current), float(previous)) is not None:
        comparisons.append(
            {
                "type": f"{unit}_over_{unit}",
                "label": f"Latest {unit} vs previous {unit}",
                "current_label": _label(periods.iloc[-1], freq),
                "previous_label": _label(periods.iloc[-2], freq),
                "current": safe_float(current),
                "previous": safe_float(previous),
                "change": safe_float(current - previous),
                "change_pct": pct_change(float(current), float(previous)),
            }
        )

    periods_per_year = {"D": 365, "W": 52, "MS": 12, "QS": 4, "YS": 1}.get(freq, 12)
    if len(values) > periods_per_year:
        year_ago = values[-1 - periods_per_year]
        if pct_change(float(current), float(year_ago)) is not None:
            comparisons.append(
                {
                    "type": "year_over_year",
                    "label": f"Latest {unit} vs same {unit} last year",
                    "current_label": _label(periods.iloc[-1], freq),
                    "previous_label": _label(periods.iloc[-1 - periods_per_year], freq),
                    "current": safe_float(current),
                    "previous": safe_float(year_ago),
                    "change": safe_float(current - year_ago),
                    "change_pct": pct_change(float(current), float(year_ago)),
                }
            )

    half = len(values) // 2
    if half >= 2:
        first_half, second_half = float(values[:half].sum()), float(values[half:].sum())
        if pct_change(second_half, first_half) is not None:
            comparisons.append(
                {
                    "type": "first_half_vs_second_half",
                    "label": "First half vs second half of the period",
                    "current_label": f"{_label(periods.iloc[half], freq)} – {_label(periods.iloc[-1], freq)}",
                    "previous_label": f"{_label(periods.iloc[0], freq)} – {_label(periods.iloc[half - 1], freq)}",
                    "current": safe_float(second_half),
                    "previous": safe_float(first_half),
                    "change": safe_float(second_half - first_half),
                    "change_pct": pct_change(second_half, first_half),
                }
            )
    return comparisons


MIN_TREND_PERIODS = 4


def decompose_volume_value(series: pd.DataFrame, mean_series: pd.DataFrame) -> dict[str, Any]:
    """Split a change in a total into "more records" versus "bigger records".

    A total that doubles because twice as many rows arrived is a very different
    finding from one that doubles because each row got bigger, and reporting the
    headline percentage without this distinction is how a cohort-size chart gets
    mistaken for growth.
    """
    if len(series) < 4:
        return {}
    records = series["records"].to_numpy(dtype=float)
    values = series["value"].to_numpy(dtype=float)
    averages = mean_series["value"].to_numpy(dtype=float) if len(mean_series) == len(series) else None

    half = len(series) // 2
    record_change = pct_change(float(records[half:].sum()), float(records[:half].sum()))
    value_change = pct_change(float(values[half:].sum()), float(values[:half].sum()))
    average_change = None
    if averages is not None and np.isfinite(averages).all():
        average_change = pct_change(
            float(np.nanmean(averages[half:])), float(np.nanmean(averages[:half]))
        )

    driver = "unclear"
    if record_change is not None and average_change is not None:
        if abs(record_change) > abs(average_change) * 2:
            driver = "volume"
        elif abs(average_change) > abs(record_change) * 2:
            driver = "value"
        else:
            driver = "both"

    narrative = ""
    if driver == "volume":
        narrative = (
            f"The movement is driven by record volume: the number of records per period changed "
            f"{record_change:+.0f}% while the average per record changed {average_change:+.0f}%."
        )
    elif driver == "value":
        narrative = (
            f"The movement is driven by size per record: the average per record changed "
            f"{average_change:+.0f}% while record volume changed {record_change:+.0f}%."
        )
    elif driver == "both":
        narrative = (
            f"Record volume ({record_change:+.0f}%) and average per record "
            f"({average_change:+.0f}%) both moved in the same direction."
        )
    return {
        "record_change_pct": round(record_change, 1) if record_change is not None else None,
        "value_change_pct": round(value_change, 1) if value_change is not None else None,
        "average_change_pct": round(average_change, 1) if average_change is not None else None,
        "driver": driver,
        "narrative": narrative,
    }


def analyze_trends(
    df: pd.DataFrame, profile: dict[str, Any], time_column: str | None,
    measures: list[str], max_measures: int = 6,
) -> list[dict[str, Any]]:
    if not time_column or not measures:
        return []
    currency = profile.get("currency_symbol", "")
    columns = {c["name"]: c for c in profile["columns"]}
    types = {name: c["semantic_type"] for name, c in columns.items()}
    dates = P.to_datetime_series(df[time_column])
    freq, unit = choose_frequency(dates.dropna())

    results: list[dict[str, Any]] = []
    for measure in measures[:max_measures]:
        aggregation = columns.get(measure, {}).get("aggregation") or "sum"
        series = build_series(df, time_column, measure, aggregation, freq)
        if len(series) < MIN_TREND_PERIODS:
            continue
        classification = classify_trend(series)
        decomposition = (
            decompose_volume_value(series, build_series(df, time_column, measure, "mean", freq))
            if aggregation == "sum" else {}
        )
        seasonality = detect_seasonality(series, freq)
        runs = detect_runs(series, freq)
        sudden = detect_sudden_changes(series, freq)
        comparisons = period_comparison(series, freq)
        points = [
            {
                "label": _label(row.period, freq),
                "iso": row.period.isoformat(),
                "value": safe_float(row.value),
                "records": int(row.records),
            }
            for row in series.itertuples()
        ]
        first, last = float(series["value"].iloc[0]), float(series["value"].iloc[-1])
        total_change_pct = pct_change(last, first)
        results.append(
            {
                "measure": measure,
                "aggregation": aggregation,
                "aggregation_label": "Total" if aggregation == "sum" else "Average",
                "time_column": time_column,
                "frequency": freq,
                "unit": unit,
                "points": points,
                "classification": classification,
                "decomposition": decomposition,
                "seasonality": seasonality,
                "runs": runs,
                "sudden_changes": sudden,
                "comparisons": comparisons,
                "first_period": points[0]["label"],
                "last_period": points[-1]["label"],
                "first_value": safe_float(first),
                "last_value": safe_float(last),
                "total_change_pct": total_change_pct,
                "total": safe_float(
                    series["value"].sum() if aggregation == "sum" else series["value"].mean()
                ),
                "formatted_total": format_value(
                    safe_float(
                        series["value"].sum() if aggregation == "sum" else series["value"].mean()
                    ),
                    types.get(measure, ""), currency,
                ),
            }
        )
    return results
