"""Recommendation engine and executive briefing.

Recommendations are always tied to a calculated finding: the action text names
the segment, the measure and the size of the effect, and carries the evidence
that justified its priority.
"""
from __future__ import annotations

from typing import Any

from app.engines import insights as I
from app.engines.formatting import format_delta

CRITICAL, HIGH, MEDIUM, LOW = "critical", "high", "medium", "low"

PRIORITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

PRIORITY_MEANING = {
    CRITICAL: "Immediate investigation recommended.",
    HIGH: "Significant potential impact.",
    MEDIUM: "Worth investigating.",
    LOW: "Optional optimisation.",
}


def _priority_for(insight: dict[str, Any]) -> str:
    score = insight["priority"]["score"]
    insight_type = insight["type"]
    if insight_type in {I.RISK, I.ANOMALY} and score >= 75:
        return CRITICAL
    if score >= 75:
        return HIGH
    if insight_type in {I.RISK, I.DATA_QUALITY} and score >= 55:
        return HIGH
    if score >= 55:
        return MEDIUM
    return LOW


def build_recommendations(insights: list[dict[str, Any]], quality: dict[str, Any],
                          max_items: int = 10) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()

    for insight in insights:
        action = insight["recommendation"].strip()
        if not action or action.lower() in seen:
            continue
        seen.add(action.lower())
        priority = _priority_for(insight)
        evidence = insight["evidence"]
        recommendations.append(
            {
                "id": f"rec_{len(recommendations) + 1:03d}",
                "insight_id": insight["id"],
                "action": action,
                "priority": priority,
                "priority_meaning": PRIORITY_MEANING[priority],
                "rationale": insight["fact"],
                "impact": insight.get("so_what") or insight["interpretation"],
                "confidence": insight["confidence"],
                "type": insight["type"],
                "type_label": insight["type_label"],
                "source_columns": evidence.get("source_columns", []),
                "evidence": {
                    "metric": evidence.get("metric"),
                    "value": evidence.get("formatted_value"),
                    "calculation": evidence.get("calculation"),
                    "records_used": evidence.get("records_used"),
                    "comparison": evidence.get("comparison"),
                },
                "priority_score": insight["priority"]["score"],
            }
        )
        if len(recommendations) >= max_items:
            break

    for recommendation in quality.get("recommendations", [])[:2]:
        if recommendation.lower() in seen or len(recommendations) >= max_items + 2:
            continue
        seen.add(recommendation.lower())
        recommendations.append(
            {
                "id": f"rec_{len(recommendations) + 1:03d}",
                "insight_id": None,
                "action": recommendation,
                "priority": MEDIUM if quality.get("score", 100) < 85 else LOW,
                "priority_meaning": PRIORITY_MEANING[MEDIUM if quality.get("score", 100) < 85 else LOW],
                "rationale": quality.get("explanation", ""),
                "impact": "Improves the reliability of every figure derived from this dataset.",
                "confidence": "high",
                "type": I.DATA_QUALITY,
                "type_label": "Data Quality",
                "source_columns": [],
                "evidence": {
                    "metric": "data quality score",
                    "value": f"{quality.get('score', 0):.0f}/100",
                    "calculation": "Weighted completeness, uniqueness, validity, consistency and structure",
                    "records_used": quality.get("metrics", {}).get("rows"),
                },
                "priority_score": 40.0,
            }
        )

    recommendations.sort(key=lambda r: (PRIORITY_ORDER[r["priority"]], -r["priority_score"]))
    return recommendations


def build_briefing(context: dict[str, Any]) -> dict[str, Any]:
    """Management-ready summary readable in about two minutes."""
    insights = context["insights"]
    recommendations = context.get("recommendations", [])
    kpis = context.get("kpis", {}).get("primary", [])
    quality = context.get("quality", {})
    trends = context.get("trends", [])

    wins = [
        i for i in insights
        if ("winner" in i["tags"] or "growth" in i["tags"]
            or (i["type"] == I.TREND and "increasing" in i["tags"]))
    ][:3]
    concerns = [
        i for i in insights
        if i["type"] in {I.RISK, I.ANOMALY} or "decline" in i["tags"]
    ][:3]
    trend_insights = [i for i in insights if i["type"] == I.TREND][:3]
    opportunities = [
        i for i in insights if i["type"] == I.OPPORTUNITY
    ][:3]

    status, status_reason = _overall_status(insights, trends, quality)

    return {
        "status": status,
        "status_reason": status_reason,
        "generated_from": {
            "insights_considered": len(insights),
            "records": context["profile"]["row_count"],
        },
        "wins": [_brief_item(i) for i in wins],
        "concerns": [_brief_item(i) for i in concerns],
        "trends": [_brief_item(i) for i in trend_insights],
        "opportunities": [_brief_item(i) for i in opportunities],
        "actions": [
            {
                "action": r["action"],
                "priority": r["priority"],
                "impact": r["impact"],
                "insight_id": r["insight_id"],
            }
            for r in recommendations[:3]
        ],
        "key_numbers": [
            {
                "label": k["label"],
                "value": k["formatted"],
                "detail": k["description"],
                "derived": k["derived"],
            }
            for k in kpis[:6]
        ],
        "data_quality": {
            "score": quality.get("score"),
            "grade": quality.get("grade"),
            "headline": quality.get("explanation", "").split(".")[0] + "."
            if quality.get("explanation") else "",
        },
        "reading_time_seconds": 120,
    }


def _brief_item(insight: dict[str, Any]) -> dict[str, Any]:
    return {
        "insight_id": insight["id"],
        "headline": insight["headline"],
        "detail": insight["fact"],
        "confidence": insight["confidence"],
        "type_label": insight["type_label"],
    }


def _overall_status(insights: list[dict[str, Any]], trends: list[dict[str, Any]],
                    quality: dict[str, Any]) -> tuple[str, str]:
    reasons: list[str] = []
    score = 0

    declining = [
        t for t in trends
        if t["classification"].get("direction") == "decreasing"
        and t["classification"].get("confidence") in {"high", "medium"}
    ]
    increasing = [
        t for t in trends
        if t["classification"].get("direction") == "increasing"
        and t["classification"].get("confidence") in {"high", "medium"}
    ]
    if increasing:
        score += 2 * len(increasing)
        reasons.append(f"{len(increasing)} measure(s) show a significant upward trend")
    if declining:
        score -= 2 * len(declining)
        reasons.append(f"{len(declining)} measure(s) show a significant downward trend")

    risks = [i for i in insights if i["type"] == I.RISK and i["priority"]["score"] >= 65]
    if risks:
        score -= len(risks)
        reasons.append(f"{len(risks)} high-priority risk(s) were identified")

    critical_anomalies = [
        i for i in insights if i["type"] == I.ANOMALY and "critical" in i["tags"]
    ]
    if critical_anomalies:
        score -= 2
        reasons.append(f"{len(critical_anomalies)} critical anomaly(ies) were detected")

    if quality.get("score", 100) < 70:
        score -= 1
        reasons.append(f"data quality is {quality.get('grade', 'weak').lower()}")

    if score >= 2:
        status = "Positive"
    elif score <= -2:
        status = "Concerning"
    else:
        status = "Neutral"

    if not reasons:
        reasons.append("no significant trends or risks were detected")
    return status, "Status is " + status.lower() + " because " + ", ".join(reasons) + "."
