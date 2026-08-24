"""Insight discovery, evidence construction and priority ranking.

Every insight is derived from a value the analytics engine already calculated.
The narrative layer never invents a number: each insight carries an evidence
object holding the source columns, the calculation, the values used and the
number of records behind it, which is what the UI shows under
"Why am I seeing this insight?" and "Show the math".
"""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import format_delta, format_value, safe_float

# --- insight types ----------------------------------------------------------
PERFORMANCE = "performance"
TREND = "trend"
DRIVER = "driver"
ANOMALY = "anomaly"
RISK = "risk"
OPPORTUNITY = "opportunity"
DATA_QUALITY = "data_quality"
RELATIONSHIP = "relationship"
DISTRIBUTION = "distribution"

HIGH, MEDIUM, LOW = "high", "medium", "low"

TYPE_LABELS = {
    PERFORMANCE: "Performance",
    TREND: "Trend",
    DRIVER: "Driver",
    ANOMALY: "Anomaly",
    RISK: "Risk",
    OPPORTUNITY: "Opportunity",
    DATA_QUALITY: "Data Quality",
    RELATIONSHIP: "Relationship",
    DISTRIBUTION: "Distribution",
}


class InsightBuilder:
    """Accumulates insights and assigns stable ids."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._counter = itertools.count(1)

    def add(
        self,
        *,
        insight_type: str,
        headline: str,
        fact: str,
        interpretation: str,
        recommendation: str,
        confidence: str,
        confidence_reason: str,
        evidence: dict[str, Any],
        components: dict[str, float],
        so_what: str = "",
        next_questions: list[str] | None = None,
        chart_hint: dict[str, Any] | None = None,
        subject: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        insight = {
            "id": f"ins_{next(self._counter):03d}",
            "type": insight_type,
            "type_label": TYPE_LABELS.get(insight_type, insight_type.title()),
            "headline": headline,
            "fact": fact,
            "interpretation": interpretation,
            "recommendation": recommendation,
            "so_what": so_what,
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "evidence": evidence,
            "priority": {
                "score": round(float(sum(components.values())), 1),
                "components": {k: round(float(v), 1) for k, v in components.items()},
            },
            "next_questions": next_questions or [],
            "chart_hint": chart_hint,
            "chart_id": None,
            "subject": subject,
            "tags": tags or [],
        }
        self._items.append(insight)
        return insight

    @property
    def items(self) -> list[dict[str, Any]]:
        return self._items


def _components(
    magnitude: float, unusualness: float, relevance: float, confidence: float,
    coverage: float, importance: float,
) -> dict[str, float]:
    """Insight Priority Score = the six components from the specification."""
    return {
        "magnitude": min(max(magnitude, 0), 25),
        "unusualness": min(max(unusualness, 0), 20),
        "relevance": min(max(relevance, 0), 20),
        "confidence": min(max(confidence, 0), 15),
        "coverage": min(max(coverage, 0), 10),
        "analytical_importance": min(max(importance, 0), 20),
    }


def _confidence_score(level: str) -> float:
    return {HIGH: 15.0, MEDIUM: 9.0, LOW: 4.0}[level]


def _measure_relevance(name: str) -> float:
    lowered = name.lower()
    if any(t in lowered for t in ("revenue", "sales", "profit", "income", "turnover", "gmv")):
        return 20.0
    if any(t in lowered for t in ("cost", "expense", "spend", "budget", "margin", "attrition",
                                  "churn", "conversion")):
        return 17.0
    if any(t in lowered for t in ("quantity", "units", "orders", "volume", "count", "headcount",
                                  "score", "marks", "salary", "rating")):
        return 13.0
    return 9.0


# --- individual discovery passes -------------------------------------------

def _trend_insights(builder: InsightBuilder, trends: list[dict[str, Any]],
                    profile: dict[str, Any]) -> None:
    currency = profile.get("currency_symbol", "")
    types = {c["name"]: c["semantic_type"] for c in profile["columns"]}

    # Across a dataset, three "this period jumped" findings is plenty.
    sudden_budget = [3]
    for trend in trends:
        measure = trend["measure"]
        semantic = types.get(measure, "")
        classification = trend["classification"]
        direction = classification.get("direction")
        change_pct = trend.get("total_change_pct")
        unit = trend["unit"]
        relevance = _measure_relevance(measure)

        if direction in {"increasing", "decreasing"} and change_pct is not None:
            confidence = (
                HIGH if classification["confidence"] == "high"
                else MEDIUM if classification["confidence"] == "medium" else LOW
            )
            decomposition = trend.get("decomposition") or {}
            aggregation_label = trend.get("aggregation_label", "Total")
            significant = bool(classification.get("p_value") is not None
                               and classification["p_value"] < 0.05)
            fact = (
                f"{aggregation_label} {measure} moved from "
                f"{format_value(trend['first_value'], semantic, currency)} in "
                f"{trend['first_period']} to {format_value(trend['last_value'], semantic, currency)} "
                f"in {trend['last_period']}, a change of {format_delta(change_pct)} across "
                f"{classification['periods']} {unit}s."
            )
            slope = classification.get("slope_pct_per_period")
            r_squared = classification.get("r_squared")
            interpretation = (
                f"The {unit}ly series shows a statistically "
                f"{'significant' if significant else 'weak'} {direction} trend"
                + (f" (slope {slope:+.1f}% of the mean per {unit}"
                   f"{f', r² = {r_squared:.2f}' if r_squared is not None else ''})."
                   if slope is not None else ".")
            )
            if decomposition.get("narrative"):
                interpretation += " " + decomposition["narrative"]
            recommendation = (
                f"Confirm whether the {direction} trend in {measure} is expected, and check which "
                f"segments it is concentrated in before extrapolating it forward."
                if direction == "increasing"
                else f"Investigate the {direction} trend in {measure}: identify which segments and "
                     f"{unit}s contributed most to the decline."
            )
            builder.add(
                insight_type=TREND,
                headline=(
                    (
                        f"{aggregation_label} {measure} is {direction} - "
                        f"{format_delta(change_pct)} over {classification['periods']} {unit}s, "
                        f"driven by record volume"
                    ) if decomposition.get("driver") == "volume" else (
                        f"{aggregation_label} {measure} is {direction} - "
                        f"{format_delta(change_pct)} over {classification['periods']} {unit}s"
                    )
                ),
                fact=fact,
                interpretation=interpretation,
                recommendation=recommendation,
                confidence=confidence,
                confidence_reason=(
                    "Calculated by ordinary least squares regression on the aggregated series; "
                    f"p = {classification['p_value']:.4f}."
                ),
                evidence={
                    "metric": measure,
                    "value": trend["last_value"],
                    "formatted_value": format_value(trend["last_value"], semantic, currency),
                    "comparison": {
                        "label": f"{trend['first_period']} vs {trend['last_period']}",
                        "from": trend["first_value"],
                        "to": trend["last_value"],
                        "change_pct": change_pct,
                    },
                    "source_columns": [measure, trend["time_column"]],
                    "calculation": (
                        f"SUM({measure}) grouped by {unit} of {trend['time_column']}, "
                        f"then linear regression across {classification['periods']} points"
                    ),
                    "math": {
                        "formula": "((Last period − First period) ÷ First period) × 100",
                        "substitution": (
                            f"(({format_value(trend['last_value'], semantic, currency)} − "
                            f"{format_value(trend['first_value'], semantic, currency)}) ÷ "
                            f"{format_value(trend['first_value'], semantic, currency)}) × 100"
                        ),
                        "result": format_delta(change_pct),
                    },
                    "records_used": int(sum(p["records"] for p in trend["points"])),
                    "periods": classification["periods"],
                    "statistics": {
                        "slope_pct_per_period": classification["slope_pct_per_period"],
                        "r_squared": classification["r_squared"],
                        "p_value": classification["p_value"],
                        "volatility_pct": classification["volatility_pct"],
                    },
                    "aggregation": trend["points"],
                },
                components=_components(
                    magnitude=min(abs(change_pct) / 3, 25),
                    unusualness=10 if abs(change_pct) > 20 else 5,
                    relevance=relevance,
                    confidence=_confidence_score(confidence),
                    coverage=10,
                    importance=18 if direction == "decreasing" else 15,
                ),
                so_what=_so_what_trend(measure, direction, change_pct, unit),
                next_questions=[
                    f"Which segments contributed most to the change in {measure}?",
                    f"Is the change in {measure} concentrated in specific {unit}s?",
                    f"Did related measures move in the same direction?",
                ],
                chart_hint={"kind": "trend", "measure": measure},
                subject=measure,
                tags=["trend", direction],
            )

        # Sudden changes
        for change in trend.get("sudden_changes", [])[:2]:
            if sudden_budget[0] <= 0:
                break
            sudden_budget[0] -= 1
            builder.add(
                insight_type=TREND,
                headline=(
                    f"{measure} {change['direction']}d {abs(change['change_pct']):.0f}% in "
                    f"{change['period']}"
                ),
                fact=(
                    f"{measure} moved from "
                    f"{format_value(change['previous_value'], semantic, currency)} in "
                    f"{change['previous_period']} to "
                    f"{format_value(change['value'], semantic, currency)} in {change['period']}, "
                    f"a {change['change_pct']:+.1f}% change."
                ),
                interpretation=(
                    f"The typical {unit}-over-{unit} movement in this series is "
                    f"{change['typical_movement_pct']:.1f}%, so this change is roughly "
                    f"{abs(change['change_pct']) / max(change['typical_movement_pct'], 0.1):.1f}x larger "
                    f"than normal."
                ),
                recommendation=(
                    f"Check what happened in {change['period']} - a one-off event, a data issue, or "
                    f"the start of a new level."
                ),
                confidence=HIGH,
                confidence_reason="Both values are direct sums from the dataset.",
                evidence={
                    "metric": measure,
                    "value": change["value"],
                    "formatted_value": format_value(change["value"], semantic, currency),
                    "comparison": {
                        "label": f"{change['previous_period']} vs {change['period']}",
                        "from": change["previous_value"],
                        "to": change["value"],
                        "change_pct": change["change_pct"],
                    },
                    "source_columns": [measure, trend["time_column"]],
                    "calculation": f"SUM({measure}) per {unit}, consecutive period comparison",
                    "math": {
                        "formula": "((Current − Previous) ÷ Previous) × 100",
                        "substitution": (
                            f"(({format_value(change['value'], semantic, currency)} − "
                            f"{format_value(change['previous_value'], semantic, currency)}) ÷ "
                            f"{format_value(change['previous_value'], semantic, currency)}) × 100"
                        ),
                        "result": f"{change['change_pct']:+.1f}%",
                    },
                    "records_used": int(sum(p["records"] for p in trend["points"])),
                    "aggregation": trend["points"],
                },
                components=_components(
                    magnitude=min(abs(change["change_pct"]) / 2.5, 25),
                    unusualness=16,
                    relevance=relevance,
                    confidence=_confidence_score(HIGH),
                    coverage=6,
                    importance=16 if change["direction"] == "decrease" else 13,
                ),
                so_what=(
                    f"A single-{unit} move of this size materially shifts the {measure} total for the "
                    f"whole period."
                ),
                next_questions=[
                    f"Which segment drove the {change['direction']} in {change['period']}?",
                    f"Did record volume or average {measure} per record change?",
                    f"Has a similar move happened before?",
                ],
                chart_hint={"kind": "trend", "measure": measure},
                # Keyed on the period so the same spike reported across Revenue,
                # Cost and Profit collapses into one finding.
                subject=f"period:{change['period']}",
                tags=["sudden_change"],
            )

        seasonality = trend.get("seasonality")
        if seasonality:
            builder.add(
                insight_type=TREND,
                headline=f"{measure} follows a seasonal pattern peaking in {seasonality['peak']}",
                fact=(
                    f"Across {seasonality['cycles_observed']} cycles, {seasonality['peak']} averages "
                    f"{seasonality['peak_deviation_pct']:+.0f}% versus the overall mean while "
                    f"{seasonality['trough']} averages {seasonality['trough_deviation_pct']:+.0f}%."
                ),
                interpretation=(
                    "A repeating within-year pattern of this size means period-over-period "
                    "comparisons should be made against the same period last year, not the "
                    "previous period."
                ),
                recommendation=(
                    f"Use year-over-year comparisons for {measure} and plan capacity around the "
                    f"{seasonality['peak']} peak."
                ),
                confidence=MEDIUM if seasonality["cycles_observed"] < 3 else HIGH,
                confidence_reason=(
                    f"Based on {seasonality['cycles_observed']} observed cycles; more cycles would "
                    f"strengthen the conclusion."
                ),
                evidence={
                    "metric": measure,
                    "value": seasonality["strength_pct"],
                    "formatted_value": f"{seasonality['strength_pct']:.0f}% swing",
                    "source_columns": [measure, trend["time_column"]],
                    "calculation": "Mean per calendar period ÷ overall mean − 1",
                    "records_used": int(sum(p["records"] for p in trend["points"])),
                    "aggregation": seasonality["profile"],
                },
                components=_components(
                    magnitude=min(seasonality["strength_pct"] / 4, 20),
                    unusualness=8,
                    relevance=relevance,
                    confidence=_confidence_score(MEDIUM),
                    coverage=9,
                    importance=12,
                ),
                so_what=(
                    f"Without adjusting for seasonality, a {seasonality['peak']} figure will look "
                    f"like growth and a {seasonality['trough']} figure like decline."
                ),
                next_questions=[
                    f"Is the seasonal pattern in {measure} consistent across segments?",
                    f"How does the latest cycle compare with the same point last year?",
                ],
                chart_hint={"kind": "seasonality", "measure": measure},
                subject=measure,
                tags=["seasonality"],
            )


def _so_what_trend(measure: str, direction: str, change_pct: float, unit: str) -> str:
    if direction == "increasing":
        return (
            f"If the current rate continues, {measure} would keep compounding at roughly the same "
            f"pace per {unit}; understanding what is driving it makes it repeatable."
        )
    return (
        f"A sustained decline in {measure} compounds: left unaddressed the gap widens every {unit}, "
        f"so identifying the driver early matters more than the size of any single period."
    )


def _segment_insights(builder: InsightBuilder, segments: list[dict[str, Any]],
                      profile: dict[str, Any], row_count: int) -> None:
    currency = profile.get("currency_symbol", "")
    seen_pairs: set[tuple[str, str]] = set()
    per_measure: dict[str, int] = {}

    for segment in segments:
        dimension, measure = segment["dimension"], segment["measure"]
        if (dimension, measure) in seen_pairs:
            continue
        seen_pairs.add((dimension, measure))
        semantic = segment["semantic_type"]
        best, worst = segment["best"], segment["worst"]
        if not best or not worst or best["group"] == worst["group"]:
            continue
        relevance = _measure_relevance(measure)
        shares_valid = segment.get("shares_valid", True) and best.get("share_pct") is not None
        agg_label = segment.get("aggregation_label", "Total").lower()

        ratio = (best["value"] / worst["value"]) if worst["value"] else None
        # With many similarly sized groups, "the highest" is a coin toss rather
        # than a finding, so require the leader to stand clear of an even split.
        even_share = 100.0 / max(segment["group_count"], 1)
        distinctive = (
            (best["share_pct"] or 0) >= even_share * 1.5 if shares_valid
            else (segment.get("spread_pct") or 0) >= 25
        )
        # Cap how many ways the same measure gets sliced, so one measure cannot
        # fill the report with near-identical rankings.
        if per_measure.get(measure, 0) >= 2:
            continue
        per_measure[measure] = per_measure.get(measure, 0) + 1

        if not distinctive:
            # "The highest of several near-identical groups" is not a finding.
            # That the groups barely differ, however, is one.
            spread = segment.get("spread_pct") or 0.0
            builder.add(
                insight_type=PERFORMANCE,
                headline=f"{measure} varies little across {dimension}",
                fact=(
                    f"{agg_label.title()} {measure} ranges from {worst['formatted_value']} "
                    f"({worst['group']}) to {best['formatted_value']} ({best['group']}) across "
                    f"{segment['group_count']} {dimension} value(s) - a spread of "
                    f"{abs(spread):.1f}%."
                ),
                interpretation=(
                    f"The differences between {dimension} values are small, so {dimension} does "
                    f"not explain much of the variation in {measure}."
                ),
                recommendation=(
                    f"Look for the drivers of {measure} somewhere other than {dimension}; "
                    f"segmenting by it is unlikely to be productive."
                ),
                confidence=HIGH,
                confidence_reason=f"Direct aggregation of {measure} grouped by {dimension}.",
                evidence={
                    "metric": measure,
                    "value": best["value"],
                    "formatted_value": best["formatted_value"],
                    "comparison": {"label": f"{best['group']} vs {worst['group']}",
                                   "from": worst["value"], "to": best["value"],
                                   "change_pct": spread},
                    "source_columns": [measure, dimension],
                    "calculation": (
                        f"{segment.get('aggregation', 'sum').upper()}({measure}) GROUP BY {dimension}"
                    ),
                    "records_used": int(sum(g["count"] for g in segment["groups"])),
                    "aggregation": segment["groups"],
                },
                components=_components(
                    magnitude=3, unusualness=3, relevance=relevance * 0.5,
                    confidence=_confidence_score(HIGH), coverage=9, importance=6,
                ),
                so_what=(
                    f"Ruling {dimension} out narrows where to look for what actually moves "
                    f"{measure}."
                ),
                next_questions=[
                    f"Which column does explain the variation in {measure}?",
                ],
                chart_hint={"kind": "segment", "dimension": dimension, "measure": measure},
                subject=f"{dimension}:flat:{measure}",
                tags=["no_difference"],
            )
            continue

        builder.add(
            insight_type=PERFORMANCE,
            headline=(
                f"{dimension}: {best['group']} accounts for {best['share_pct']:.0f}% of {measure}"
                if shares_valid else
                f"{dimension}: {best['group']} has the highest {agg_label} {measure}"
            ),
            fact=(
                (
                    f"{best['group']} accounts for {best['formatted_value']} of {measure} "
                    f"({best['share_pct']:.1f}% of the {segment['formatted_total']} total) across "
                    f"{best['count']:,} records, while {worst['group']} accounts for "
                    f"{worst['formatted_value']} ({worst['share_pct']:.1f}%)."
                ) if shares_valid else (
                    f"{best['group']} has an {agg_label} {measure} of {best['formatted_value']} "
                    f"across {best['count']:,} records, versus {worst['formatted_value']} for "
                    f"{worst['group']} ({worst['count']:,} records)."
                )
            ),
            interpretation=(
                f"Performance across {dimension} is uneven"
                + (f" - the leader is {ratio:.1f}x the smallest group." if ratio and ratio > 1.5
                   else " but the spread between groups is modest.")
            ),
            recommendation=(
                f"Examine what {best['group']} does differently and whether it can be applied to "
                f"{worst['group']}; confirm the gap is not simply a difference in record volume."
            ),
            confidence=HIGH,
            confidence_reason=f"Direct aggregation of {measure} grouped by {dimension}.",
            evidence={
                "metric": measure,
                "value": best["value"],
                "formatted_value": best["formatted_value"],
                "comparison": {
                    "label": f"{best['group']} vs {worst['group']}",
                    "from": worst["value"],
                    "to": best["value"],
                    "change_pct": safe_float(
                        (best["value"] - worst["value"]) / abs(worst["value"]) * 100
                    ) if worst["value"] else None,
                },
                "source_columns": [measure, dimension],
                "calculation": f"{segment.get('aggregation', 'sum').upper()}({measure}) GROUP BY {dimension}",
                "math": (
                    {
                        "formula": f"Share = SUM({measure} for group) ÷ SUM({measure}) × 100",
                        "substitution": (
                            f"({best['formatted_value']} ÷ {segment['formatted_total']}) × 100"
                        ),
                        "result": f"{best['share_pct']:.1f}%",
                    } if shares_valid else {
                        "formula": f"{segment.get('aggregation', 'sum').upper()}({measure}) per {dimension}",
                        "substitution": f"{best['group']}: {best['count']:,} records",
                        "result": best["formatted_value"],
                    }
                ),
                "records_used": int(sum(g["count"] for g in segment["groups"])),
                "aggregation": segment["groups"],
            },
            components=_components(
                magnitude=(
                    min(best["share_pct"] / 3, 22) if shares_valid
                    else min(abs(segment.get("spread_pct") or 30) / 6, 18)
                ),
                unusualness=min((ratio or 1) * 2, 14),
                relevance=relevance,
                confidence=_confidence_score(HIGH),
                coverage=10,
                importance=15,
            ),
            so_what=(
                (
                    f"{best['group']} contributes {best['share_pct']:.0f}% of total {measure}, so its "
                    f"performance has an outsized effect on the overall number."
                ) if shares_valid else (
                    f"The gap between {best['group']} and {worst['group']} is "
                    f"{abs((best['value'] or 0) - (worst['value'] or 0)):,.4g} on {agg_label} "
                    f"{measure}, which is where any levelling-up effort would pay off most."
                )
            ),
            next_questions=[
                f"What explains the gap between {best['group']} and {worst['group']}?",
                f"Is {best['group']} leading on volume or on average {measure} per record?",
                f"Has the ranking of {dimension} changed over time?",
            ],
            chart_hint={"kind": "segment", "dimension": dimension, "measure": measure},
            subject=f"{dimension}:{best['group']}",
            tags=["winner", "ranking"],
        )

        if shares_valid and worst["share_pct"] is not None and worst["share_pct"] < 8 \
                and segment["group_count"] >= 3:
            builder.add(
                insight_type=OPPORTUNITY,
                headline=f"{worst['group']} contributes only {worst['share_pct']:.1f}% of {measure}",
                fact=(
                    f"{worst['group']} generated {worst['formatted_value']} of {measure} across "
                    f"{worst['count']:,} records - {worst['share_pct']:.1f}% of the total, versus "
                    f"{best['share_pct']:.1f}% for {best['group']}."
                ),
                interpretation=(
                    f"{worst['group']} is the weakest {dimension}. Whether that is an opportunity "
                    f"or simply a smaller market depends on context this dataset does not contain."
                ),
                recommendation=(
                    f"Compare {worst['group']} with {best['group']} on record volume and average "
                    f"{measure} per record to see whether the gap is reach or value."
                ),
                confidence=MEDIUM,
                confidence_reason=(
                    "The totals are calculated directly, but whether the gap represents untapped "
                    "potential requires business context."
                ),
                evidence={
                    "metric": measure,
                    "value": worst["value"],
                    "formatted_value": worst["formatted_value"],
                    "source_columns": [measure, dimension],
                    "calculation": f"SUM({measure}) GROUP BY {dimension}, ascending",
                    "records_used": int(worst["count"]),
                    "aggregation": segment["groups"],
                },
                components=_components(
                    magnitude=min((best["share_pct"] - worst["share_pct"]) / 4, 18),
                    unusualness=8,
                    relevance=relevance * 0.8,
                    confidence=_confidence_score(MEDIUM),
                    coverage=6,
                    importance=13,
                ),
                so_what=(
                    f"Closing even part of the gap between {worst['group']} and the {dimension} "
                    f"average would move the total {measure} measurably."
                ),
                next_questions=[
                    f"Is {worst['group']} under-served or simply a smaller segment?",
                    f"What is the average {measure} per record in {worst['group']}?",
                ],
                chart_hint={"kind": "segment", "dimension": dimension, "measure": measure},
                subject=f"{dimension}:{worst['group']}",
                tags=["underperformer"],
            )

        fastest, declining = segment.get("fastest_growing"), segment.get("fastest_declining")
        # Half-period growth for a thinly populated group is noise, not a trend.
        min_records = max(25, int(row_count * 0.02))
        if fastest and fastest["count"] < min_records:
            fastest = None
        if declining and declining["count"] < min_records:
            declining = None
        if segment["group_count"] > 20:
            fastest = declining = None
        if fastest and declining and fastest["group"] != declining["group"]:
            if declining["growth_pct"] is not None and declining["growth_pct"] < -8:
                builder.add(
                    insight_type=RISK,
                    headline=(
                        f"{declining['group']} {dimension} declined "
                        f"{abs(declining['growth_pct']):.0f}% in {measure}"
                    ),
                    fact=(
                        f"Comparing the first and second halves of the period, {measure} for "
                        f"{declining['group']} changed {declining['growth_pct']:+.1f}% while "
                        f"{fastest['group']} changed {fastest['growth_pct']:+.1f}%."
                    ),
                    interpretation=(
                        f"The decline is specific to {declining['group']} rather than dataset-wide, "
                        f"which points to something particular to that {dimension}."
                    ),
                    recommendation=(
                        f"Investigate {declining['group']} first: break its {measure} down by other "
                        f"dimensions and check whether the fall is in record volume or value."
                    ),
                    confidence=MEDIUM,
                    confidence_reason=(
                        "Half-period comparison of directly aggregated values; the split point is "
                        "chosen mechanically, not around a known event."
                    ),
                    evidence={
                        "metric": measure,
                        "value": declining["value"],
                        "formatted_value": declining["formatted_value"],
                        "comparison": {
                            "label": "First half vs second half",
                            "change_pct": declining["growth_pct"],
                        },
                        "source_columns": [measure, dimension],
                        "calculation": (
                            f"SUM({measure}) per period for each {dimension}, first half vs second half"
                        ),
                        "math": {
                            "formula": "((Second half − First half) ÷ First half) × 100",
                            "result": f"{declining['growth_pct']:+.1f}%",
                        },
                        "records_used": int(declining["count"]),
                        "aggregation": segment["groups"],
                    },
                    components=_components(
                        magnitude=min(abs(declining["growth_pct"]) / 2.5, 22),
                        unusualness=14,
                        relevance=relevance,
                        confidence=_confidence_score(MEDIUM),
                        coverage=min((declining.get("share_pct") or 20) / 5, 10),
                        importance=19,
                    ),
                    so_what=(
                        (
                            f"{declining['group']} represents {declining['share_pct']:.0f}% of "
                            f"{measure}, so a decline of this size subtracts roughly "
                            f"{abs(declining['growth_pct']) * declining['share_pct'] / 100:.1f}% "
                            f"from the overall total."
                        ) if declining.get("share_pct") is not None else (
                            f"{declining['group']} covers {declining['count']:,} records, so a "
                            f"decline of this size is material to the overall picture."
                        )
                    ),
                    next_questions=[
                        f"Which records inside {declining['group']} fell the most?",
                        f"Did record count or average {measure} fall?",
                        f"Is the decline in {declining['group']} seasonal?",
                    ],
                    chart_hint={"kind": "segment_growth", "dimension": dimension, "measure": measure},
                    subject=f"{dimension}:{declining['group']}",
                    tags=["decline", "risk"],
                )
            if fastest["growth_pct"] is not None and fastest["growth_pct"] > 10:
                builder.add(
                    insight_type=OPPORTUNITY,
                    headline=(
                        f"{fastest['group']} is the fastest growing {dimension} "
                        f"({fastest['growth_pct']:+.0f}% in {measure})"
                    ),
                    fact=(
                        f"{measure} for {fastest['group']} changed {fastest['growth_pct']:+.1f}% "
                        f"between the first and second halves of the period, on "
                        f"{fastest['count']:,} records."
                    ),
                    interpretation=(
                        (
                            f"Growth is concentrated in {fastest['group']}, which currently holds "
                            f"{fastest['share_pct']:.1f}% of total {measure}."
                        ) if fastest.get("share_pct") is not None else (
                            f"Growth is concentrated in {fastest['group']} across "
                            f"{fastest['count']:,} records."
                        )
                    ),
                    recommendation=(
                        f"Identify what changed for {fastest['group']} and test whether the same "
                        f"approach transfers to other {dimension} values."
                    ),
                    confidence=MEDIUM,
                    confidence_reason="Half-period comparison of directly aggregated values.",
                    evidence={
                        "metric": measure,
                        "value": fastest["value"],
                        "formatted_value": fastest["formatted_value"],
                        "comparison": {"label": "First half vs second half",
                                       "change_pct": fastest["growth_pct"]},
                        "source_columns": [measure, dimension],
                        "calculation": f"SUM({measure}) per period for each {dimension}",
                        "records_used": int(fastest["count"]),
                        "aggregation": segment["groups"],
                    },
                    components=_components(
                        magnitude=min(fastest["growth_pct"] / 3, 20),
                        unusualness=11,
                        relevance=relevance * 0.9,
                        confidence=_confidence_score(MEDIUM),
                        coverage=min((fastest.get("share_pct") or 20) / 5, 10),
                        importance=14,
                    ),
                    so_what=(
                        f"Growth concentrated in one {dimension} is easier to replicate than "
                        f"dataset-wide growth, but also easier to lose."
                    ),
                    next_questions=[
                        f"Is the growth in {fastest['group']} broad-based or from a few records?",
                        f"Does the same pattern appear in other measures?",
                    ],
                    chart_hint={"kind": "segment_growth", "dimension": dimension, "measure": measure},
                    subject=f"{dimension}:{fastest['group']}",
                    tags=["growth", "opportunity"],
                )


def _concentration_insights(builder: InsightBuilder, concentrations: list[dict[str, Any]],
                            profile: dict[str, Any]) -> None:
    for item in concentrations:
        if not item["is_risk"]:
            continue
        dimension, measure = item["dimension"], item["measure"]
        builder.add(
            insight_type=RISK,
            headline=(
                f"Concentration risk: {item['groups_for_80pct']} of {item['group_count']} "
                f"{dimension} values produce 80% of {measure}"
            ),
            fact=(
                f"{item['top_group']} alone accounts for {item['top1_pct']:.1f}% of {measure} "
                f"({item['top_group_formatted']} of {item['formatted_total']}). The top 5 "
                f"{dimension} values account for {item['top5_pct']:.1f}%."
            ),
            interpretation=(
                f"{measure} is concentrated in a small number of {dimension} values "
                f"(Herfindahl index {item['hhi']:.0f}). Performance of the whole dataset is "
                f"therefore highly dependent on those few."
            ),
            recommendation=(
                f"Assess the dependency on {item['top_group']}: quantify what a 10% fall there "
                f"would do to total {measure}, and look at whether the tail of {dimension} can be "
                f"grown to dilute the exposure."
            ),
            confidence=HIGH,
            confidence_reason="Shares are calculated directly from the aggregated totals.",
            evidence={
                "metric": measure,
                "value": item["top_group_value"],
                "formatted_value": item["top_group_formatted"],
                "source_columns": [measure, dimension],
                "calculation": (
                    f"SUM({measure}) GROUP BY {dimension}, sorted descending, cumulative share"
                ),
                "math": {
                    "formula": f"Top share = SUM({measure} for {item['top_group']}) ÷ SUM({measure}) × 100",
                    "substitution": f"({item['top_group_formatted']} ÷ {item['formatted_total']}) × 100",
                    "result": f"{item['top1_pct']:.1f}%",
                },
                "records_used": int(sum(p.get("value") is not None for p in item["pareto"])),
                "aggregation": item["pareto"],
                "statistics": {"hhi": item["hhi"], "top1_pct": item["top1_pct"],
                               "top5_pct": item["top5_pct"], "groups_for_80pct": item["groups_for_80pct"]},
            },
            components=_components(
                magnitude=min(item["top1_pct"] / 2.5, 24),
                unusualness=14 if item["severity"] == "high" else 10,
                relevance=_measure_relevance(measure),
                confidence=_confidence_score(HIGH),
                coverage=10,
                importance=20 if item["severity"] == "high" else 16,
            ),
            so_what=(
                f"If {item['top_group']} fell 10%, total {measure} would fall roughly "
                f"{item['top1_pct'] / 10:.1f}% with no change anywhere else."
            ),
            next_questions=[
                f"How has the share of {item['top_group']} changed over time?",
                f"Which {dimension} values are growing fast enough to dilute the concentration?",
                f"Is the concentration also present in other measures?",
            ],
            chart_hint={"kind": "pareto", "dimension": dimension, "measure": measure},
            subject=f"{dimension}:{item['top_group']}",
            tags=["concentration", "risk"],
        )


def _anomaly_insights(builder: InsightBuilder, anomalies: dict[str, Any],
                      profile: dict[str, Any], row_count: int) -> None:
    currency = profile.get("currency_symbol", "")
    for item in anomalies.get("items", [])[:6]:
        severity_weight = {"critical": 20, "high": 16, "medium": 11, "low": 7}[item["severity"]]
        if item["kind"] == "timeseries":
            fact = (
                f"{item['column']} in {item['period']} was "
                f"{item['evidence']['actual']} versus {item['evidence']['expected']} implied by the "
                f"trend line - a deviation of {item['deviation_pct']:+.1f}% "
                f"(modified z-score {item['max_score']})."
            )
            interpretation = (
                f"The period sits well outside the normal variation of this series after the "
                f"underlying trend is removed, so it is unlikely to be routine fluctuation."
            )
            recommendation = (
                f"Investigate {item['period']} using the anomaly investigation view to see which "
                f"dimensions the deviation is concentrated in."
            )
            headline = item["headline"]
            subject = f"period:{item['period']}"
        else:
            fact = (
                f"{item['count']:,} record(s) ({item['pct_of_records']:.2f}% of the column) fall "
                f"outside the {item['column']} interquartile fences "
                f"[{format_value(item['bounds']['lower'], item['semantic_type'], currency)}, "
                f"{format_value(item['bounds']['upper'], item['semantic_type'], currency)}] and "
                f"exceed a modified z-score of 3.5."
            )
            interpretation = (
                f"These records are extreme relative to the rest of {item['column']}. They may be "
                f"genuine exceptional cases or data-entry problems."
            )
            recommendation = (
                f"Review the flagged {item['column']} records; decide whether to keep, correct or "
                f"exclude them before relying on averages."
            )
            headline = item["headline"]
            subject = item["column"]

        builder.add(
            insight_type=ANOMALY,
            headline=headline,
            fact=fact,
            interpretation=interpretation,
            recommendation=recommendation,
            confidence=HIGH if item["max_score"] >= 4.5 else MEDIUM,
            confidence_reason=(
                f"Detected by {item['method']}; the statistic is computed from the data itself."
            ),
            evidence={
                "metric": item["column"],
                "value": item.get("actual", item.get("max_score")),
                "formatted_value": item.get("evidence", {}).get("actual", f"z={item['max_score']}"),
                "source_columns": [item["column"]],
                "calculation": item["evidence"]["calculation"],
                "records_used": int(item["evidence"].get("records_used", item.get("count", 0))),
                "statistics": item["evidence"],
                "aggregation": item.get("examples", []),
                "anomaly_id": item["id"],
            },
            components=_components(
                magnitude=(
                    min(abs(item.get("deviation_pct") or 0) / 3, 22)
                    if item["kind"] == "timeseries"
                    else min(item["max_score"] * 2, 14)
                ),
                # A handful of extreme records is unusual; hundreds of them is a
                # skewed distribution, which the distribution engine covers.
                unusualness=20 if item["kind"] == "timeseries" else max(
                    6.0, 20.0 - (item.get("pct_of_records") or 0) * 3
                ),
                relevance=_measure_relevance(item["column"]),
                confidence=_confidence_score(HIGH if item["max_score"] >= 4.5 else MEDIUM),
                coverage=min(item.get("pct_of_records", 3), 10),
                importance=severity_weight,
            ),
            so_what=(
                "Outliers of this size move averages and totals; the report shows median alongside "
                "mean so you can see how much."
                if item["kind"] == "record"
                else f"A single period this far from trend distorts any comparison that includes it."
            ),
            next_questions=[
                f"What may explain the unusual {item['column']} values?",
                f"Are the flagged records concentrated in one segment?",
                f"Do the same records look unusual on other measures?",
            ],
            chart_hint={"kind": "anomaly", "measure": item["column"],
                        "anomaly_id": item["id"], "anomaly_kind": item["kind"]},
            subject=subject,
            tags=["anomaly", item["severity"]],
        )


def _correlation_insights(builder: InsightBuilder, correlations: dict[str, Any]) -> None:
    for pair in correlations.get("meaningful", [])[:5]:
        r = pair["pearson_r"]
        p_value = pair["pearson_p"]
        p_text = "< 0.001" if p_value < 0.001 else f"= {p_value:.3f}"
        builder.add(
            insight_type=RELATIONSHIP,
            headline=(
                f"{pair['x']} and {pair['y']} move together (r = {r:.2f})"
                if r > 0 else f"{pair['x']} and {pair['y']} move in opposite directions (r = {r:.2f})"
            ),
            fact=(
                f"Across {pair['observations']:,} records with both values present, {pair['x']} and "
                f"{pair['y']} have a Pearson correlation of {r:.2f} "
                f"(r² = {pair['r_squared']:.2f}, p {p_text})."
            ),
            interpretation=(
                f"About {pair['r_squared'] * 100:.0f}% of the variation in {pair['y']} is associated "
                f"with variation in {pair['x']}. This is an association, not evidence that one "
                f"causes the other."
            ),
            recommendation=(
                f"If {pair['x']} is something you control, test the relationship deliberately before "
                f"assuming changes to it will move {pair['y']}."
            ),
            confidence=MEDIUM,
            confidence_reason=(
                "The coefficient is calculated directly and is statistically significant, but the "
                "direction of any causal link cannot be established from this dataset."
            ),
            evidence={
                "metric": f"{pair['x']} ~ {pair['y']}",
                "value": r,
                "formatted_value": f"r = {r:.2f}",
                "source_columns": [pair["x"], pair["y"]],
                "calculation": "Pearson product-moment correlation on records where both values exist",
                "math": {
                    "formula": "r = cov(x, y) ÷ (σx × σy)",
                    "substitution": f"{pair['observations']:,} paired observations",
                    "result": f"{r:.4f}",
                },
                "records_used": pair["observations"],
                "statistics": {
                    "pearson_r": r, "spearman_r": pair["spearman_r"],
                    "p_value": pair["pearson_p"], "r_squared": pair["r_squared"],
                },
            },
            components=_components(
                magnitude=min(abs(r) * 20, 20),
                unusualness=12 if abs(r) >= 0.7 else 7,
                relevance=(_measure_relevance(pair["x"]) + _measure_relevance(pair["y"])) / 2,
                confidence=_confidence_score(MEDIUM),
                coverage=8,
                importance=13,
            ),
            so_what=(
                f"Knowing {pair['x']} gives you a usable estimate of {pair['y']} - useful for "
                f"planning, sanity checks and spotting records that break the pattern."
            ),
            next_questions=[
                f"Does the {pair['x']}–{pair['y']} relationship hold within every segment?",
                f"Which records deviate most from the relationship?",
            ],
            chart_hint={"kind": "scatter", "x": pair["x"], "y": pair["y"]},
            subject=f"{pair['x']}~{pair['y']}",
            tags=["correlation"],
        )


def _distribution_insights(builder: InsightBuilder, distributions: dict[str, Any],
                           profile: dict[str, Any]) -> None:
    for item in distributions.get("interpretations", [])[:4]:
        stats = item["stats"]
        builder.add(
            insight_type=DISTRIBUTION,
            headline=f"{item['column']} is {item['shape']}",
            fact=item["narrative"],
            interpretation=(
                f"With skewness {item['skewness']:.2f}, the mean is not a good summary of a typical "
                f"{item['column']}; the median is the more representative figure."
                if item["skewness"] is not None else
                f"The mean and median of {item['column']} differ materially."
            ),
            recommendation=(
                f"Report the median for {item['column']} alongside the mean, and segment the "
                f"distribution before drawing conclusions from the average."
            ),
            confidence=HIGH,
            confidence_reason="Mean, median and skewness are calculated directly from the column.",
            evidence={
                "metric": item["column"],
                "value": stats["mean"],
                "formatted_value": f"mean {stats['mean']:,.2f} vs median {stats['median']:,.2f}",
                "source_columns": [item["column"]],
                "calculation": "Mean, median, quartiles and Fisher-Pearson skewness",
                "math": {
                    "formula": "Gap = |mean − median| ÷ |median| × 100",
                    "substitution": f"|{stats['mean']:,.2f} − {stats['median']:,.2f}| ÷ |{stats['median']:,.2f}| × 100",
                    "result": f"{item['gap_pct']:.1f}%",
                },
                "records_used": stats["count"],
                "statistics": stats,
            },
            components=_components(
                magnitude=min(item["gap_pct"] / 3, 16),
                unusualness=9,
                relevance=_measure_relevance(item["column"]),
                confidence=_confidence_score(HIGH),
                coverage=9,
                importance=11,
            ),
            so_what=(
                f"Decisions based on the average {item['column']} will misrepresent the majority of "
                f"records."
            ),
            next_questions=[
                f"Which segment contains the extreme {item['column']} values?",
                f"How does the {item['column']} distribution differ between groups?",
            ],
            chart_hint={"kind": "histogram", "measure": item["column"]},
            subject=item["column"],
            tags=["distribution"],
        )


def _quality_insights(builder: InsightBuilder, quality: dict[str, Any], row_count: int) -> None:
    for issue in quality.get("issues", [])[:5]:
        if issue["severity"] not in {"critical", "high", "medium"}:
            continue
        builder.add(
            insight_type=DATA_QUALITY,
            headline=issue["title"],
            fact=issue["detail"],
            interpretation=issue["impact"],
            recommendation=(
                f"Address this before relying on {issue['column'] or 'the affected'} figures: "
                + (quality["recommendations"][0] if quality.get("recommendations") else
                   "correct the source data or exclude the affected records explicitly.")
            ),
            confidence=HIGH,
            confidence_reason="Counted directly from the dataset.",
            evidence={
                "metric": issue["column"] or "dataset",
                "value": issue.get("affected_records"),
                "formatted_value": f"{issue.get('affected_records', 0):,} records",
                "source_columns": [issue["column"]] if issue["column"] else [],
                "calculation": f"Data quality check: {issue['type'].replace('_', ' ')}",
                "records_used": int(issue.get("affected_records") or 0),
                "statistics": {"severity": issue["severity"],
                               "affected_pct": issue.get("affected_pct")},
            },
            components=_components(
                magnitude=min((issue.get("affected_pct") or 0) / 2, 14),
                unusualness=6,
                relevance=10,
                confidence=_confidence_score(HIGH),
                coverage=min((issue.get("affected_pct") or 0) / 5, 10),
                importance={"critical": 19, "high": 15, "medium": 10}.get(issue["severity"], 6),
            ),
            so_what=issue["impact"],
            next_questions=[
                f"How many downstream figures depend on {issue['column'] or 'these records'}?",
                "Can the affected records be corrected at source?",
            ],
            chart_hint={"kind": "quality"},
            subject=issue["column"] or "dataset",
            tags=["data_quality", issue["severity"]],
        )


def _driver_insights(builder: InsightBuilder, investigations: list[dict[str, Any]],
                     profile: dict[str, Any]) -> None:
    for investigation in investigations[:3]:
        if not investigation.get("available") or not investigation.get("explanations"):
            continue
        measure = investigation["measure"]
        top = investigation["contributions"][0] if investigation["contributions"] else None
        if not top:
            continue
        builder.add(
            insight_type=DRIVER,
            headline=(
                f"The deviation in {measure} is concentrated in {top['dimension']} = "
                f"{top['top_value']}"
            ),
            fact=top["narrative"],
            interpretation=(
                "The pattern coincides with this segment. That is where to look first, but the "
                "dataset cannot establish that this segment caused the deviation."
            ),
            recommendation=(
                f"Start the investigation with {top['dimension']} = {top['top_value']} and confirm "
                f"whether the same shift appears in other periods."
            ),
            confidence=MEDIUM,
            confidence_reason=(
                "The shares are calculated directly, but attributing the deviation to this segment "
                "is an interpretation, not a measured fact."
            ),
            evidence={
                "metric": measure,
                "value": top["top_share_pct"],
                "formatted_value": f"{top['top_share_pct']:.1f}% share",
                "source_columns": [measure, top["dimension"]],
                "calculation": (
                    f"Share of {measure} by {top['dimension']} within {investigation['context']} "
                    f"versus the rest of the dataset"
                ),
                "records_used": investigation["records_examined"],
                "aggregation": top["rows"],
                "statistics": {"share_shift_pct": top["top_shift_pct"]},
            },
            components=_components(
                magnitude=min(abs(top["top_shift_pct"]), 20),
                unusualness=15,
                relevance=_measure_relevance(measure),
                confidence=_confidence_score(MEDIUM),
                coverage=7,
                importance=17,
            ),
            so_what=(
                f"Narrowing the deviation to one {top['dimension']} value turns a dataset-wide "
                f"question into a specific one."
            ),
            next_questions=investigation.get("next_questions", [])[:3],
            chart_hint={"kind": "investigation", "measure": measure,
                        "dimension": top["dimension"]},
            subject=f"{top['dimension']}:{top['top_value']}",
            tags=["driver"],
        )


def _derived_column_insights(builder: InsightBuilder, derived: list[dict[str, Any]],
                             profile: dict[str, Any]) -> None:
    for finding in derived[:3]:
        builder.add(
            insight_type=RELATIONSHIP,
            headline=f"{finding['column']} is calculated from other columns in this dataset",
            fact=finding["narrative"],
            interpretation=(
                f"{finding['column']} is not an independent measure. Any correlation between it and "
                f"{', '.join(finding['sources'])} is arithmetic, not a discovery, so those pairs are "
                f"excluded from the reported relationships."
            ),
            recommendation=(
                f"Treat {finding['column']} as a summary of {', '.join(finding['sources'])} when "
                f"interpreting this report, and analyse the components when you need to explain a "
                f"change in it."
            ),
            confidence=HIGH,
            confidence_reason=(
                f"The identity holds in {finding['match_ratio'] * 100:.0f}% of records tested."
            ),
            evidence={
                "metric": finding["column"],
                "value": finding["match_ratio"],
                "formatted_value": f"{finding['match_ratio'] * 100:.0f}% of records match",
                "source_columns": [finding["column"], *finding["sources"]],
                "calculation": finding["formula"],
                "math": {"formula": finding["formula"],
                         "substitution": "checked row by row within a 0.5% tolerance",
                         "result": f"{finding['match_ratio'] * 100:.1f}% match"},
                "records_used": profile["row_count"],
            },
            components=_components(
                magnitude=8, unusualness=6, relevance=9,
                confidence=_confidence_score(HIGH), coverage=10, importance=9,
            ),
            so_what=(
                f"Knowing {finding['column']} is derived stops it being read as independent "
                f"confirmation of the same story."
            ),
            next_questions=[
                f"Which component of {finding['column']} moved most?",
            ],
            chart_hint={"kind": "quality"},
            subject=f"derived:{finding['column']}",
            tags=["derived_column"],
        )


def discover_insights(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Run every discovery pass and return insights ranked by priority score."""
    builder = InsightBuilder()
    profile = context["profile"]
    row_count = profile["row_count"]

    _trend_insights(builder, context.get("trends", []), profile)
    _segment_insights(builder, context.get("segments", []), profile, row_count)
    _concentration_insights(builder, context.get("concentration", []), profile)
    _anomaly_insights(builder, context.get("anomalies", {}), profile, row_count)
    _driver_insights(builder, context.get("investigations", []), profile)
    _correlation_insights(builder, context.get("correlations", {}))
    _derived_column_insights(builder, context.get("derived_columns", []), profile)
    _distribution_insights(builder, context.get("distributions", {}), profile)
    _quality_insights(builder, context.get("quality", {}), row_count)

    insights = builder.items
    insights = _deduplicate(insights)
    insights.sort(key=lambda i: -i["priority"]["score"])
    for rank, insight in enumerate(insights, start=1):
        insight["rank"] = rank
    return insights


def _deduplicate(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop insights that repeat the same finding.

    Two passes: identical (type, subject) pairs, then - for findings keyed on a
    time period - any repeat of that period regardless of type, so a single
    unusual month is not reported once as a trend break and again as an anomaly.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for insight in sorted(insights, key=lambda i: -i["priority"]["score"]):
        key = (insight["type"], insight["subject"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(insight)

    periods_seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    record_anomalies = 0
    for insight in unique:
        subject = insight["subject"].lower()
        if subject.startswith("period:"):
            if subject in periods_seen:
                continue
            periods_seen.add(subject)
        if insight["type"] == ANOMALY and "anomaly" in insight["tags"] \
                and not subject.startswith("period:"):
            # Record-level outlier findings across correlated measures describe
            # the same rows; two are informative, five are noise.
            record_anomalies += 1
            if record_anomalies > 2:
                continue
        deduped.append(insight)
    return deduped


def diversify(insights: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Pick the strongest findings while avoiding three of the same kind in a row."""
    chosen: list[dict[str, Any]] = []
    used_types: dict[str, int] = {}
    for insight in insights:
        if used_types.get(insight["type"], 0) >= 2:
            continue
        used_types[insight["type"]] = used_types.get(insight["type"], 0) + 1
        chosen.append(insight)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for insight in insights:
            if insight not in chosen:
                chosen.append(insight)
            if len(chosen) >= limit:
                break
    return chosen


def story_score(insights: list[dict[str, Any]], quality: dict[str, Any],
                context: dict[str, Any]) -> dict[str, Any]:
    """'Data Story Strength' - how much useful information was discovered."""
    completeness = float(quality.get("components", {}).get("completeness", 100))
    pattern_count = len(insights)
    patterns = min(pattern_count / 18 * 100, 100)

    strong = [
        i for i in insights
        if i["confidence"] == HIGH and i["priority"]["score"] >= 55
    ]
    statistical = min(len(strong) / 8 * 100, 100)

    confidence_map = {HIGH: 1.0, MEDIUM: 0.6, LOW: 0.3}
    confidence = (
        sum(confidence_map[i["confidence"]] for i in insights) / max(len(insights), 1) * 100
    )

    covered = {i["type"] for i in insights}
    possible = {PERFORMANCE, TREND, ANOMALY, RISK, OPPORTUNITY, RELATIONSHIP,
                DISTRIBUTION, DATA_QUALITY, DRIVER}
    coverage = len(covered) / len(possible) * 100

    weights = {"data_completeness": 0.2, "meaningful_patterns": 0.25, "statistical_strength": 0.2,
               "insight_confidence": 0.2, "analytical_coverage": 0.15}
    components = {
        "data_completeness": round(completeness, 1),
        "meaningful_patterns": round(patterns, 1),
        "statistical_strength": round(statistical, 1),
        "insight_confidence": round(confidence, 1),
        "analytical_coverage": round(coverage, 1),
    }
    score = round(sum(components[k] * weights[k] for k in components), 1)
    if score >= 85:
        label = "Rich"
    elif score >= 70:
        label = "Strong"
    elif score >= 55:
        label = "Moderate"
    else:
        label = "Limited"
    return {
        "score": score,
        "label": label,
        "components": components,
        "weights": weights,
        "explanation": (
            f"{pattern_count} meaningful pattern(s) were discovered across "
            f"{len(covered)} of {len(possible)} analytical categories, "
            f"{len(strong)} of them with high confidence and a high priority score. "
            f"Data completeness contributes {completeness:.0f}/100."
        ),
    }
