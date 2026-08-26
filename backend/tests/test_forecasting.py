"""Projection: what it produces, and - just as important - what it refuses to.

A forecast is the one place in this platform where a number appears that was
never measured. These tests exist to hold that boundary: the method has to be
chosen for a reason, the projection has to be withheld when the data cannot
support one, and a projected value must never leak into anything that reports
what actually happened.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines.forecast import MIN_PERIODS, build_forecast, forecast_trends
from app.engines.trend import _label

SEASON = [30, 20, 0, -10, -25, -30, -20, -5, 10, 20, 25, 28]


def points(values, freq="MS", start="2022-01-01"):
    index = pd.date_range(start, periods=len(values), freq=freq)
    return [
        {"label": _label(period, freq), "iso": period.isoformat(),
         "value": float(value), "records": 10}
        for period, value in zip(index, values)
    ]


@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(11)


# --- method selection -------------------------------------------------------

def test_a_clear_trend_is_extrapolated(rng):
    forecast = build_forecast(points(100 + 5 * np.arange(30) + rng.normal(0, 4, 30)), "MS",
                              measure="Revenue")
    assert forecast["available"]
    assert forecast["method"] == "linear_trend"
    assert forecast["confidence"] == "high"
    # The projection continues the slope rather than repeating the last value.
    values = [p["value"] for p in forecast["points"]]
    assert values == sorted(values)
    assert values[0] > 100 + 5 * 29


def test_no_significant_trend_carries_the_level_forward_instead(rng):
    forecast = build_forecast(points(np.full(30, 100.0) + rng.normal(0, 6, 30)), "MS",
                              measure="Headcount")
    assert forecast["method"] == "level"
    assert forecast["slope_per_period"] == 0.0
    assert any("no statistically significant trend" in c.lower() for c in forecast["caveats"])
    # Every projected period is the same level: it does not invent a direction.
    assert len({round(p["value"], 6) for p in forecast["points"]}) == 1


def test_a_seasonal_series_is_projected_with_its_season(rng):
    values = 200 + np.tile(SEASON, 3) + rng.normal(0, 5, 36)
    forecast = build_forecast(points(values), "MS", measure="Units")
    assert forecast["seasonal"] is True
    assert forecast["method"] == "seasonal_level"
    # January is a peak month in SEASON, so the first projected period must sit
    # above the recent average rather than at it.
    assert forecast["points"][0]["value"] > float(np.mean(values[-6:]))


def test_two_cycles_of_noise_do_not_become_a_seasonal_pattern(rng):
    """The expensive mistake: 12 monthly offsets fitted to 24 noisy points."""
    forecast = build_forecast(points(100 + 5 * np.arange(24) + rng.normal(0, 4, 24)), "MS",
                              measure="Revenue")
    assert forecast["seasonal"] is False
    assert forecast["method"] == "linear_trend"


# --- refusals ---------------------------------------------------------------

def test_a_short_series_is_not_projected():
    forecast = build_forecast(points([10, 12, 11, 13, 14]), "MS", measure="Revenue")
    assert forecast["available"] is False
    assert str(MIN_PERIODS) in forecast["reason"]


def test_a_volatile_series_is_not_projected(rng):
    """Two guards can catch this - the point is that neither lets it through."""
    forecast = build_forecast(points(np.abs(rng.normal(100, 95, 24))), "MS", measure="Spend")
    assert forecast["available"] is False
    assert len(forecast["reason"]) > 40


def test_extreme_volatility_is_named_as_the_reason(rng):
    forecast = build_forecast(points(rng.lognormal(3, 1.4, 24)), "MS", measure="Spend")
    assert forecast["available"] is False
    assert "varies by" in forecast["reason"]


def test_a_refusal_explains_itself():
    forecast = build_forecast(points([1, 2, 3]), "MS", measure="Revenue")
    assert forecast["available"] is False
    assert len(forecast["reason"]) > 30


# --- honesty ----------------------------------------------------------------

def test_every_projected_point_is_labelled_and_bounded(rng):
    forecast = build_forecast(points(100 + 4 * np.arange(24) + rng.normal(0, 5, 24)), "MS",
                              measure="Revenue")
    for point in forecast["points"]:
        assert point["projected"] is True
        assert point["lower"] <= point["value"] <= point["upper"]
        assert point["formatted_range"]
    assert forecast["interval_pct"] == 90
    assert "not a measured value" in forecast["disclaimer"]


def test_a_non_negative_measure_is_never_projected_below_zero(rng):
    # A steep decline extrapolated far enough crosses zero; a count cannot.
    forecast = build_forecast(points(np.linspace(500, 40, 20) + rng.normal(0, 3, 20)), "MS",
                              measure="Orders", non_negative=True)
    assert forecast["available"]
    assert all(point["value"] >= 0 and point["lower"] >= 0 for point in forecast["points"])


def test_the_horizon_never_exceeds_a_quarter_of_the_history(rng):
    forecast = build_forecast(points(100 + 3 * np.arange(12) + rng.normal(0, 2, 12)), "MS",
                              measure="Revenue")
    assert forecast["horizon"] <= 3


def test_the_basis_names_the_method_and_the_history(rng):
    forecast = build_forecast(points(100 + 3 * np.arange(24) + rng.normal(0, 3, 24)), "MS",
                              measure="Revenue", aggregation="sum")
    assert "24 measured months" in forecast["basis"]
    assert forecast["method_label"].lower() in forecast["basis"].lower()


# --- integration with the analysis -----------------------------------------

def test_projections_never_enter_the_measured_series(sales_analysis):
    """The whole point of keeping them apart: no total can absorb a forecast."""
    for trend in sales_analysis["trends"]:
        for point in trend["points"]:
            assert "projected" not in point
            assert point["value"] is not None


def test_projections_are_a_separate_chart_series(sales_analysis):
    projected_charts = [c for c in sales_analysis["charts"] if c.get("projection")]
    for chart in projected_charts:
        keys = {s["key"] for s in chart["series"]}
        assert "projected" in keys
        assert any(s.get("projected") for s in chart["series"])
        for row in chart["data"]:
            # A row is measured or projected, never counted as both - except the
            # single bridging row that joins the two lines visually.
            if row.get("is_projection"):
                assert row["value"] is None
            elif "projected" in row:
                assert row.get("bridge") is True


def test_kpis_are_calculated_only_from_measured_values(sales_analysis):
    for kpi in sales_analysis["kpis"]["all"]:
        assert "projected" not in str(kpi.get("calculation", "")).lower()
        assert kpi["records_used"] <= sales_analysis["profile"]["row_count"]


def test_forecast_trends_reports_a_reason_for_every_measure_it_skips(sales_analysis):
    results = forecast_trends(sales_analysis["trends"], sales_analysis["profile"])
    assert results
    for result in results:
        assert result["measure"]
        assert result["available"] or result["reason"]
