"""Propose-and-confirm cleaning, and column classification overrides.

Both features let a user change how their data is interpreted. The tests below
mostly assert restraint: nothing is corrected without being accepted, the
uploaded file is never touched, and a correction the data cannot support is
refused rather than accommodated.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

from app.engines import cleaning as C
from app.engines import profiler as P
from app.engines.excel_parser import read_workbook
from app.engines.orchestrator import analyze_workbook, prepare_frame


@pytest.fixture(scope="module")
def messy_workbook() -> bytes:
    frame = pd.DataFrame({
        "Cust ID": ["C001", "C002", "C003", "C003", "C005", None, "C007", "C008"] * 4,
        "Region": ["North", "north", " North ", "South", "SOUTH", "East", None, "East"] * 4,
        "Amount": ["1200", "2400", "not a number", "900", "1100", "5600", "700", "800"] * 4,
        "Joined": ["2024-01-15", "2024-02-20", "bad date", "2024-04-02",
                   "2024-05-11", "2024-06-30", "2024-07-04", "2024-08-19"] * 4,
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        frame.to_excel(writer, sheet_name="Messy", index=False)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def messy_analysis(messy_workbook) -> dict:
    return analyze_workbook(messy_workbook, "messy.xlsx")


@pytest.fixture(scope="module")
def full_recipe(messy_analysis) -> list[dict]:
    return [
        {"id": p["id"], "type": p["type"], "column": p["column"], "title": p["title"],
         "params": p["params"]}
        for p in messy_analysis["cleaning_proposals"]
    ]


# --- proposals --------------------------------------------------------------

def test_proposals_are_generated_for_the_problems_that_exist(messy_analysis):
    kinds = {p["type"] for p in messy_analysis["cleaning_proposals"]}
    assert C.STANDARDIZE_CATEGORIES in kinds
    assert C.PARSE_NUMERIC in kinds
    assert C.PARSE_DATES in kinds
    assert C.DROP_DUPLICATE_ROWS in kinds


def test_a_clean_dataset_gets_no_proposals(sales_analysis):
    assert sales_analysis["cleaning_proposals"] == []


def test_every_proposal_states_its_cost_and_shows_real_examples(messy_analysis):
    for proposal in messy_analysis["cleaning_proposals"]:
        assert proposal["rows_affected"] > 0
        assert proposal["risk"]
        assert proposal["description"]
        assert isinstance(proposal["data_loss"], bool)
        if proposal["type"] != C.DROP_DUPLICATE_ROWS:
            assert proposal["examples"]


def test_a_lossy_proposal_says_so(messy_analysis):
    lossy = [p for p in messy_analysis["cleaning_proposals"] if p["data_loss"]]
    assert lossy
    for proposal in lossy:
        assert "discarded" in proposal["risk"] or "fall by" in proposal["risk"]


def test_nothing_is_applied_until_it_is_accepted(messy_analysis):
    """Proposing is not doing: the untouched analysis still shows the problems."""
    assert messy_analysis["cleaning"] is None
    assert messy_analysis["quality"]["score"] < 80


def test_the_canonical_spelling_is_the_one_most_used(messy_analysis):
    standardise = next(p for p in messy_analysis["cleaning_proposals"]
                       if p["type"] == C.STANDARDIZE_CATEGORIES)
    # "North" appears three times (including the whitespace variant the parser
    # trims); "north" once. The frequent spelling wins.
    assert standardise["params"]["mapping"]["north"] == "North"


# --- application ------------------------------------------------------------

def test_accepting_the_proposals_improves_quality(messy_workbook, messy_analysis, full_recipe):
    cleaned = analyze_workbook(messy_workbook, "messy.xlsx", config={"cleaning": full_recipe})
    assert cleaned["quality"]["score"] > messy_analysis["quality"]["score"]
    assert cleaned["cleaning"]["applied_count"] == len(full_recipe)


def test_the_original_frame_is_never_mutated(messy_workbook, full_recipe):
    frames, _, _ = read_workbook(messy_workbook, "messy.xlsx")
    original = frames["Messy"]
    before = original.copy(deep=True)
    cleaned, _ = C.apply_recipe(original, full_recipe)
    pd.testing.assert_frame_equal(original, before)
    assert len(cleaned) < len(original)


def test_removing_the_recipe_restores_the_original_analysis(messy_workbook, messy_analysis,
                                                            full_recipe):
    analyze_workbook(messy_workbook, "messy.xlsx", config={"cleaning": full_recipe})
    restored = analyze_workbook(messy_workbook, "messy.xlsx", config={"cleaning": []})
    assert restored["quality"]["score"] == messy_analysis["quality"]["score"]
    assert restored["profile"]["row_count"] == messy_analysis["profile"]["row_count"]


def test_every_applied_step_is_audited(messy_workbook, full_recipe):
    frames, _, _ = read_workbook(messy_workbook, "messy.xlsx")
    _, context = prepare_frame(frames, None, {"cleaning": full_recipe})
    audit = context["cleaning"]
    assert audit["applied_count"] == len(full_recipe)
    assert audit["rows_removed"] > 0
    for step in audit["steps"]:
        assert step["note"]
    assert "uploaded file itself is unchanged" in audit["statement"]


def test_a_fix_for_a_missing_column_is_skipped_not_fatal(messy_workbook):
    frames, _, _ = read_workbook(messy_workbook, "messy.xlsx")
    cleaned, audit = C.apply_recipe(frames["Messy"], [
        {"id": "x", "type": C.PARSE_NUMERIC, "column": "Nonexistent", "params": {}},
    ])
    assert len(cleaned) == len(frames["Messy"])
    assert audit[0]["applied"] is False
    assert "not present" in audit[0]["note"]


def test_standardisation_merges_the_variants(messy_workbook, messy_analysis):
    standardise = next(p for p in messy_analysis["cleaning_proposals"]
                       if p["type"] == C.STANDARDIZE_CATEGORIES)
    frames, _, _ = read_workbook(messy_workbook, "messy.xlsx")
    cleaned, _ = C.apply_recipe(frames["Messy"], [
        {"id": standardise["id"], "type": standardise["type"], "column": standardise["column"],
         "params": standardise["params"]},
    ])
    before = frames["Messy"]["Region"].dropna().astype(str).nunique()
    after = cleaned["Region"].dropna().astype(str).nunique()
    assert after < before


# --- validation -------------------------------------------------------------

def test_an_unknown_fix_type_is_rejected():
    errors = C.validate_recipe([{"id": "x", "type": "drop_table", "column": "Region"}])
    assert errors and "unknown fix type" in errors[0]


def test_a_standardisation_without_a_mapping_is_rejected():
    errors = C.validate_recipe([
        {"id": "x", "type": C.STANDARDIZE_CATEGORIES, "column": "Region", "params": {}},
    ])
    assert errors and "mapping" in errors[0]


def test_duplicate_fixes_are_rejected():
    step = {"id": "same", "type": C.PARSE_NUMERIC, "column": "Amount", "params": {}}
    assert C.validate_recipe([step, dict(step)])


# --- column classification overrides ---------------------------------------

def test_a_measure_can_be_switched_from_summed_to_averaged(sales_workbook, sales_analysis):
    corrected = analyze_workbook(sales_workbook, "sales.xlsx", config={
        "column_overrides": {"Units": {"aggregation": "mean"}},
    })
    column = next(c for c in corrected["profile"]["columns"] if c["name"] == "Units")
    assert column["aggregation"] == "mean"
    assert column["additive"] is False
    assert "corrected by a user" in " ".join(column["notes"])
    # The correction has to reach the numbers, not just the profile.
    units_trend = next((t for t in corrected["trends"] if t["measure"] == "Units"), None)
    if units_trend:
        assert units_trend["aggregation"] == "mean"


def test_a_column_can_be_demoted_from_measure_to_dimension(sales_workbook):
    corrected = analyze_workbook(sales_workbook, "sales.xlsx", config={
        "column_overrides": {"Rating": {"role": "dimension"}},
    })
    assert "Rating" in corrected["profile"]["roles"]["dimension"]
    assert "Rating" not in corrected["profile"]["roles"]["measure"]
    assert "Rating" not in corrected["ranked_measures"]


def test_text_cannot_be_relabelled_as_a_measure(sales_analysis):
    errors = P.validate_overrides({"Region": {"role": "measure"}}, sales_analysis["profile"])
    assert errors
    assert "cannot be used as a measure" in errors[0]


def test_the_offered_options_exclude_what_the_data_cannot_support(sales_analysis):
    options = {o["column"]: o for o in sales_analysis["column_options"]}
    assert "measure" not in options["Region"]["roles"]
    assert "measure" in options["Revenue"]["roles"]
    assert options["Revenue"]["aggregations"] == ["mean", "sum"]
    assert options["Region"]["blocked"]


def test_an_unknown_column_is_rejected(sales_analysis):
    errors = P.validate_overrides({"Nope": {"role": "measure"}}, sales_analysis["profile"])
    assert errors and "not a column" in errors[0]


def test_an_override_is_recorded_on_the_profile(sales_workbook):
    corrected = analyze_workbook(sales_workbook, "sales.xlsx", config={
        "column_overrides": {"Units": {"aggregation": "mean"}},
    })
    assert corrected["profile"]["overrides_applied"] == ["Units"]
