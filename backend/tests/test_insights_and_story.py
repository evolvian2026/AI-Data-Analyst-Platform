"""Insight engine and Data Story: ranking, evidence, and no fabricated numbers."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from app.engines import insights as I
from app.engines import narrative
from app.engines.ai_provider import narrate, verify_against_facts
from app.engines.recommendations import PRIORITY_ORDER, build_briefing, build_recommendations
from app.engines.story import SECTIONS, build_story


def test_insights_are_ranked_by_priority_score(sales_analysis):
    insights = sales_analysis["insights"]
    assert insights
    scores = [i["priority"]["score"] for i in insights]
    assert scores == sorted(scores, reverse=True)
    assert [i["rank"] for i in insights] == list(range(1, len(insights) + 1))


def test_priority_score_uses_the_six_specified_components(sales_analysis):
    expected = {"magnitude", "unusualness", "relevance", "confidence", "coverage",
                "analytical_importance"}
    for insight in sales_analysis["insights"]:
        assert set(insight["priority"]["components"]) == expected
        assert insight["priority"]["score"] == pytest.approx(
            sum(insight["priority"]["components"].values()), abs=0.2
        )


def test_a_large_decline_outranks_a_trivial_change():
    """Revenue dropping 32% must sort above a 1.1% move in a minor measure."""
    builder = I.InsightBuilder()
    big = builder.add(
        insight_type=I.TREND, headline="Revenue fell 32%", fact="f", interpretation="i",
        recommendation="r", confidence=I.HIGH, confidence_reason="c",
        evidence={"metric": "Revenue", "records_used": 1000},
        components=I._components(24, 18, 20, 15, 10, 18), subject="Revenue",
    )
    small = builder.add(
        insight_type=I.TREND, headline="Average order value rose 1.1%", fact="f",
        interpretation="i", recommendation="r", confidence=I.MEDIUM, confidence_reason="c",
        evidence={"metric": "AOV", "records_used": 1000},
        components=I._components(1, 2, 9, 9, 6, 6), subject="AOV",
    )
    assert big["priority"]["score"] > small["priority"]["score"]


def test_every_insight_separates_fact_interpretation_and_recommendation(sales_analysis):
    for insight in sales_analysis["insights"]:
        assert insight["fact"].strip()
        assert insight["interpretation"].strip()
        assert insight["recommendation"].strip()
        assert insight["fact"] != insight["interpretation"]
        assert insight["confidence"] in {"high", "medium", "low"}
        assert insight["confidence_reason"].strip()


def test_every_insight_carries_traceable_evidence(sales_analysis):
    columns = {c["name"] for c in sales_analysis["profile"]["columns"]}
    for insight in sales_analysis["insights"]:
        evidence = insight["evidence"]
        assert evidence.get("calculation"), f"{insight['id']} has no calculation"
        assert evidence.get("records_used") is not None
        for column in evidence.get("source_columns") or []:
            assert column in columns, f"{insight['id']} cites unknown column {column}"


def test_insight_types_cover_the_specified_taxonomy(sales_analysis):
    allowed = {I.PERFORMANCE, I.TREND, I.DRIVER, I.ANOMALY, I.RISK, I.OPPORTUNITY,
               I.DATA_QUALITY, I.RELATIONSHIP, I.DISTRIBUTION}
    found = {i["type"] for i in sales_analysis["insights"]}
    assert found <= allowed
    assert len(found) >= 3, "a rich dataset should surface several kinds of finding"


def test_low_confidence_claims_are_never_stated_as_fact(sales_analysis):
    hedges = ("appears", "may", "might", "suggest", "coincid", "possible", "could",
              "not causation", "association", "likely", "unlikely")
    for insight in sales_analysis["insights"]:
        if insight["confidence"] in {"medium", "low"}:
            text = (insight["interpretation"] + " " + insight["confidence_reason"]).lower()
            assert any(word in text for word in hedges), insight["headline"]


def test_driver_insights_never_claim_causation(sales_analysis):
    for insight in sales_analysis["insights"]:
        if insight["type"] == I.DRIVER:
            combined = (insight["fact"] + insight["interpretation"]).lower()
            assert "caused by" not in combined
            assert "because of" not in combined


def test_insights_are_deduplicated(sales_analysis):
    keys = [(i["type"], i["subject"].lower()) for i in sales_analysis["insights"]]
    assert len(keys) == len(set(keys))


# --- Data Story --------------------------------------------------------------

def test_story_follows_the_specified_section_order(sales_analysis):
    story = sales_analysis["story"]
    order = [s["key"] for s in story["sections"]]
    expected = [s["key"] for s in SECTIONS]
    positions = [expected.index(key) for key in order]
    assert positions == sorted(positions), "sections must keep the specified order"
    assert order[0] == "executive_summary"
    assert "next_questions" in order


def test_story_cards_carry_evidence_and_confidence(sales_analysis):
    cards = sales_analysis["story"]["cards"]
    assert cards
    for card in cards:
        assert card["headline"].strip()
        assert card["confidence"] in {"high", "medium", "low"}
        assert card["evidence"].get("calculation")
        assert card["position"] >= 1
    assert cards[-1]["position"] == len(cards)


def test_important_story_cards_have_supporting_evidence(sales_analysis):
    """A claim in the story must point at a chart, a KPI or a calculation."""
    for card in sales_analysis["story"]["cards"]:
        has_evidence = bool(
            card.get("chart_id") or card.get("kpi") or card.get("supporting_kpi")
            or card["evidence"].get("calculation")
        )
        assert has_evidence, card["headline"]


def test_executive_summary_is_three_to_six_sentences(sales_analysis):
    narrative_text = sales_analysis["story"]["sections"][0]["narrative"]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", narrative_text.strip()) if s]
    assert 3 <= len(sentences) <= 6


def test_story_chart_references_resolve(sales_analysis):
    chart_ids = {c["id"] for c in sales_analysis["charts"]}
    for card in sales_analysis["story"]["cards"]:
        if card.get("chart_id"):
            assert card["chart_id"] in chart_ids


def test_story_score_is_explained(sales_analysis):
    score = sales_analysis["story_score"]
    assert 0 <= score["score"] <= 100
    assert score["label"] in {"Rich", "Strong", "Moderate", "Limited"}
    assert score["explanation"]
    assert set(score["components"]) == {
        "data_completeness", "meaningful_patterns", "statistical_strength",
        "insight_confidence", "analytical_coverage",
    }


# --- numbers must come from the engine ---------------------------------------

def _numbers(text: str) -> set[float]:
    found = set()
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            found.add(round(float(token.replace(",", "")), 4))
        except ValueError:
            continue
    return found


def test_story_numbers_appear_in_the_underlying_evidence(sales_analysis):
    """Nothing in the narrative may contain a figure the engine did not produce."""
    for insight in sales_analysis["insights"]:
        evidence_text = " ".join(
            str(v) for v in [
                insight["evidence"].get("formatted_value"),
                insight["evidence"].get("value"),
                insight["evidence"].get("records_used"),
                insight["evidence"].get("math", {}),
                insight["evidence"].get("comparison", {}),
                insight["evidence"].get("statistics", {}),
                insight["evidence"].get("aggregation", []),
                insight["fact"],
            ]
        )
        available = _numbers(evidence_text)
        for number in _numbers(insight["headline"]):
            assert any(
                abs(number - candidate) <= max(abs(candidate) * 0.02, 0.05)
                for candidate in available
            ), f"{insight['id']} headline number {number} is not in its evidence"


def test_ai_verification_rejects_unsupported_numbers():
    ok, unsupported = verify_against_facts("Revenue rose 18.4% to 55.33M", "18.4 55.33")
    assert ok and not unsupported
    ok, unsupported = verify_against_facts("Revenue rose 41.2% to 91M", "18.4 55.33")
    assert not ok
    assert set(unsupported) == {"41.2", "91"}


def test_narration_falls_back_to_the_engine_without_a_provider():
    result = narrate("Rewrite this", {"revenue": 100}, "Revenue is 100.")
    assert result["text"] == "Revenue is 100."
    assert result["source"] == "deterministic"
    assert result["verified"] is True


# --- recommendations and briefing ---------------------------------------------

def test_recommendations_are_specific_and_prioritised(sales_analysis):
    recommendations = sales_analysis["recommendations"]
    assert recommendations
    priorities = [PRIORITY_ORDER[r["priority"]] for r in recommendations]
    assert priorities == sorted(priorities)
    for recommendation in recommendations:
        assert len(recommendation["action"]) > 30, "recommendations must not be generic"
        assert recommendation["rationale"]
        assert recommendation["priority_meaning"]
        assert recommendation["evidence"].get("calculation")


def test_recommendations_are_unique(sales_analysis):
    actions = [r["action"].lower() for r in sales_analysis["recommendations"]]
    assert len(actions) == len(set(actions))


def test_briefing_is_management_ready(sales_analysis):
    briefing = sales_analysis["briefing"]
    assert briefing["status"] in {"Positive", "Neutral", "Concerning"}
    assert briefing["status_reason"]
    for key in ("wins", "concerns", "trends", "opportunities", "actions", "key_numbers"):
        assert key in briefing
        assert len(briefing[key]) <= 6
    assert briefing["data_quality"]["score"] is not None


def test_audience_depth_changes_the_narration(sales_analysis):
    insight = sales_analysis["insights"][0]
    executive = narrative.adapt_for_audience(insight, "executive")
    analyst = narrative.adapt_for_audience(insight, "analyst")
    assert len(analyst["body"]) > len(executive["body"])
    assert "Method" in analyst["body"] or "Confidence" in analyst["body"]
    assert executive["headline"] == analyst["headline"], "the facts must not change"


def test_dataset_summary_is_generated_from_the_profile(sales_analysis):
    summary = sales_analysis["summary"]
    assert f"{sales_analysis['profile']['row_count']:,}" in summary
    assert str(sales_analysis["profile"]["column_count"]) in summary
    assert "measure" in summary and "dimension" in summary


def test_next_questions_reference_real_columns(sales_analysis):
    columns = {c["name"].lower() for c in sales_analysis["profile"]["columns"]}
    questions = sales_analysis["next_questions"]
    assert questions
    mentioning = [q for q in questions if any(c in q.lower() for c in columns)]
    assert mentioning, "follow-up questions should be built from this dataset's columns"
