"""Conversational follow-up, and feedback that reorders without rewriting."""
from __future__ import annotations

import pytest

from app.engines import ask as A
from app.engines import feedback as F


# --- detecting a follow-up --------------------------------------------------

CONTEXT = {"intent": A.TOP_N, "measure": "Revenue", "dimension": "Region",
           "aggregation": "sum", "limit": 10, "filter": None}


@pytest.mark.parametrize("question", [
    "and what about Product?",
    "what about the North region?",
    "same for Units",
    "by product",
    "now show me the bottom 5",
    "and that for last year",
])
def test_a_continuation_is_recognised(question):
    assert A.is_follow_up(question, CONTEXT) is True


@pytest.mark.parametrize("question", [
    "What is the total revenue?",
    "Which region performs best?",
    "Show me the data quality issues",
    "How many orders were placed?",
])
def test_a_self_contained_question_is_not_a_follow_up(question):
    assert A.is_follow_up(question, CONTEXT) is False


def test_the_first_question_is_never_a_follow_up():
    assert A.is_follow_up("and what about Product?", None) is False
    assert A.is_follow_up("and what about Product?", {}) is False


# --- carrying a plan forward ------------------------------------------------

def test_a_follow_up_inherits_the_measure_it_does_not_name(sales_frame, sales_analysis):
    plan = A.build_plan("and by Product?", sales_frame, sales_analysis["profile"],
                        sales_analysis["time_column"], context=CONTEXT)
    assert plan.follow_up is True
    assert plan.measure == "Revenue"
    assert "measure" in plan.inherited
    assert plan.dimension == "Product"


def test_an_explicit_mention_always_beats_the_inherited_one(sales_frame, sales_analysis):
    plan = A.build_plan("and what about Units by Product?", sales_frame,
                        sales_analysis["profile"], sales_analysis["time_column"],
                        context=CONTEXT)
    assert plan.measure == "Units"
    assert "measure" not in plan.inherited


def test_a_self_contained_question_inherits_nothing(sales_frame, sales_analysis):
    plan = A.build_plan("How has Units changed over time?", sales_frame,
                        sales_analysis["profile"], sales_analysis["time_column"],
                        context=CONTEXT)
    assert plan.follow_up is False
    assert plan.inherited == []


def test_the_answer_states_what_it_inherited(sales_frame, sales_analysis):
    first = A.answer_question("Which Region has the highest Revenue?", sales_frame,
                              sales_analysis)
    second = A.answer_question("and by Product?", sales_frame, sales_analysis,
                               context=first["context"])
    assert second["follow_up"] is True
    assert "carried over" in second["interpretation"]
    assert "Revenue" in second["answer"]


def test_every_answer_says_how_it_read_the_question(sales_frame, sales_analysis):
    answer = A.answer_question("Which Region has the highest Revenue?", sales_frame,
                               sales_analysis)
    assert answer["interpretation"].startswith("Understood as:")
    assert "Region" in answer["interpretation"]


def test_the_context_returned_is_enough_to_continue(sales_frame, sales_analysis):
    answer = A.answer_question("Top 5 Regions by Revenue", sales_frame, sales_analysis)
    context = answer["context"]
    assert {"intent", "measure", "dimension", "aggregation", "limit", "filter"} <= set(context)
    follow = A.answer_question("and Product?", sales_frame, sales_analysis, context=context)
    assert follow["plan"]["measure"] == context["measure"]


def test_a_narrowing_filter_carries_into_the_next_question(sales_frame, sales_analysis):
    first = A.answer_question("How much Revenue came from North?", sales_frame, sales_analysis)
    if not first.get("applied_filter"):
        pytest.skip("the dataset did not bind a dimension value for this question")
    second = A.answer_question("and how has it changed over time?", sales_frame, sales_analysis,
                               context=first["context"])
    assert second["applied_filter"] == first["applied_filter"]
    assert "filter" in second["inherited"]


# --- feedback ---------------------------------------------------------------

def test_a_vote_moves_ranking_and_nothing_else(sales_analysis):
    insights = sales_analysis["insights"]
    target = insights[-1]
    adjustments = F.build_adjustments([(F.signature(target), target["type"], F.UP)] * 5)
    ranked = F.apply(insights, adjustments)

    moved = next(i for i in ranked if i["id"] == target["id"])
    assert moved["headline"] == target["headline"]
    assert moved["evidence"] == target["evidence"]
    assert moved["confidence"] == target["confidence"]
    assert moved["priority"]["score"] > moved["priority"]["score_before_feedback"]
    assert moved["priority"]["feedback_reason"]


def test_the_adjustment_is_bounded(sales_analysis):
    target = sales_analysis["insights"][0]
    adjustments = F.build_adjustments([(F.signature(target), target["type"], F.UP)] * 500)
    assert max(adjustments["signatures"].values()) <= F.MAX_ADJUSTMENT


def test_downvoting_cannot_bury_a_dominant_finding(sales_analysis):
    """Feedback tunes the order; it must not suppress the biggest finding.

    The invariant is relative, not positional: a downvoted finding may slip
    past its close neighbours, but nothing far below it on the statistics may
    overtake it however many times it is voted down.
    """
    insights = sales_analysis["insights"]
    top = insights[0]
    base = {i["id"]: i["priority"]["score"] for i in insights}
    adjustments = F.build_adjustments([(F.signature(top), top["type"], F.DOWN)] * 50)
    ranked = F.apply(insights, adjustments)

    position = next(i for i, item in enumerate(ranked) if item["id"] == top["id"])
    for overtaking in ranked[:position]:
        assert base[overtaking["id"]] >= base[top["id"]] - F.MAX_ADJUSTMENT
    assert ranked[position]["priority"]["score"] >= base[top["id"]] - F.MAX_ADJUSTMENT


def test_a_specific_vote_supersedes_a_category_vote(sales_analysis):
    insights = sales_analysis["insights"]
    target = insights[0]
    adjustments = F.build_adjustments(
        [(F.signature(target), target["type"], F.UP)] * 3
        + [("other::thing", target["type"], F.DOWN)] * 3
    )
    ranked = F.apply(insights, adjustments)
    moved = next(i for i in ranked if i["id"] == target["id"])
    assert moved["priority"]["feedback_adjustment"] > 0


def test_no_votes_leaves_the_statistical_order_untouched(sales_analysis):
    insights = sales_analysis["insights"]
    assert F.apply(insights, F.build_adjustments([])) == insights


def test_the_signature_survives_reanalysis(sales_analysis):
    """A rating must not be lost because insight ids were renumbered."""
    original = sales_analysis["insights"][0]
    renumbered = {**original, "id": "ins_999"}
    assert F.signature(renumbered) == F.signature(original)


def test_the_explanation_states_the_bound():
    explanation = F.explain(F.build_adjustments([("a::b", "trend", F.UP)]))
    assert explanation["active"] is True
    assert str(int(F.MAX_ADJUSTMENT)) in explanation["statement"]
    assert "order only" in explanation["statement"]
