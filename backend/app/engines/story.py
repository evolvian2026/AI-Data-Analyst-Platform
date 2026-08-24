"""Data Story engine.

Turns the ranked insight list into an ordered executive narrative. The order is
driven by analytical importance, not by the order the engines happened to run
in, and every card carries its supporting KPI, chart, evidence and confidence.
"""
from __future__ import annotations

from typing import Any

from app.engines import insights as I
from app.engines.formatting import format_delta, format_value

# Section definition: (key, title, purpose, which insight types belong here)
SECTIONS: list[dict[str, Any]] = [
    {"key": "executive_summary", "title": "Executive Summary",
     "purpose": "The most important findings in three to five sentences.", "types": []},
    {"key": "big_picture", "title": "The Big Picture",
     "purpose": "Overall scale and performance of the dataset.", "types": []},
    {"key": "major_trends", "title": "Major Trends",
     "purpose": "What is changing over time.", "types": [I.TREND]},
    {"key": "key_drivers", "title": "Key Drivers",
     "purpose": "What appears to be driving the major outcomes.", "types": [I.DRIVER]},
    {"key": "winners", "title": "Winners",
     "purpose": "The best-performing areas.", "types": [I.PERFORMANCE]},
    {"key": "underperformers", "title": "Underperformers",
     "purpose": "The weakest areas.", "types": [I.OPPORTUNITY]},
    {"key": "anomalies", "title": "Anomalies",
     "purpose": "Unexpected patterns worth investigating.", "types": [I.ANOMALY]},
    {"key": "relationships", "title": "Relationships",
     "purpose": "Important correlations between measures.", "types": [I.RELATIONSHIP,
                                                                     I.DISTRIBUTION]},
    {"key": "risks", "title": "Risks",
     "purpose": "Concerns that could require attention.", "types": [I.RISK, I.DATA_QUALITY]},
    {"key": "opportunities", "title": "Opportunities",
     "purpose": "Areas with apparent potential.", "types": [I.OPPORTUNITY]},
    {"key": "recommendations", "title": "Recommendations",
     "purpose": "Data-supported actions, ranked by priority.", "types": []},
    {"key": "next_questions", "title": "Next Questions",
     "purpose": "What to investigate next.", "types": []},
]


def build_story(context: dict[str, Any]) -> dict[str, Any]:
    insights = context["insights"]
    charts = {c["id"]: c for c in context.get("charts", [])}
    kpis = context.get("kpis", {}).get("primary", [])
    quality = context.get("quality", {})
    profile = context["profile"]
    recommendations = context.get("recommendations", [])

    by_type: dict[str, list[dict[str, Any]]] = {}
    for insight in insights:
        by_type.setdefault(insight["type"], []).append(insight)

    used_ids: set[str] = set()
    sections: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []

    # --- 1 & 2: summary sections built from the top findings -----------------
    top_insights = I.diversify(insights, 5)
    summary_text = executive_summary(context, top_insights)
    sections.append(
        {
            "key": "executive_summary",
            "title": "Executive Summary",
            "purpose": SECTIONS[0]["purpose"],
            "narrative": summary_text,
            "insight_ids": [i["id"] for i in top_insights],
            "kpis": [k["key"] for k in kpis[:4]],
        }
    )
    cards.append(
        {
            "id": "story_executive_summary",
            "section": "executive_summary",
            "headline": "Executive Summary",
            "kpi": kpis[0] if kpis else None,
            "chart_id": None,
            "explanation": summary_text,
            "evidence": {
                "calculation": "Composed from the highest-priority calculated findings.",
                "source_columns": sorted(
                    {c for i in top_insights for c in i["evidence"].get("source_columns", []) if c}
                ),
                "records_used": profile["row_count"],
            },
            "confidence": "high",
            "recommendation": recommendations[0]["action"] if recommendations else "",
            "insight_ids": [i["id"] for i in top_insights],
        }
    )

    big_picture = big_picture_narrative(context)
    sections.append(
        {
            "key": "big_picture",
            "title": "The Big Picture",
            "purpose": SECTIONS[1]["purpose"],
            "narrative": big_picture,
            "insight_ids": [],
            "kpis": [k["key"] for k in kpis[:6]],
        }
    )
    cards.append(
        {
            "id": "story_big_picture",
            "section": "big_picture",
            "headline": "The Big Picture",
            "kpi": kpis[0] if kpis else None,
            "chart_id": next((c["id"] for c in context.get("charts", [])
                              if c["type"] in {"line", "area", "bar", "horizontal_bar"}), None),
            "explanation": big_picture,
            "evidence": {
                "calculation": "Dataset totals and the data quality score.",
                "source_columns": [k["source_columns"][0] for k in kpis[:4] if k["source_columns"]],
                "records_used": profile["row_count"],
            },
            "confidence": "high",
            "recommendation": "",
            "insight_ids": [],
        }
    )

    # --- 3..10: insight-driven sections -------------------------------------
    for definition in SECTIONS[2:10]:
        key = definition["key"]
        candidates = _candidates_for(key, by_type, used_ids)
        if not candidates:
            continue
        chosen = candidates[: 3 if key in {"major_trends", "risks"} else 2]
        for insight in chosen:
            used_ids.add(insight["id"])
            cards.append(_card_from_insight(insight, key, charts, kpis))
        sections.append(
            {
                "key": key,
                "title": definition["title"],
                "purpose": definition["purpose"],
                "narrative": " ".join(i["fact"] for i in chosen),
                "insight_ids": [i["id"] for i in chosen],
                "kpis": [],
            }
        )

    # --- 11: recommendations -------------------------------------------------
    if recommendations:
        sections.append(
            {
                "key": "recommendations",
                "title": "Recommendations",
                "purpose": SECTIONS[10]["purpose"],
                "narrative": " ".join(r["action"] for r in recommendations[:3]),
                "insight_ids": [r["insight_id"] for r in recommendations[:5] if r.get("insight_id")],
                "kpis": [],
                "recommendations": recommendations[:8],
            }
        )
        cards.append(
            {
                "id": "story_recommendations",
                "section": "recommendations",
                "headline": "Recommended Actions",
                "kpi": None,
                "chart_id": None,
                "explanation": " ".join(
                    f"{r['priority'].title()}: {r['action']}" for r in recommendations[:3]
                ),
                "evidence": {
                    "calculation": "Derived from the highest-priority findings and their evidence.",
                    "source_columns": sorted(
                        {c for r in recommendations[:5] for c in r.get("source_columns", [])}
                    ),
                    "records_used": profile["row_count"],
                },
                "confidence": "medium",
                "recommendation": "",
                "insight_ids": [r["insight_id"] for r in recommendations[:5] if r.get("insight_id")],
                "recommendations": recommendations[:8],
            }
        )

    # --- 12: next questions --------------------------------------------------
    questions = next_questions(context)
    if questions:
        sections.append(
            {
                "key": "next_questions",
                "title": "Next Questions",
                "purpose": SECTIONS[11]["purpose"],
                "narrative": " ".join(questions[:3]),
                "insight_ids": [],
                "kpis": [],
                "questions": questions,
            }
        )
        cards.append(
            {
                "id": "story_next_questions",
                "section": "next_questions",
                "headline": "What to Investigate Next",
                "kpi": None,
                "chart_id": None,
                "explanation": "These questions follow directly from the findings above and can be "
                               "asked in Ask Your Data.",
                "evidence": {
                    "calculation": "Generated from the columns available in this dataset.",
                    "source_columns": [],
                    "records_used": profile["row_count"],
                },
                "confidence": "high",
                "recommendation": "",
                "insight_ids": [],
                "questions": questions,
            }
        )

    for position, card in enumerate(cards, start=1):
        card["position"] = position
        card["total"] = len(cards)

    return {
        "sections": sections,
        "cards": cards,
        "card_count": len(cards),
        "flow": [{"position": c["position"], "headline": c["headline"], "section": c["section"]}
                 for c in cards],
    }


def _candidates_for(key: str, by_type: dict[str, list[dict[str, Any]]],
                    used: set[str]) -> list[dict[str, Any]]:
    if key == "winners":
        pool = [i for i in by_type.get(I.PERFORMANCE, []) if "winner" in i["tags"]]
    elif key == "underperformers":
        pool = [i for i in by_type.get(I.OPPORTUNITY, []) if "underperformer" in i["tags"]]
    elif key == "opportunities":
        pool = [i for i in by_type.get(I.OPPORTUNITY, []) if "underperformer" not in i["tags"]]
    elif key == "relationships":
        pool = by_type.get(I.RELATIONSHIP, []) + by_type.get(I.DISTRIBUTION, [])
    elif key == "risks":
        pool = by_type.get(I.RISK, []) + by_type.get(I.DATA_QUALITY, [])
    else:
        types = next(s["types"] for s in SECTIONS if s["key"] == key)
        pool = [i for t in types for i in by_type.get(t, [])]
    pool = [i for i in pool if i["id"] not in used]
    pool.sort(key=lambda i: -i["priority"]["score"])
    return pool


def _card_from_insight(insight: dict[str, Any], section: str, charts: dict[str, Any],
                       kpis: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = insight["evidence"]
    kpi = None
    for candidate in kpis:
        if evidence.get("metric") and evidence["metric"] in candidate.get("source_columns", []):
            kpi = candidate
            break
    supporting_kpi = {
        "label": evidence.get("metric", ""),
        "value": evidence.get("formatted_value", ""),
        "sub": (
            format_delta(evidence.get("comparison", {}).get("change_pct"))
            if evidence.get("comparison", {}).get("change_pct") is not None else ""
        ),
    }
    return {
        "id": f"story_{insight['id']}",
        "section": section,
        "headline": insight["headline"],
        "kpi": kpi,
        "supporting_kpi": supporting_kpi,
        "chart_id": insight.get("chart_id"),
        "explanation": insight["interpretation"],
        "fact": insight["fact"],
        "so_what": insight.get("so_what", ""),
        "evidence": evidence,
        "confidence": insight["confidence"],
        "confidence_reason": insight["confidence_reason"],
        "recommendation": insight["recommendation"],
        "insight_ids": [insight["id"]],
        "type": insight["type"],
        "type_label": insight["type_label"],
        "priority_score": insight["priority"]["score"],
        "questions": insight.get("next_questions", []),
    }


def executive_summary(context: dict[str, Any], top_insights: list[dict[str, Any]]) -> str:
    """Three to five sentences describing the most important findings."""
    profile = context["profile"]
    quality = context.get("quality", {})
    meta = context.get("meta", {})
    sentences: list[str] = []

    sentences.append(
        f"This analysis covers {profile['row_count']:,} records across "
        f"{profile['column_count']} columns"
        + (f" from {meta.get('filename')}." if meta.get("filename") else ".")
    )

    if not top_insights:
        sentences.append(
            "No statistically notable pattern was found: the measures are stable, evenly spread "
            "across segments and free of significant outliers."
        )
    else:
        for insight in top_insights[:3]:
            sentences.append(insight["fact"])
        risk = next((i for i in top_insights if i["type"] in {I.RISK}), None)
        if risk and risk not in top_insights[:3]:
            sentences.append(risk["fact"])

    if quality:
        sentences.append(
            f"Data quality scores {quality['score']:.0f}/100 ({quality['grade']}), which is the "
            f"reliability ceiling for every figure in this report."
        )
    return " ".join(sentences[:6])


def big_picture_narrative(context: dict[str, Any]) -> str:
    profile = context["profile"]
    kpis = context.get("kpis", {}).get("primary", [])
    quality = context.get("quality", {})
    trends = context.get("trends", [])
    parts: list[str] = []

    headline_kpis = [k for k in kpis if k["key"] != "record_count"][:3]
    if headline_kpis:
        parts.append(
            "Headline figures: "
            + "; ".join(f"{k['label']} is {k['formatted']}" for k in headline_kpis)
            + "."
        )
    parts.append(
        f"The dataset holds {profile['row_count']:,} records with "
        f"{len(profile['roles']['measure'])} measure(s) and "
        f"{len(profile['roles']['dimension'])} dimension(s) available for analysis."
    )
    if trends:
        leading = trends[0]
        direction = leading["classification"].get("direction", "stable")
        parts.append(
            f"Over the observed period {leading['measure']} is {direction}"
            + (f" ({format_delta(leading['total_change_pct'])} from {leading['first_period']} to "
               f"{leading['last_period']})." if leading.get("total_change_pct") is not None else ".")
        )
    else:
        parts.append(
            "No usable time dimension was found, so this analysis compares segments rather than "
            "periods."
        )
    if quality:
        parts.append(quality["explanation"].split(".")[0] + ".")
    return " ".join(parts)


def next_questions(context: dict[str, Any]) -> list[str]:
    """Dynamically generated follow-up questions based on available columns."""
    questions: list[str] = []
    seen: set[str] = set()
    for insight in context["insights"][:8]:
        for question in insight.get("next_questions", []):
            normalised = question.lower().strip()
            if normalised in seen:
                continue
            seen.add(normalised)
            questions.append(question)
    profile = context["profile"]
    measures = profile["roles"]["measure"]
    dimensions = profile["roles"]["dimension"]
    time_column = context.get("time_column")
    generic = []
    if measures and dimensions:
        generic.append(f"Which {dimensions[0]} has the highest average {measures[0]}?")
    if measures and time_column:
        generic.append(f"How did {measures[0]} change compared with the previous period?")
    if len(measures) >= 2:
        generic.append(f"Is {measures[0]} related to {measures[1]}?")
    generic.append("What are the most important findings?")
    for question in generic:
        if question.lower() not in seen:
            seen.add(question.lower())
            questions.append(question)
    return questions[:10]
