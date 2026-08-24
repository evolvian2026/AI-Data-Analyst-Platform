"""Anomaly detection and anomaly investigation.

Two complementary passes:

* **Record level** - IQR fences plus a modified z-score (median absolute
  deviation), which is robust to the very outliers it is looking for.
* **Time-series level** - residuals from the aggregated series after removing
  the trend, so a genuinely unusual month is flagged rather than the peak of a
  normal seasonal cycle.

Anomaly *investigation* then decomposes an anomalous period across every
available dimension and reports where the deviation is concentrated. It never
claims causation - only coincidence and concentration.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import format_value, safe_float
from app.engines.trend import _label, build_series, choose_frequency

MAD_SCALE = 0.6745
MIN_ANOMALY_PERIODS = 8
MIN_ANOMALY_DEVIATION_PCT = 20.0
# Above this share of a column, "outliers" are describing a skewed distribution
# rather than genuinely exceptional records.
OUTLIER_SHARE_CEILING_PCT = 12.0
MIN_OUTLIER_RECORDS = 3


def _severity(score: float) -> str:
    if score >= 6:
        return "critical"
    if score >= 4.5:
        return "high"
    if score >= 3.5:
        return "medium"
    return "low"


def detect_record_outliers(
    df: pd.DataFrame, profile: dict[str, Any], max_columns: int = 10,
    max_examples: int = 25,
) -> list[dict[str, Any]]:
    currency = profile.get("currency_symbol", "")
    measures = [c for c in profile["columns"] if c["role"] == P.MEASURE][:max_columns]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION][:4]

    findings: list[dict[str, Any]] = []
    for column in measures:
        name = column["name"]
        numeric = P.to_numeric_series(df[name])
        valid = numeric.dropna()
        if len(valid) < 20:
            continue
        values = valid.to_numpy(dtype=float)
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))

        if iqr > 0:
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            iqr_mask = (numeric < low) | (numeric > high)
        else:
            low = high = None
            iqr_mask = pd.Series(False, index=numeric.index)

        if mad > 0:
            modified_z = MAD_SCALE * (numeric - median) / mad
        else:
            std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
            modified_z = (numeric - float(values.mean())) / std if std else numeric * 0
        z_mask = modified_z.abs() > 3.5

        mask = (iqr_mask & z_mask.fillna(False)) | (modified_z.abs() > 5)
        mask = mask.fillna(False)
        count = int(mask.sum())
        if count == 0:
            continue
        # One extreme row is a record to check, not a pattern worth a finding.
        if count < MIN_OUTLIER_RECORDS:
            continue
        share = count / len(valid) * 100
        if share > OUTLIER_SHARE_CEILING_PCT:
            # Too many "outliers" to be exceptional; this is distribution shape,
            # which the distribution engine reports instead.
            continue

        flagged = df.loc[mask].copy()
        flagged["__score__"] = modified_z.loc[mask].abs()
        flagged = flagged.sort_values("__score__", ascending=False)
        top_score = float(flagged["__score__"].iloc[0])

        example_columns = [c for c in identifiers[:2] + dimensions if c in df.columns]
        examples = []
        for _, row in flagged.head(max_examples).iterrows():
            example = {c: (None if pd.isna(row[c]) else str(row[c])) for c in example_columns}
            example["__value__"] = safe_float(numeric.loc[row.name])
            example["__formatted__"] = format_value(
                safe_float(numeric.loc[row.name]), column["semantic_type"], currency
            )
            example["__score__"] = round(float(row["__score__"]), 2)
            example["__row__"] = int(df.index.get_loc(row.name)) if row.name in df.index else None
            examples.append(example)

        direction = "high" if float(flagged[name].apply(lambda v: 1 if safe_float(v) and safe_float(v) > median else 0).mean() if len(flagged) else 0) >= 0.5 else "low"
        findings.append(
            {
                "id": f"anom_col_{column['position']}",
                "kind": "record",
                "column": name,
                "semantic_type": column["semantic_type"],
                "count": count,
                "pct_of_records": round(count / len(valid) * 100, 2),
                "severity": _severity(top_score),
                "max_score": round(top_score, 2),
                "method": "IQR fences confirmed by modified z-score (median absolute deviation)",
                "bounds": {"lower": safe_float(low), "upper": safe_float(high)},
                "median": safe_float(median),
                "direction": direction,
                "examples": examples,
                "headline": (
                    f"{count:,} record(s) have unusual {name} values "
                    f"({count / len(valid) * 100:.1f}% of the column)"
                ),
                "evidence": {
                    "calculation": "Q1 - 1.5xIQR / Q3 + 1.5xIQR, cross-checked with |modified z| > 3.5",
                    "q1": safe_float(q1), "q3": safe_float(q3), "iqr": safe_float(iqr),
                    "median": safe_float(median), "mad": safe_float(mad),
                    "records_used": int(len(valid)),
                },
            }
        )
    findings.sort(key=lambda f: (-f["max_score"], -f["count"]))
    return findings


def detect_timeseries_anomalies(
    df: pd.DataFrame, profile: dict[str, Any], time_column: str | None,
    measures: list[str], max_measures: int = 4,
) -> list[dict[str, Any]]:
    if not time_column or not measures:
        return []
    currency = profile.get("currency_symbol", "")
    columns = {c["name"]: c for c in profile["columns"]}
    types = {name: c["semantic_type"] for name, c in columns.items()}
    freq, unit = choose_frequency(P.to_datetime_series(df[time_column]).dropna())

    findings: list[dict[str, Any]] = []
    for measure in measures[:max_measures]:
        aggregation = columns.get(measure, {}).get("aggregation") or "sum"
        series = build_series(df, time_column, measure, aggregation, freq)
        # Fewer than eight periods cannot support a claim that one of them is
        # unusual - there is no baseline to be unusual against.
        if len(series) < MIN_ANOMALY_PERIODS:
            continue
        values = series["value"].to_numpy(dtype=float)
        x = np.arange(len(values), dtype=float)
        # De-trend so a rising series does not flag its own last period.
        coefficients = np.polyfit(x, values, 1)
        residuals = values - np.polyval(coefficients, x)
        median_residual = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - median_residual)))
        if mad <= 0:
            continue
        scores = MAD_SCALE * (residuals - median_residual) / mad
        for index in np.argsort(-np.abs(scores)):
            score = float(abs(scores[index]))
            if score < 3.5:
                break
            expected = float(np.polyval(coefficients, x[index]))
            actual = float(values[index])
            deviation_pct = (actual - expected) / abs(expected) * 100 if expected else 0.0
            # A statistically extreme residual that moves the value by a few
            # percent is not worth reporting as an anomaly.
            if abs(deviation_pct) < MIN_ANOMALY_DEVIATION_PCT:
                continue
            period_label = _label(series["period"].iloc[index], freq)
            findings.append(
                {
                    "id": f"anom_ts_{measure}_{index}".replace(" ", "_"),
                    "kind": "timeseries",
                    "column": measure,
                    "semantic_type": types.get(measure, ""),
                    "period": period_label,
                    "period_iso": series["period"].iloc[index].isoformat(),
                    "frequency": freq,
                    "unit": unit,
                    "actual": safe_float(actual),
                    "expected": safe_float(expected),
                    "deviation_pct": round(deviation_pct, 1),
                    "direction": "above" if actual > expected else "below",
                    "severity": _severity(score),
                    "max_score": round(score, 2),
                    "count": int(series["records"].iloc[index]),
                    "method": "Modified z-score on de-trended period residuals",
                    "headline": (
                        f"{measure} in {period_label} was {abs(deviation_pct):.0f}% "
                        f"{'above' if actual > expected else 'below'} the level implied by the trend"
                    ),
                    "evidence": {
                        "calculation": "residual = actual - linear trend; |modified z| > 3.5 flags the period",
                        "actual": format_value(actual, types.get(measure, ""), currency),
                        "expected": format_value(expected, types.get(measure, ""), currency),
                        "records_used": int(series["records"].iloc[index]),
                        "periods_analyzed": int(len(values)),
                    },
                }
            )
            if len([f for f in findings if f["column"] == measure]) >= 2:
                break
    findings.sort(key=lambda f: -f["max_score"])
    return findings


def investigate_anomaly(
    df: pd.DataFrame, profile: dict[str, Any], anomaly: dict[str, Any],
    time_column: str | None,
) -> dict[str, Any]:
    """Decompose an anomalous period across the available dimensions.

    Reports where the deviation is *concentrated*, phrased as coincidence rather
    than cause.
    """
    measure = anomaly.get("column")
    if not measure or measure not in df.columns:
        return {"available": False, "reason": "The measure for this anomaly is not available."}

    currency = profile.get("currency_symbol", "")
    types = {c["name"]: c["semantic_type"] for c in profile["columns"]}
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]
    other_measures = [
        c["name"] for c in profile["columns"] if c["role"] == P.MEASURE and c["name"] != measure
    ]

    if anomaly.get("kind") == "timeseries" and time_column:
        dates = P.to_datetime_series(df[time_column])
        freq = anomaly.get("frequency", "MS")
        target = pd.Timestamp(anomaly["period_iso"])
        period_index = dates.dt.to_period(_period_alias(freq))
        target_period = target.to_period(_period_alias(freq))
        in_period = period_index == target_period
        baseline = period_index.notna() & ~in_period
        context_label = anomaly.get("period", "the anomalous period")
    else:
        numeric = P.to_numeric_series(df[measure])
        bounds = anomaly.get("bounds", {})
        upper, lower = bounds.get("upper"), bounds.get("lower")
        in_period = pd.Series(False, index=df.index)
        if upper is not None:
            in_period = in_period | (numeric > upper)
        if lower is not None:
            in_period = in_period | (numeric < lower)
        in_period = in_period.fillna(False)
        baseline = ~in_period & numeric.notna()
        context_label = "the flagged records"

    subject = df.loc[in_period]
    rest = df.loc[baseline]
    if subject.empty:
        return {"available": False, "reason": "No records matched the anomaly definition."}

    values = P.to_numeric_series(df[measure])
    # Shares of a total that mixes positive and negative values are undefined,
    # so contribution is measured on magnitudes when the measure is signed.
    mixed_sign = bool((values.dropna() < 0).any() and (values.dropna() > 0).any())
    share_basis = values.abs() if mixed_sign else values
    subject_total = float(share_basis.loc[in_period].sum())
    contributions: list[dict[str, Any]] = []

    for dimension in dimensions[:6]:
        if df[dimension].nunique(dropna=True) > 60:
            continue
        subject_group = share_basis.loc[in_period].groupby(subject[dimension].astype(str)).sum()
        display_group = values.loc[in_period].groupby(subject[dimension].astype(str)).sum()
        if subject_group.empty or subject_total == 0:
            continue
        subject_share = subject_group / subject_total * 100
        baseline_total = float(share_basis.loc[baseline].sum()) if len(rest) else 0.0
        if baseline_total:
            baseline_group = share_basis.loc[baseline].groupby(rest[dimension].astype(str)).sum()
            baseline_share = baseline_group / baseline_total * 100
        else:
            baseline_share = pd.Series(dtype=float)

        rows = []
        for value, share in subject_share.sort_values(ascending=False).head(6).items():
            normal = float(baseline_share.get(value, 0.0))
            rows.append(
                {
                    "value": str(value),
                    "amount": safe_float(display_group.get(value)),
                    "formatted": format_value(
                        safe_float(display_group.get(value)), types.get(measure, ""), currency
                    ),
                    "share_pct": round(float(share), 1),
                    "normal_share_pct": round(normal, 1),
                    "share_shift_pct": round(float(share) - normal, 1),
                }
            )
        if not rows:
            continue
        top = max(rows, key=lambda r: abs(r["share_shift_pct"]))
        contributions.append(
            {
                "dimension": dimension,
                "rows": rows,
                "top_value": top["value"],
                "top_share_pct": top["share_pct"],
                "top_shift_pct": top["share_shift_pct"],
                "concentrated": abs(top["share_shift_pct"]) >= 8,
                "share_basis": "absolute magnitude" if mixed_sign else "value",
                "narrative": (
                    f"Within {context_label}, {dimension} = {top['value']} accounts for "
                    f"{top['share_pct']:.0f}% of "
                    f"{'the absolute magnitude of ' if mixed_sign else ''}{measure} versus "
                    f"{top['normal_share_pct']:.0f}% in the rest of the dataset "
                    f"({'+' if top['share_shift_pct'] >= 0 else ''}{top['share_shift_pct']:.0f} pts)."
                ),
            }
        )

    contributions.sort(key=lambda c: -abs(c["top_shift_pct"]))

    # Volume vs value decomposition - was it more records, or bigger records?
    volume = {
        "subject_records": int(len(subject)),
        "baseline_records": int(len(rest)),
        "subject_avg": safe_float(values.loc[in_period].mean()),
        "baseline_avg": safe_float(values.loc[baseline].mean()) if len(rest) else None,
    }
    if volume["baseline_avg"]:
        volume["avg_shift_pct"] = round(
            (volume["subject_avg"] - volume["baseline_avg"]) / abs(volume["baseline_avg"]) * 100, 1
        )
        if anomaly.get("kind") == "timeseries":
            periods = max(int(anomaly.get("evidence", {}).get("periods_analyzed", 1)) - 1, 1)
            expected_records = volume["baseline_records"] / periods
            volume["expected_records"] = round(expected_records, 1)
            volume["record_shift_pct"] = (
                round((volume["subject_records"] - expected_records) / expected_records * 100, 1)
                if expected_records else None
            )
    else:
        volume["avg_shift_pct"] = None

    driver = "unclear"
    if volume.get("avg_shift_pct") is not None and volume.get("record_shift_pct") is not None:
        if abs(volume["avg_shift_pct"]) > abs(volume["record_shift_pct"]) * 1.5:
            driver = "value"
        elif abs(volume["record_shift_pct"]) > abs(volume["avg_shift_pct"]) * 1.5:
            driver = "volume"
        else:
            driver = "both"

    volume_narrative = None
    if driver == "value":
        volume_narrative = (
            f"The average {measure} per record was {volume['avg_shift_pct']:+.0f}% versus the rest of "
            f"the dataset while record volume moved {volume.get('record_shift_pct', 0):+.0f}%, so the "
            f"deviation is concentrated in larger individual records rather than more of them."
        )
    elif driver == "volume":
        volume_narrative = (
            f"Record volume was {volume.get('record_shift_pct', 0):+.0f}% versus a typical period "
            f"while the average {measure} per record moved only {volume['avg_shift_pct']:+.0f}%, so "
            f"the deviation coincides with a change in activity levels rather than record size."
        )
    elif driver == "both":
        volume_narrative = (
            f"Both record volume ({volume.get('record_shift_pct', 0):+.0f}%) and average {measure} "
            f"per record ({volume['avg_shift_pct']:+.0f}%) moved together."
        )

    companions = []
    for other in other_measures[:4]:
        other_values = P.to_numeric_series(df[other])
        subject_mean = safe_float(other_values.loc[in_period].mean())
        baseline_mean = safe_float(other_values.loc[baseline].mean()) if len(rest) else None
        if subject_mean is None or not baseline_mean:
            continue
        shift = (subject_mean - baseline_mean) / abs(baseline_mean) * 100
        if abs(shift) >= 10:
            companions.append(
                {
                    "measure": other,
                    "subject_avg": subject_mean,
                    "baseline_avg": baseline_mean,
                    "shift_pct": round(shift, 1),
                    "narrative": (
                        f"Average {other} was {shift:+.0f}% versus the rest of the dataset over the "
                        f"same records."
                    ),
                }
            )
    companions.sort(key=lambda c: -abs(c["shift_pct"]))

    top_records = []
    if identifiers:
        key = identifiers[0]
        subject_values = values.loc[in_period]
        ordered = subject_values.reindex(
            share_basis.loc[in_period].sort_values(ascending=False).index
        ).head(5)
        for index, value in ordered.items():
            top_records.append(
                {
                    "identifier": str(df.at[index, key]),
                    "value": safe_float(value),
                    "formatted": format_value(safe_float(value), types.get(measure, ""), currency),
                    "share_pct": round(float(value) / subject_total * 100, 1) if subject_total else None,
                }
            )

    explanations = [c["narrative"] for c in contributions if c["concentrated"]][:3]
    if volume_narrative:
        explanations.append(volume_narrative)
    explanations.extend(c["narrative"] for c in companions[:2])

    return {
        "available": True,
        "anomaly_id": anomaly.get("id"),
        "measure": measure,
        "context": context_label,
        "records_examined": int(len(subject)),
        "baseline_records": int(len(rest)),
        "contributions": contributions[:5],
        "volume_vs_value": {**volume, "driver": driver, "narrative": volume_narrative},
        "companion_measures": companions[:4],
        "top_records": top_records,
        "explanations": explanations[:5],
        "caveat": (
            "These findings describe where the deviation is concentrated. They show association, "
            "not causation - a factor outside this dataset may be responsible."
        ),
        "next_questions": _next_questions(measure, contributions, time_column),
    }


def _next_questions(measure: str, contributions: list[dict[str, Any]],
                    time_column: str | None) -> list[str]:
    questions = []
    for contribution in contributions[:3]:
        questions.append(
            f"Does the shift in {contribution['dimension']} ({contribution['top_value']}) also appear "
            f"in other periods?"
        )
    questions.append(f"Was the change in {measure} driven by more records or larger records?")
    if time_column:
        questions.append(f"Has a similar deviation in {measure} occurred before in this dataset?")
    return questions[:5]


def _period_alias(freq: str) -> str:
    return {"D": "D", "W": "W", "MS": "M", "QS": "Q", "YS": "Y"}.get(freq, "M")


def summarize_anomalies(record: list[dict[str, Any]], timeseries: list[dict[str, Any]],
                        row_count: int) -> dict[str, Any]:
    all_items = timeseries + record
    affected_columns = sorted({item["column"] for item in all_items})
    affected_records = sum(item.get("count", 0) for item in record)
    return {
        "total": len(all_items),
        "record_level": len(record),
        "timeseries_level": len(timeseries),
        "affected_columns": affected_columns,
        "affected_records": int(affected_records),
        "affected_pct": round(affected_records / max(row_count, 1) * 100, 2),
        "highest_severity": (
            max((i["severity"] for i in all_items), key=lambda s: {"critical": 3, "high": 2, "medium": 1, "low": 0}[s])
            if all_items else None
        ),
        "items": all_items,
    }
