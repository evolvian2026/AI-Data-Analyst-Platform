"""Comparing two analyses: what changed, and what cannot honestly be compared."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from app.engines import comparison as C
from app.engines.orchestrator import analyze_workbook


def _workbook(months: int, growth: float, seed: int, extra_column: bool = False) -> bytes:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=months * 30, freq="D")
    frame = pd.DataFrame({
        "Order ID": [f"O{i:05d}" for i in range(len(dates))],
        "Order Date": dates,
        "Region": rng.choice(["North", "South", "East", "West"], len(dates),
                             p=[0.4, 0.25, 0.2, 0.15]),
        "Product": rng.choice(["Alpha", "Beta"], len(dates), p=[0.6, 0.4]),
        "Units": rng.integers(1, 20, len(dates)),
        "Revenue": (rng.normal(1000, 150, len(dates))
                    * (1 + growth * np.arange(len(dates)) / len(dates))).round(2),
    })
    if extra_column:
        frame["Discount %"] = rng.uniform(0, 20, len(dates)).round(1)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        frame.to_excel(writer, sheet_name="Sales", index=False)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def earlier() -> dict:
    return analyze_workbook(_workbook(12, 0.1, seed=5), "march.xlsx")


@pytest.fixture(scope="module")
def later() -> dict:
    return analyze_workbook(_workbook(18, 0.4, seed=9), "august.xlsx")


@pytest.fixture(scope="module")
def widened() -> dict:
    return analyze_workbook(_workbook(18, 0.4, seed=9, extra_column=True), "august-plus.xlsx")


@pytest.fixture(scope="module")
def diff(earlier, later) -> dict:
    return C.compare_analyses(earlier, later, "March", "August")


# --- what is comparable -----------------------------------------------------

def test_identical_shapes_are_fully_comparable(earlier, later):
    assert C.signature_overlap(
        C.dataset_signature(earlier), C.dataset_signature(later)
    ) == pytest.approx(100.0)


def test_an_added_column_lowers_comparability_and_is_reported(earlier, widened):
    comparison = C.compare_analyses(earlier, widened)
    assert comparison["comparable_pct"] < 100
    assert "Discount %" in comparison["schema"]["added"]
    assert any("only in the newer dataset" in c for c in comparison["caveats"])


def test_a_metric_present_in_only_one_run_is_reported_not_compared(earlier, widened):
    comparison = C.compare_analyses(earlier, widened)
    new_metrics = [k for k in comparison["kpis"] if k["status"] == "new"]
    assert new_metrics
    for metric in new_metrics:
        assert metric["value_before"] is None
        assert metric["change_pct"] is None
        assert metric["note"]


def test_a_changed_aggregation_makes_a_metric_incomparable(earlier, later):
    """Summing what used to be averaged is not a movement, it is a different number."""
    tampered = {**later, "kpis": {**later["kpis"], "all": [
        {**k, "aggregation": "mean" if k.get("aggregation") == "sum" else "sum"}
        for k in later["kpis"]["all"]
    ]}}
    comparison = C.compare_analyses(earlier, tampered)
    incomparable = [k for k in comparison["kpis"] if k["status"] == "incomparable"]
    assert incomparable
    assert all(k["change_pct"] is None for k in incomparable)
    assert all("not comparable" in k["note"] for k in incomparable)


# --- the diff itself --------------------------------------------------------

def test_row_growth_is_measured_and_stated(diff):
    assert diff["coverage"]["rows_after"] > diff["coverage"]["rows_before"]
    assert diff["coverage"]["rows_delta"] == (
        diff["coverage"]["rows_after"] - diff["coverage"]["rows_before"]
    )
    assert any("records" in line for line in diff["headline"])


def test_kpi_movements_match_the_underlying_values(diff):
    for metric in diff["kpis"]:
        if metric["status"] != "changed" or metric["change_pct"] is None:
            continue
        expected = (metric["value_after"] - metric["value_before"]) / metric["value_before"] * 100
        assert metric["change_pct"] == pytest.approx(expected, abs=0.05)


def test_a_longer_period_is_flagged_before_totals_are_compared(diff):
    assert diff["coverage"]["extends_period"]
    assert any("longer period" in c for c in diff["caveats"])


def test_segment_rank_and_share_shifts_are_reported(diff):
    segments = [s for s in diff["segments"] if s["groups"]]
    assert segments
    for group in segments[0]["groups"]:
        if group["status"] == "changed":
            assert group["rank_before"] and group["rank_after"]


def test_trend_direction_reversals_are_surfaced_first(diff):
    directions = diff["trends"]
    assert directions
    assert directions == sorted(directions, key=lambda t: (not t["reversed"], not t["changed"]))


def test_findings_are_matched_by_subject_not_by_wording(earlier, later):
    """Rephrasing a headline must not read as a finding appearing and vanishing."""
    reworded = {**later, "insights": [
        {**i, "headline": f"REWORDED: {i['headline']}"} for i in later["insights"]
    ]}
    plain = C.compare_analyses(earlier, later)["insights"]["counts"]
    fancy = C.compare_analyses(earlier, reworded)["insights"]["counts"]
    assert plain == fancy


def test_quality_movement_is_reported_with_its_issues(earlier, later):
    comparison = C.compare_analyses(earlier, later)
    quality = comparison["quality"]
    assert quality["score_before"] is not None and quality["score_after"] is not None
    if quality["score_delta"]:
        assert quality["direction"] in {"up", "down"}
    assert isinstance(quality["resolved"], list)
    assert isinstance(quality["introduced"], list)


def test_the_headline_never_states_a_percentage_from_a_zero_baseline(earlier):
    """The class of bug that produces "declined 860%"."""
    zeroed = {**earlier, "kpis": {**earlier["kpis"], "all": [
        {**k, "value": 0.0} for k in earlier["kpis"]["all"]
    ]}}
    comparison = C.compare_analyses(zeroed, earlier)
    for metric in comparison["kpis"]:
        if metric["value_before"] == 0:
            assert metric["change_pct"] is None
            assert "undefined" in metric["note"]


def test_comparing_an_analysis_with_itself_reports_no_movement(later):
    comparison = C.compare_analyses(later, later)
    assert comparison["comparable_pct"] == pytest.approx(100.0)
    assert comparison["coverage"]["rows_delta"] == 0
    assert comparison["insights"]["counts"]["new"] == 0
    assert comparison["insights"]["counts"]["resolved"] == 0
    assert all(not k["material"] or k["status"] != "changed" for k in comparison["kpis"])


def test_the_method_is_stated(diff):
    assert "matched by" in diff["method"]
