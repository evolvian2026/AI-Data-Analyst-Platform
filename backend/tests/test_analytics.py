"""Analytics: KPIs, trends, outliers, correlation and segment comparison."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines import profiler as P
from app.engines.anomaly import (
    detect_record_outliers,
    detect_timeseries_anomalies,
    investigate_anomaly,
)
from app.engines.correlation import analyze_correlations, strength_label
from app.engines.kpi import build_kpis
from app.engines.segments import analyze_concentration, compare_segments, concentration_analysis
from app.engines.stats_engine import describe_numeric, histogram, interpret_distribution
from app.engines.trend import (
    analyze_trends,
    build_series,
    choose_frequency,
    classify_trend,
    pct_change,
    trim_partial_periods,
)


def profile_of(frame: pd.DataFrame) -> dict:
    result = P.profile_dataframe(frame)
    result.pop("profiles", None)
    return result


# --- KPI engine -------------------------------------------------------------

def test_kpis_are_prioritised_and_capped(sales_frame):
    profile = profile_of(sales_frame)
    kpis = build_kpis(sales_frame, profile, "Order Date", max_primary=8)
    assert 1 <= len(kpis["primary"]) <= 8
    scores = [k["priority_score"] for k in kpis["primary"]]
    assert scores == sorted(scores, reverse=True)
    assert len(kpis["all"]) > len(kpis["primary"]), "View All Metrics needs more than the top set"


def test_kpi_totals_match_the_dataframe(sales_frame):
    profile = profile_of(sales_frame)
    kpis = build_kpis(sales_frame, profile, "Order Date")
    revenue = next(k for k in kpis["all"] if k["key"] == "measure::Revenue::sum")
    assert revenue["value"] == pytest.approx(float(sales_frame["Revenue"].sum()), rel=1e-6)
    assert revenue["records_used"] == len(sales_frame)


def test_non_additive_measures_are_averaged(sales_frame):
    profile = profile_of(sales_frame)
    kpis = build_kpis(sales_frame, profile, "Order Date")
    rating = next(k for k in kpis["all"] if k["source_columns"] == ["Rating"])
    assert rating["aggregation"] == "mean"
    assert rating["value"] == pytest.approx(float(sales_frame["Rating"].mean()), rel=1e-6)


def test_derived_metrics_are_labelled_and_carry_a_formula(sales_frame):
    profile = profile_of(sales_frame)
    kpis = build_kpis(sales_frame, profile, "Order Date")
    derived = [k for k in kpis["all"] if k["derived"]]
    assert derived, "Revenue and Profit should produce a margin"
    margin = next(k for k in derived if "margin" in k["label"].lower())
    expected = sales_frame["Profit"].sum() / sales_frame["Revenue"].sum() * 100
    assert margin["value"] == pytest.approx(expected, rel=1e-6)
    assert margin["math"]["formula"]
    assert "derived" in margin["label"].lower()


def test_no_derived_metric_when_columns_are_incompatible():
    frame = pd.DataFrame({"Category": list("abcd") * 10, "Score": np.arange(40)})
    profile = profile_of(frame)
    kpis = build_kpis(frame, profile, None)
    assert not [k for k in kpis["all"] if k["derived"]]


# --- trends -----------------------------------------------------------------

def test_trend_direction_is_detected():
    dates = pd.date_range("2024-01-01", periods=24, freq="MS")
    rising = pd.DataFrame({"D": dates, "V": np.arange(24) * 10 + 100})
    series = build_series(rising, "D", "V", "sum", "MS")
    assert classify_trend(series)["direction"] == "increasing"

    falling = pd.DataFrame({"D": dates, "V": 500 - np.arange(24) * 10})
    assert classify_trend(build_series(falling, "D", "V", "sum", "MS"))["direction"] == "decreasing"

    flat = pd.DataFrame({"D": dates, "V": [100] * 24})
    assert classify_trend(build_series(flat, "D", "V", "sum", "MS"))["direction"] == "stable"


def test_frequency_selection_does_not_invent_empty_periods():
    """Year-stamped data must not be resampled into mostly-empty months."""
    years = pd.to_datetime(pd.Series(["2023-01-01", "2024-01-01", "2025-01-01"] * 30))
    assert choose_frequency(years)[0] == "YS"
    daily = pd.date_range("2024-01-01", "2025-12-31", freq="D").to_series()
    assert choose_frequency(daily)[0] == "MS"


def test_partial_boundary_periods_are_trimmed():
    """A half-finished final month must not read as a collapse."""
    periods = pd.date_range("2024-01-01", periods=6, freq="MS")
    series = pd.DataFrame({
        "period": periods, "value": [100.0] * 5 + [12.0], "records": [30] * 5 + [3],
    })
    trimmed = trim_partial_periods(series, "MS", pd.Timestamp("2024-01-01"),
                                   pd.Timestamp("2024-06-04"))
    assert len(trimmed) == 5
    assert trimmed["value"].iloc[-1] == 100.0


def test_percentage_change_is_undefined_on_a_non_positive_base():
    assert pct_change(120, 100) == pytest.approx(20)
    assert pct_change(50, 0) is None
    assert pct_change(50, -20) is None
    assert pct_change(-30, 20) is None


def test_seasonality_and_sudden_changes_are_reported(sales_frame):
    profile = profile_of(sales_frame)
    trends = analyze_trends(sales_frame, profile, "Order Date", ["Revenue"])
    assert trends and trends[0]["measure"] == "Revenue"
    trend = trends[0]
    assert trend["points"]
    assert trend["classification"]["periods"] == len(trend["points"])
    assert set(trend).issuperset({"comparisons", "runs", "sudden_changes", "decomposition"})


def test_trend_decomposes_volume_from_value():
    """More rows and bigger rows are different stories about the same total."""
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    rows = []
    for index, date in enumerate(dates):
        for _ in range(10 + index * 10):  # volume grows, value per row is constant
            rows.append({"D": date, "V": 100.0})
    frame = pd.DataFrame(rows)
    profile = profile_of(frame)
    trend = analyze_trends(frame, profile, "D", ["V"])[0]
    assert trend["decomposition"]["driver"] == "volume"
    assert "record volume" in trend["decomposition"]["narrative"]


def test_no_trends_without_a_time_dimension():
    frame = pd.DataFrame({"Cat": list("abcd") * 10, "Value": np.arange(40)})
    assert analyze_trends(frame, profile_of(frame), None, ["Value"]) == []


# --- anomalies --------------------------------------------------------------

def test_record_outliers_are_detected_and_bounded():
    rng = np.random.default_rng(5)
    values = np.append(rng.normal(100, 5, 500), [900, 950, 1000])
    frame = pd.DataFrame({"ID": [f"R{i}" for i in range(len(values))], "Value": values})
    profile = profile_of(frame)
    findings = detect_record_outliers(frame, profile)
    assert findings
    finding = findings[0]
    assert finding["column"] == "Value"
    assert finding["count"] >= 3
    assert finding["bounds"]["upper"] < 900
    assert finding["examples"]


def test_a_single_stray_record_is_not_reported_as_a_pattern():
    rng = np.random.default_rng(6)
    values = np.append(rng.normal(100, 5, 500), [5000])
    frame = pd.DataFrame({"Value": values})
    assert detect_record_outliers(frame, profile_of(frame)) == []


def test_timeseries_anomaly_needs_enough_history():
    dates = pd.date_range("2024-01-01", periods=4, freq="MS")
    frame = pd.DataFrame({"D": dates, "V": [10, 12, 11, 400]})
    assert detect_timeseries_anomalies(frame, profile_of(frame), "D", ["V"]) == []


def test_timeseries_anomaly_is_found_in_a_long_series():
    dates = pd.date_range("2024-01-01", periods=24, freq="MS")
    values = [100.0] * 24
    values[14] = 400.0
    frame = pd.DataFrame({"D": dates, "V": values})
    findings = detect_timeseries_anomalies(frame, profile_of(frame), "D", ["V"])
    assert findings
    assert findings[0]["direction"] == "above"
    assert abs(findings[0]["deviation_pct"]) > 20


def test_anomaly_investigation_points_at_a_concentrated_dimension():
    rng = np.random.default_rng(21)
    dates = pd.date_range("2024-01-01", periods=24, freq="MS")
    rows = []
    for date in dates:
        spike = date.month == 3 and date.year == 2025
        for region in ("North", "South", "East"):
            for _ in range(5):
                amount = float(rng.normal(100, 12))
                if spike and region == "North":
                    amount = float(rng.normal(2000, 90))
                rows.append({"D": date, "Region": region, "Revenue": round(amount, 2)})
    frame = pd.DataFrame(rows)
    profile = profile_of(frame)
    anomalies = detect_timeseries_anomalies(frame, profile, "D", ["Revenue"])
    assert anomalies
    investigation = investigate_anomaly(frame, profile, anomalies[0], "D")
    assert investigation["available"]
    assert investigation["contributions"][0]["dimension"] == "Region"
    assert investigation["contributions"][0]["top_value"] == "North"
    assert "not causation" in investigation["caveat"]


# --- correlation -------------------------------------------------------------

def test_correlation_finds_a_planted_relationship():
    rng = np.random.default_rng(9)
    spend = rng.uniform(100, 1000, 400)
    revenue = spend * 3 + rng.normal(0, 120, 400)
    frame = pd.DataFrame({"Spend": spend, "Revenue": revenue,
                          "Noise": rng.normal(0, 1, 400)})
    result = analyze_correlations(frame, profile_of(frame))
    assert result["available"]
    pair = next(p for p in result["pairs"] if {p["x"], p["y"]} == {"Spend", "Revenue"})
    assert pair["pearson_r"] > 0.8
    assert pair["significant"]
    assert "not establish" in result["caveat"] or "does not establish" in result["caveat"]


def test_correlation_excludes_arithmetically_derived_pairs(sales_frame):
    from app.engines.derived import detect_derived_columns

    profile = profile_of(sales_frame)
    derived = detect_derived_columns(sales_frame, profile)
    result = analyze_correlations(sales_frame, profile, derived=derived)
    meaningful = {frozenset((p["x"], p["y"])) for p in result["meaningful"]}
    assert frozenset(("Revenue", "Profit")) not in meaningful


def test_correlation_unavailable_with_one_measure():
    frame = pd.DataFrame({"Cat": list("ab") * 20, "Value": np.arange(40)})
    assert analyze_correlations(frame, profile_of(frame))["available"] is False


def test_strength_labels():
    assert "very strong" in strength_label(0.92)
    assert "negative" in strength_label(-0.7)
    assert strength_label(0.05) == "no meaningful relationship"


# --- segments and concentration ---------------------------------------------

def test_segment_comparison_totals_match(sales_frame):
    profile = profile_of(sales_frame)
    comparison = compare_segments(sales_frame, profile, "Region", "Revenue", "Order Date")
    assert comparison["best"]["group"] == "North"
    expected = float(sales_frame.loc[sales_frame["Region"] == "North", "Revenue"].sum())
    assert comparison["best"]["value"] == pytest.approx(expected, rel=1e-6)
    assert sum(g["share_pct"] for g in comparison["groups"]) == pytest.approx(100, abs=0.5)


def test_segment_shares_are_suppressed_for_signed_measures():
    frame = pd.DataFrame({
        "Unit": ["A", "B"] * 50,
        "Amount": ([100.0, -80.0] * 50),
    })
    profile = profile_of(frame)
    comparison = compare_segments(frame, profile, "Unit", "Amount")
    assert comparison["shares_valid"] is False
    assert comparison["best"]["share_pct"] is None


def test_concentration_detects_a_dominant_group():
    frame = pd.DataFrame({
        "Customer": ["Big"] * 70 + [f"Small{i}" for i in range(30)],
        "Revenue": [1000.0] * 70 + [10.0] * 30,
    })
    profile = profile_of(frame)
    analysis = concentration_analysis(frame, profile, "Customer", "Revenue")
    assert analysis["is_risk"]
    assert analysis["top1_pct"] > 90
    assert analysis["groups_for_80pct"] == 1
    assert analysis["hhi"] > 2500


def test_concentration_skipped_for_non_additive_measures(sales_frame):
    profile = profile_of(sales_frame)
    assert concentration_analysis(sales_frame, profile, "Region", "Rating") is None


def test_even_distribution_is_not_a_concentration_risk():
    frame = pd.DataFrame({
        "Region": [f"R{i % 10}" for i in range(200)], "Revenue": [100.0] * 200,
    })
    analysis = concentration_analysis(frame, profile_of(frame), "Region", "Revenue")
    assert analysis["is_risk"] is False


# --- distributions -----------------------------------------------------------

def test_distribution_statistics_and_skew_interpretation():
    rng = np.random.default_rng(4)
    values = np.concatenate([rng.normal(50, 5, 900), rng.normal(400, 40, 100)])
    stats = describe_numeric(pd.Series(values))
    assert stats["mean"] > stats["median"]
    assert stats["skewness"] > 1
    interpretation = interpret_distribution("Salary", stats, P.DECIMAL)
    assert interpretation is not None
    assert "median" in interpretation["narrative"]
    assert "right-skewed" in interpretation["shape"]
    assert len(histogram(pd.Series(values))) > 3


def test_symmetric_distribution_needs_no_commentary():
    rng = np.random.default_rng(2)
    stats = describe_numeric(pd.Series(rng.normal(100, 10, 2000)))
    assert interpret_distribution("Value", stats, P.DECIMAL) is None
