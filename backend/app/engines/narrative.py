"""Dataset summary and audience-aware narration.

All wording is composed from values the analytics engine calculated. The
audience setting changes depth and vocabulary, never the numbers.
"""
from __future__ import annotations

from typing import Any

from app.engines import profiler as P
from app.engines.formatting import format_delta, format_value, plural

AUDIENCES = {
    "executive": {
        "label": "Executive",
        "depth": "minimal",
        "description": "Impact, trends, risks, opportunities and actions only.",
    },
    "manager": {
        "label": "Manager",
        "depth": "moderate",
        "description": "Findings with the segments and periods behind them.",
    },
    "analyst": {
        "label": "Analyst",
        "depth": "full",
        "description": "Methodology, statistics, correlations and detailed calculations.",
    },
    "researcher": {
        "label": "Researcher",
        "depth": "full",
        "description": "Statistical detail, significance levels and caveats.",
    },
    "student": {
        "label": "Student",
        "depth": "explained",
        "description": "Plain-language explanations of what each measure means.",
    },
    "general": {
        "label": "General User",
        "depth": "moderate",
        "description": "Clear findings without statistical jargon.",
    },
}


def dataset_summary(profile: dict[str, Any], meta: dict[str, Any],
                    time_column: str | None) -> str:
    """One-paragraph description generated from the profile."""
    roles = profile["roles"]
    row_count = profile["row_count"]
    column_count = profile["column_count"]

    measures = roles[P.MEASURE]
    dimensions = roles[P.DIMENSION]
    times = roles[P.TIME_DIMENSION]
    identifiers = roles[P.IDENTIFIER_ROLE]

    subject = _infer_subject(profile, meta)
    parts = [
        f"This dataset contains {row_count:,} {subject} across {column_count} columns"
    ]

    if time_column:
        column = next((c for c in profile["columns"] if c["name"] == time_column), None)
        stats = (column or {}).get("temporal_stats") or {}
        if stats.get("min") and stats.get("max"):
            start = stats["min"][:10]
            end = stats["max"][:10]
            parts.append(f" covering {_pretty_date(start)} to {_pretty_date(end)}")
    parts.append(". ")

    composition = []
    if measures:
        composition.append(plural(len(measures), "numerical measure"))
    if dimensions:
        composition.append(plural(len(dimensions), "categorical dimension"))
    if times:
        composition.append(plural(len(times), "date field"))
    if identifiers:
        composition.append(plural(len(identifiers), "identifier field"))
    if composition:
        parts.append("It contains " + _join(composition) + ".")

    if measures:
        parts.append(
            f" The main measures are {_join(measures[:4])}"
            + (f" and {len(measures) - 4} more." if len(measures) > 4 else ".")
        )
    if dimensions:
        parts.append(
            f" Records can be broken down by {_join(dimensions[:4])}"
            + (f" and {len(dimensions) - 4} other dimension(s)." if len(dimensions) > 4 else ".")
        )
    return "".join(parts)


def _pretty_date(iso: str) -> str:
    from datetime import date

    try:
        parsed = date.fromisoformat(iso)
    except ValueError:
        return iso
    return parsed.strftime("%B %Y")


def _infer_subject(profile: dict[str, Any], meta: dict[str, Any]) -> str:
    """Name the rows using the identifier or file name, else 'records'."""
    identifiers = profile["roles"][P.IDENTIFIER_ROLE]
    for identifier in identifiers:
        lowered = identifier.lower()
        for token, noun in (
            ("order", "order records"), ("transaction", "transaction records"),
            ("customer", "customer records"), ("student", "student records"),
            ("employee", "employee records"), ("invoice", "invoice records"),
            ("product", "product records"), ("campaign", "campaign records"),
            ("patient", "patient records"), ("ticket", "ticket records"),
            ("account", "account records"), ("project", "project records"),
        ):
            if token in lowered:
                return noun
    filename = str(meta.get("filename", "")).lower()
    for token, noun in (
        ("sale", "sales records"), ("student", "student records"),
        ("employee", "employee records"), ("hr", "employee records"),
        ("market", "campaign records"), ("financ", "financial records"),
        ("invent", "inventory records"), ("survey", "survey responses"),
    ):
        if token in filename:
            return noun
    return "records"


def _join(items: list[str]) -> str:
    items = [str(i) for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def adapt_for_audience(insight: dict[str, Any], audience: str) -> dict[str, Any]:
    """Return the insight text tuned to the requested audience."""
    config = AUDIENCES.get(audience, AUDIENCES["manager"])
    depth = config["depth"]
    body: list[str] = [insight["fact"]]
    if depth in {"moderate", "full", "explained"}:
        body.append(insight["interpretation"])
    if insight.get("so_what") and depth != "minimal":
        body.append(insight["so_what"])
    elif insight.get("so_what") and depth == "minimal":
        body = [insight["fact"], insight["so_what"]]
    if depth == "full":
        evidence = insight.get("evidence", {})
        statistics = evidence.get("statistics")
        if statistics:
            body.append(
                "Method: " + evidence.get("calculation", "") +
                ". Statistics: " + ", ".join(
                    f"{k} = {v:.4g}" if isinstance(v, (int, float)) else f"{k} = {v}"
                    for k, v in list(statistics.items())[:6]
                    if v is not None
                ) + "."
            )
        else:
            body.append("Method: " + evidence.get("calculation", "") + ".")
        body.append(
            f"Based on {evidence.get('records_used', 0):,} records. "
            f"Confidence: {insight['confidence']} - {insight['confidence_reason']}"
        )
    if depth == "explained":
        body.append(
            f"In plain terms: this is a {insight['type_label'].lower()} finding, and the confidence "
            f"is {insight['confidence']} because {insight['confidence_reason'][0].lower()}"
            f"{insight['confidence_reason'][1:]}"
        )
    return {
        "id": insight["id"],
        "headline": insight["headline"],
        "body": " ".join(part for part in body if part),
        "recommendation": insight["recommendation"] if depth != "minimal" else insight["recommendation"],
        "confidence": insight["confidence"],
        "type": insight["type"],
        "type_label": insight["type_label"],
    }
