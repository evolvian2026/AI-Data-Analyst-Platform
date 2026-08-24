"""Data profiling: type detection, missing values, duplicates, classification."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines import profiler as P
from app.engines.derived import detect_derived_columns
from app.engines.quality import assess_quality, outlier_scan


def profile_of(frame: pd.DataFrame) -> dict:
    result = P.profile_dataframe(frame)
    result.pop("profiles", None)
    return result


def column(profile: dict, name: str) -> dict:
    return next(c for c in profile["columns"] if c["name"] == name)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["₹125,000", "₹98,000", "₹250,500"], P.CURRENCY),
        (["18.5%", "7.2%", "22.0%"], P.PERCENTAGE),
        (["2026-08-24", "2026-08-25", "2026-09-01"], P.DATE),
        (["North", "South", "East", "West", "North"], P.GEOGRAPHIC),
        (["a@b.com", "c@d.com", "e@f.com"], P.EMAIL),
        (["https://a.com", "https://b.com", "https://c.com"], P.URL),
        (["yes", "no", "yes", "no"], P.BOOLEAN),
        ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], P.INTEGER),
        ([1.5, 2.25, 3.75, 9.1, 4.4], P.DECIMAL),
        (["09:30", "14:45", "23:15"], P.TIME),
    ],
)
def test_semantic_type_is_inferred_from_values(values, expected):
    series = pd.Series(values * 6)
    detected, confidence, _symbol, _notes = P.infer_semantic_type(series, "Column")
    assert detected == expected
    assert confidence > 0.5


def test_repeated_codes_are_categorical_not_identifiers():
    """STU001 repeated across rows is a category; unique per row it is a key."""
    repeated = pd.Series(["STU001", "STU002", "STU003", "STU004"] * 6)
    assert P.infer_semantic_type(repeated, "Code")[0] == P.CATEGORICAL

    unique = pd.Series([f"STU{i:05d}" for i in range(60)])
    assert P.infer_semantic_type(unique, "Student ID")[0] == P.IDENTIFIER


def test_semantic_types_ignore_misleading_column_names():
    """Detection reads the values; a name alone must not decide the type."""
    series = pd.Series(["North", "South", "East"] * 10)
    detected, _c, _s, _n = P.infer_semantic_type(series, "Revenue")
    assert detected in {P.CATEGORICAL, P.GEOGRAPHIC}


def test_currency_symbol_is_captured(messy_frame):
    profile = profile_of(messy_frame)
    assert profile["currency_symbol"] == "₹"
    assert column(profile, "Amount")["semantic_type"] == P.CURRENCY


def test_roles_split_measures_dimensions_time_and_identifiers(sales_frame):
    profile = profile_of(sales_frame)
    roles = profile["roles"]
    assert "Revenue" in roles[P.MEASURE]
    assert "Region" in roles[P.DIMENSION]
    assert "Order Date" in roles[P.TIME_DIMENSION]
    assert "Order ID" in roles[P.IDENTIFIER_ROLE]
    assert P.primary_time_column(profile) == "Order Date"


def test_aggregation_policy_averages_non_additive_measures(sales_frame):
    profile = profile_of(sales_frame)
    assert column(profile, "Revenue")["aggregation"] == "sum"
    assert column(profile, "Revenue")["additive"] is True
    assert column(profile, "Rating")["aggregation"] == "mean"
    assert column(profile, "Rating")["additive"] is False


def test_percentage_and_year_handling():
    assert P.default_aggregation("Attendance %", P.DECIMAL) == "mean"
    parsed = P.to_datetime_series(pd.Series([2023, 2024, 2025]))
    assert parsed.dt.year.tolist() == [2023, 2024, 2025]


def test_numeric_conversion_understands_currency_and_percent():
    values = P.to_numeric_series(pd.Series(["₹1,200", "(500)", "12.5%", "bad", None]))
    assert values.tolist()[:3] == [1200.0, -500.0, 12.5]
    assert pd.isna(values.iloc[3]) and pd.isna(values.iloc[4])


def test_missing_and_constant_columns_are_reported(messy_frame):
    profile = profile_of(messy_frame)
    assert column(profile, "Constant")["is_constant"] is True
    assert column(profile, "Cust ID")["missing"] == 1
    assert column(profile, "Region")["missing_pct"] > 0


def test_quality_flags_duplicates_inconsistency_and_conversion_failures(messy_frame):
    profile = profile_of(messy_frame)
    quality = assess_quality(messy_frame, profile, outlier_scan(messy_frame, profile))
    kinds = {issue["type"] for issue in quality["issues"]}
    assert "duplicate_identifier" in kinds
    assert "inconsistent_categories" in kinds
    assert "invalid_numeric" in kinds
    assert "constant_column" in kinds
    assert 0 <= quality["score"] <= 100
    assert quality["grade"] in {"Excellent", "Good", "Fair", "Poor", "Critical"}
    assert quality["explanation"]


def test_quality_issues_explain_their_analytical_impact(messy_frame):
    profile = profile_of(messy_frame)
    quality = assess_quality(messy_frame, profile, outlier_scan(messy_frame, profile))
    for issue in quality["issues"]:
        assert issue["impact"], f"{issue['type']} has no stated impact"
        # An impact must say what it does to the analysis, not restate the count.
        assert issue["impact"] != issue["detail"]


def test_quality_score_is_high_for_a_clean_dataset(sales_frame):
    profile = profile_of(sales_frame)
    quality = assess_quality(sales_frame, profile, outlier_scan(sales_frame, profile))
    assert quality["score"] > 90
    assert quality["metrics"]["duplicate_rows"] == 0


def test_duplicate_rows_are_counted():
    frame = pd.DataFrame({"A": [1, 1, 2, 3], "B": ["x", "x", "y", "z"]})
    profile = profile_of(frame)
    quality = assess_quality(frame, profile, {"total": 0, "columns": {}})
    assert quality["metrics"]["duplicate_rows"] == 1


def test_derived_columns_are_detected(sales_frame):
    profile = profile_of(sales_frame)
    findings = detect_derived_columns(sales_frame, profile)
    formulas = {f["formula"] for f in findings}
    assert any("Profit" in f or "Cost" in f or "Revenue" in f for f in formulas)
    assert all(f["match_ratio"] >= 0.97 for f in findings)


def test_profiling_samples_large_frames():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"V": rng.normal(0, 1, 120_000), "C": rng.choice(list("abc"), 120_000)})
    profile = P.profile_dataframe(frame, sample_rows=10_000)
    assert profile["sampled"] is True
    assert profile["sample_rows"] == 10_000
    assert profile["row_count"] == 120_000
