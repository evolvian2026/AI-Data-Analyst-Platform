"""Ask Your Data - a controlled natural-language query layer.

The pipeline is deliberately narrow:

    question -> intent detection -> column mapping -> analytical operation
             -> validated calculation -> answer (+ optional chart)

No code is ever generated or executed from a user's question. The question only
ever selects an operation from a fixed catalogue and binds columns to it, so a
hostile question can at worst produce an unhelpful answer, never execution.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines import stats_engine
from app.engines.formatting import format_delta, format_value, safe_float
from app.engines.sanitize import neutralize_text
from app.engines.trend import (
    FREQ_LABELS,
    _label,
    build_series,
    choose_frequency,
    classify_trend,
    pct_change,
)

# --- intents ----------------------------------------------------------------
TOP_N = "top_n"
BOTTOM_N = "bottom_n"
AGGREGATE = "aggregate"
TREND = "trend"
COMPARE_PERIODS = "compare_periods"
COMPARE_SEGMENTS = "compare_segments"
GROWTH = "growth"
CORRELATION = "correlation"
DISTRIBUTION = "distribution"
OUTLIERS = "outliers"
COUNT = "count"
SUMMARY = "summary"
KEY_FINDINGS = "key_findings"
RECOMMENDATIONS = "recommendations"
DATA_QUALITY = "data_quality"
DRIVER = "driver"
UNKNOWN = "unknown"

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    (KEY_FINDINGS, [r"\b(most important|key|main|biggest)\b.*\b(finding|insight|takeaway)",
                    r"what should (management|i|we) know", r"summari[sz]e .*(point|finding)",
                    r"\bwhat matters\b", r"tell me what'?s important"]),
    (RECOMMENDATIONS, [r"\brecommend", r"what should (i|we) do", r"next step", r"action"]),
    (DATA_QUALITY, [r"data quality", r"missing value", r"how (clean|reliable)", r"duplicate"]),
    (OUTLIERS, [r"\bunusual\b", r"\boutlier", r"\banomal", r"\bstrange\b", r"\bweird\b",
                r"stand out"]),
    (DRIVER, [r"what (caused|drove|is driving|explains)", r"why (did|is|has|are)",
              r"reason for", r"what (may |might )?explain", r"root cause",
              r"what.*behind the"]),
    (CORRELATION, [r"correlat", r"relationship between", r"related to", r"associated with",
                   r"depend on", r"driven by", r"\bvs\b.*\brelation"]),
    (COMPARE_PERIODS, [r"compare \d{4} (and|vs|with) \d{4}", r"year over year", r"yoy",
                       r"versus last", r"compared (with|to) (last|previous)",
                       r"\b\d{4}\s*(vs|versus|and)\s*\d{4}\b"]),
    (GROWTH, [r"grow(ing|th)? fastest", r"fastest grow", r"biggest (increase|decline|drop)",
              r"growth rate", r"which .* growing", r"declin(e|ing) most"]),
    (TREND, [r"\btrend\b", r"over time", r"\bby month\b", r"\bmonthly\b", r"\bby year\b",
             r"\byearly\b", r"\bby quarter\b", r"how has .* changed", r"changed over"]),
    (TOP_N, [r"\btop\b", r"\bbest\b", r"\bhighest\b", r"\bmost\b", r"\blargest\b", r"\bleading\b"]),
    (BOTTOM_N, [r"\bbottom\b", r"\bworst\b", r"\blowest\b", r"\bleast\b", r"\bsmallest\b"]),
    (DISTRIBUTION, [r"distribut", r"spread of", r"histogram", r"skew", r"\bmedian\b",
                    r"how (is|are) .* spread"]),
    (COMPARE_SEGMENTS, [r"\bcompare\b", r"\bversus\b", r"\bvs\b", r"\bbreak ?down\b",
                        r"\bby [a-z ]+\b.*\bfor\b", r"difference between"]),
    (COUNT, [r"how many", r"\bcount\b", r"number of records", r"how much data"]),
    (AGGREGATE, [r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bmean\b", r"\bhow much\b",
                 r"\bwhat is the\b"]),
    (SUMMARY, [r"summar", r"\boverview\b", r"describe (the|this) data", r"what is this data"]),
]

_STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "on", "by", "to", "and", "or", "is", "are", "was",
    "were", "what", "which", "who", "how", "show", "me", "give", "list", "find", "top",
    "bottom", "best", "worst", "highest", "lowest", "most", "least", "total", "sum",
    "average", "mean", "count", "number", "records", "record", "data", "dataset", "please",
    "can", "you", "do", "does", "did", "with", "from", "over", "time", "trend", "compare",
    "vs", "versus", "between", "across", "per", "each", "all", "any", "there", "that", "this",
}


@dataclass
class QueryPlan:
    intent: str
    measure: str | None = None
    dimension: str | None = None
    second_measure: str | None = None
    time_column: str | None = None
    limit: int = 10
    aggregation: str = "sum"
    matched_terms: list[str] = None
    confidence: str = "medium"


def _tokens(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9%]+", question.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def detect_intent(question: str) -> str:
    lowered = question.lower()
    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return intent
    return UNKNOWN


def _match_column(question: str, candidates: list[str]) -> tuple[str | None, float]:
    """Bind a question to a column by name overlap, then fuzzy similarity."""
    if not candidates:
        return None, 0.0
    lowered = question.lower()
    best: tuple[str | None, float] = (None, 0.0)

    for column in candidates:
        name = column.lower()
        if name in lowered:
            score = 1.0 + len(name) / 100
            if score > best[1]:
                best = (column, score)
    if best[0]:
        return best

    question_tokens = set(_tokens(question))
    for column in candidates:
        column_tokens = set(_tokens(column))
        if not column_tokens:
            continue
        overlap = len(question_tokens & column_tokens) / len(column_tokens)
        if overlap > best[1]:
            best = (column, overlap)
    if best[1] >= 0.5:
        return best

    for token in question_tokens:
        matches = difflib.get_close_matches(token, [c.lower() for c in candidates], n=1, cutoff=0.82)
        if matches:
            column = next(c for c in candidates if c.lower() == matches[0])
            return column, 0.6
    return (None, 0.0)


def _match_dimension_value(question: str, df: pd.DataFrame,
                           dimensions: list[str]) -> tuple[str | None, str | None]:
    """Spot a filter like 'in North' by matching against actual category values."""
    lowered = question.lower()
    for dimension in dimensions:
        try:
            values = df[dimension].dropna().astype(str).unique()[:500]
        except (KeyError, TypeError):
            continue
        for value in values:
            text = str(value).lower()
            if len(text) < 3:
                continue
            if re.search(rf"\b{re.escape(text)}\b", lowered):
                return dimension, str(value)
    return None, None


def build_plan(question: str, df: pd.DataFrame, profile: dict[str, Any],
               time_column: str | None, ranked_measures: list[str] | None = None) -> QueryPlan:
    measures = ranked_measures or [c["name"] for c in profile["columns"] if c["role"] == P.MEASURE]
    measures = [m for m in measures if m in df.columns]
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]
    aggregations = {
        c["name"]: (c.get("aggregation") or "sum")
        for c in profile["columns"] if c["role"] == P.MEASURE
    }

    intent = detect_intent(question)
    measure, measure_score = _match_column(question, measures)
    dimension, dimension_score = _match_column(question, dimensions + identifiers)

    second_measure = None
    if intent == CORRELATION:
        remaining = [m for m in measures if m != measure]
        second_measure, _ = _match_column(question, remaining)
        if not second_measure and len(remaining) >= 1:
            second_measure = remaining[0]

    limit_match = re.search(r"\btop\s+(\d{1,3})|\bbottom\s+(\d{1,3})|\bfirst\s+(\d{1,3})", question.lower())
    limit = 10
    if limit_match:
        limit = int(next(g for g in limit_match.groups() if g))
    limit = max(1, min(limit, 50))

    if intent == UNKNOWN:
        if measure and dimension:
            intent = TOP_N
        elif measure and time_column:
            intent = TREND
        elif measure:
            intent = AGGREGATE
        elif dimension:
            intent = COUNT
        else:
            intent = KEY_FINDINGS

    if not measure and measures and intent in {TOP_N, BOTTOM_N, TREND, AGGREGATE, GROWTH,
                                               DISTRIBUTION, OUTLIERS, COMPARE_SEGMENTS,
                                               COMPARE_PERIODS}:
        measure = measures[0]
        measure_score = 0.2
    if not dimension and dimensions and intent in {TOP_N, BOTTOM_N, COMPARE_SEGMENTS, GROWTH}:
        dimension = dimensions[0]
        dimension_score = 0.2

    confidence = "high" if (measure_score >= 1 or dimension_score >= 1) else (
        "medium" if max(measure_score, dimension_score) >= 0.5 else "low"
    )
    return QueryPlan(
        intent=intent,
        measure=measure,
        dimension=dimension,
        second_measure=second_measure,
        time_column=time_column,
        limit=limit,
        aggregation=aggregations.get(measure or "", "sum"),
        matched_terms=[t for t in (measure, dimension, second_measure) if t],
        confidence=confidence,
    )


def answer_question(
    question: str,
    df: pd.DataFrame,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Answer a natural-language question using validated calculations only."""
    question = neutralize_text(question, 400)
    profile = analysis["profile"]
    time_column = analysis.get("time_column")
    currency = profile.get("currency_symbol", "")
    types = {c["name"]: c["semantic_type"] for c in profile["columns"]}
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION]

    plan = build_plan(question, df, profile, time_column, analysis.get("ranked_measures"))
    filter_dimension, filter_value = _match_dimension_value(question, df, dimensions)
    working = df
    applied_filter = None
    if filter_dimension and filter_value and filter_dimension != plan.dimension:
        working = df[df[filter_dimension].astype(str) == filter_value]
        applied_filter = {"column": filter_dimension, "value": filter_value,
                          "records": int(len(working))}
        if working.empty:
            working = df
            applied_filter = None

    handlers = {
        TOP_N: _answer_ranking, BOTTOM_N: _answer_ranking, COMPARE_SEGMENTS: _answer_ranking,
        AGGREGATE: _answer_aggregate, COUNT: _answer_count, TREND: _answer_trend,
        GROWTH: _answer_growth, COMPARE_PERIODS: _answer_period_comparison,
        CORRELATION: _answer_correlation, DISTRIBUTION: _answer_distribution,
        OUTLIERS: _answer_outliers, KEY_FINDINGS: _answer_key_findings,
        RECOMMENDATIONS: _answer_recommendations, DATA_QUALITY: _answer_quality,
        SUMMARY: _answer_summary, DRIVER: _answer_driver,
    }
    handler = handlers.get(plan.intent, _answer_key_findings)
    result = handler(question, working, analysis, plan, currency, types)

    result.setdefault("chart", None)
    result.setdefault("table", [])
    result.setdefault("confidence", plan.confidence)
    result["question"] = question
    result["intent"] = plan.intent
    result["plan"] = {
        "intent": plan.intent,
        "measure": plan.measure,
        "dimension": plan.dimension,
        "second_measure": plan.second_measure,
        "aggregation": plan.aggregation,
        "limit": plan.limit,
        "filter": applied_filter,
    }
    result["applied_filter"] = applied_filter
    result["records_used"] = result.get("records_used", int(len(working)))
    result["caveat"] = result.get("caveat", "")
    return result


# --- handlers ---------------------------------------------------------------

def _need(plan: QueryPlan, *fields: str) -> str | None:
    for field in fields:
        if not getattr(plan, field):
            return field
    return None


def _unsupported(reason: str, suggestions: list[str]) -> dict[str, Any]:
    return {
        "answer": reason,
        "calculation": "",
        "confidence": "low",
        "supported": False,
        "suggestions": suggestions,
        "records_used": 0,
    }


def _answer_ranking(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    missing = _need(plan, "measure", "dimension")
    if missing:
        return _unsupported(
            f"This dataset does not have a {missing} that matches the question.",
            analysis.get("next_questions", [])[:4],
        )
    ascending = plan.intent == BOTTOM_N
    values = P.to_numeric_series(df[plan.measure])
    frame = pd.DataFrame({"group": df[plan.dimension].astype("string"), "value": values}).dropna()
    if frame.empty:
        return _unsupported("No records have both of those values.", [])
    grouped = frame.groupby("group")["value"]
    aggregated = grouped.sum() if plan.aggregation == "sum" else grouped.mean()
    counts = grouped.count()
    ordered = aggregated.sort_values(ascending=ascending).head(plan.limit)
    total = float(aggregated.sum())
    semantic = types.get(plan.measure, "")
    label = "Total" if plan.aggregation == "sum" else "Average"

    rows = [
        {
            "rank": position,
            plan.dimension: str(index),
            plan.measure: format_value(safe_float(value), semantic, currency),
            "records": int(counts.get(index, 0)),
            "share_pct": round(float(value) / total * 100, 2) if plan.aggregation == "sum" and total else None,
        }
        for position, (index, value) in enumerate(ordered.items(), start=1)
    ]
    # The chart needs the raw numbers; the table shows the formatted ones.
    values = [safe_float(value) for _, value in ordered.items()]
    leader = {**rows[0], "formatted": rows[0][plan.measure]}
    direction = "lowest" if ascending else "highest"
    answer = (
        f"{leader[plan.dimension]} has the {direction} {label.lower()} {plan.measure} at "
        f"{leader['formatted']} across {leader['records']:,} records"
        + (f", which is {leader['share_pct']:.1f}% of the {format_value(total, semantic, currency)} total."
           if leader["share_pct"] is not None else ".")
    )
    if len(rows) > 1:
        answer += (
            f" It is followed by {rows[1][plan.dimension]} ({rows[1][plan.measure]})"
            + (f" and {rows[2][plan.dimension]} ({rows[2][plan.measure]})."
               if len(rows) > 2 else ".")
        )
    return {
        "answer": answer,
        "calculation": (
            f"{plan.aggregation.upper()}({plan.measure}) GROUP BY {plan.dimension} "
            f"ORDER BY value {'ASC' if ascending else 'DESC'} LIMIT {plan.limit}"
        ),
        "table": rows,
        "chart": {
            "type": "horizontal_bar" if len(rows) > 5 else "bar",
            "title": f"{label} {plan.measure} by {plan.dimension}",
            "data": [
                {"name": row[plan.dimension], "value": value, "share": row["share_pct"],
                 "records": row["records"]}
                for row, value in zip(rows, values)
            ],
            "x_key": "name",
            "series": [{"key": "value", "label": plan.measure}],
            "value_format": semantic,
            "currency_symbol": currency,
        },
        "supported": True,
        "records_used": int(len(frame)),
    }


def _answer_aggregate(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if not plan.measure:
        return _unsupported("No numeric measure in this dataset matches the question.", [])
    numeric = P.to_numeric_series(df[plan.measure]).dropna()
    if numeric.empty:
        return _unsupported(f"{plan.measure} has no numeric values.", [])
    semantic = types.get(plan.measure, "")
    lowered = question.lower()
    wants_average = any(w in lowered for w in ("average", "mean", "typical", "per record"))
    aggregation = "mean" if wants_average else plan.aggregation
    value = float(numeric.mean()) if aggregation == "mean" else float(numeric.sum())
    label = "average" if aggregation == "mean" else "total"
    stats = stats_engine.describe_numeric(df[plan.measure])
    return {
        "answer": (
            f"The {label} {plan.measure} is {format_value(value, semantic, currency)} across "
            f"{len(numeric):,} records. The median is "
            f"{format_value(stats['median'], semantic, currency)}, ranging from "
            f"{format_value(stats['min'], semantic, currency)} to "
            f"{format_value(stats['max'], semantic, currency)}."
        ),
        "calculation": f"{aggregation.upper()}({plan.measure}) over {len(numeric):,} non-empty records",
        "table": [
            {"metric": "Total", "value": format_value(stats["sum"], semantic, currency)},
            {"metric": "Average", "value": format_value(stats["mean"], semantic, currency)},
            {"metric": "Median", "value": format_value(stats["median"], semantic, currency)},
            {"metric": "Minimum", "value": format_value(stats["min"], semantic, currency)},
            {"metric": "Maximum", "value": format_value(stats["max"], semantic, currency)},
            {"metric": "Records", "value": f"{stats['count']:,}"},
        ],
        "supported": True,
        "confidence": "high",
        "records_used": int(len(numeric)),
    }


def _answer_count(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if plan.dimension and plan.dimension in df.columns:
        counts = df[plan.dimension].dropna().astype(str).value_counts().head(plan.limit)
        total = int(len(df))
        rows = [
            {plan.dimension: str(index), "records": int(value),
             "share_pct": round(int(value) / total * 100, 2)}
            for index, value in counts.items()
        ]
        return {
            "answer": (
                f"The dataset holds {total:,} records across "
                f"{df[plan.dimension].nunique(dropna=True):,} distinct {plan.dimension} values. "
                f"The largest is {rows[0][plan.dimension]} with {rows[0]['records']:,} records "
                f"({rows[0]['share_pct']:.1f}%)."
            ),
            "calculation": f"COUNT(rows) GROUP BY {plan.dimension}",
            "table": rows,
            "chart": {
                "type": "horizontal_bar", "title": f"Record count by {plan.dimension}",
                "data": [{"name": r[plan.dimension], "value": r["records"]} for r in rows],
                "x_key": "name", "series": [{"key": "value", "label": "Records"}],
                "value_format": P.INTEGER, "currency_symbol": currency,
            },
            "supported": True, "confidence": "high", "records_used": total,
        }
    return {
        "answer": f"The dataset contains {len(df):,} records across {df.shape[1]} columns.",
        "calculation": "COUNT(rows)",
        "supported": True, "confidence": "high", "records_used": int(len(df)),
    }


def _answer_trend(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if not plan.time_column:
        return _unsupported(
            "This dataset has no usable date column, so a trend over time cannot be calculated.",
            ["Which segment has the highest total?", "What are the most important findings?"],
        )
    if not plan.measure:
        return _unsupported("No numeric measure matches the question.", [])
    freq, unit = choose_frequency(P.to_datetime_series(df[plan.time_column]).dropna())
    series = build_series(df, plan.time_column, plan.measure, plan.aggregation, freq)
    if len(series) < 3:
        return _unsupported(
            f"There are only {len(series)} distinct {unit}(s) of data, which is not enough to "
            f"describe a trend.", [],
        )
    classification = classify_trend(series)
    semantic = types.get(plan.measure, "")
    first, last = float(series["value"].iloc[0]), float(series["value"].iloc[-1])
    change = pct_change(last, first)
    points = [
        {"name": _label(row.period, freq), "value": safe_float(row.value), "records": int(row.records)}
        for row in series.itertuples()
    ]
    label = "Total" if plan.aggregation == "sum" else "Average"
    return {
        "answer": (
            f"{label} {plan.measure} is {classification['direction']} over the observed period: it "
            f"moved from {format_value(first, semantic, currency)} in {points[0]['name']} to "
            f"{format_value(last, semantic, currency)} in {points[-1]['name']}"
            + (f", a change of {format_delta(change)}." if change is not None
               else f", a change of {format_value(last - first, semantic, currency)}.")
            + f" The regression across {classification['periods']} {unit}s has r² = "
              f"{classification['r_squared']:.2f}."
        ),
        "calculation": (
            f"{plan.aggregation.upper()}({plan.measure}) grouped by {unit} of {plan.time_column}, "
            f"then linear regression"
        ),
        "table": points,
        "chart": {
            "type": "line", "title": f"{label} {plan.measure} over time",
            "data": points, "x_key": "name",
            "series": [{"key": "value", "label": plan.measure}],
            "value_format": semantic, "currency_symbol": currency,
        },
        "supported": True,
        "confidence": "high" if classification["confidence"] == "high" else "medium",
        "records_used": int(series["records"].sum()),
    }


def _answer_growth(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if not plan.time_column or not plan.measure or not plan.dimension:
        return _answer_trend(question, df, analysis, plan, currency, types)
    from app.engines.segments import compare_segments

    comparison = compare_segments(df, analysis["profile"], plan.dimension, plan.measure,
                                  plan.time_column, top=plan.limit)
    if not comparison or not comparison.get("has_growth"):
        return _unsupported(
            f"Growth by {plan.dimension} cannot be calculated - there is not enough history per "
            f"group.", [],
        )
    rows = [r for r in comparison["groups"] if r["growth_pct"] is not None]
    rows.sort(key=lambda r: -r["growth_pct"])
    fastest, slowest = rows[0], rows[-1]
    return {
        "answer": (
            f"{fastest['group']} is growing fastest: {plan.measure} changed "
            f"{fastest['growth_pct']:+.1f}% between the first and second halves of the period. "
            f"{slowest['group']} changed {slowest['growth_pct']:+.1f}%."
        ),
        "calculation": (
            f"{plan.aggregation.upper()}({plan.measure}) per period for each {plan.dimension}, "
            f"first half vs second half"
        ),
        "table": [
            {plan.dimension: r["group"], "growth_pct": r["growth_pct"],
             plan.measure: r["formatted_value"], "records": r["count"]}
            for r in rows
        ],
        "chart": {
            "type": "bar", "title": f"{plan.measure} growth by {plan.dimension}",
            "data": [{"name": r["group"], "value": r["growth_pct"]} for r in rows],
            "x_key": "name", "series": [{"key": "value", "label": "Change %"}],
            "value_format": P.PERCENTAGE, "currency_symbol": currency,
        },
        "supported": True, "confidence": "medium",
        "records_used": int(sum(r["count"] for r in rows)),
        "caveat": "The split point between halves is mechanical, not tied to a known event.",
    }


def _answer_period_comparison(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if not plan.time_column or not plan.measure:
        return _unsupported("A date column and a numeric measure are needed to compare periods.", [])
    years = [int(y) for y in re.findall(r"\b(19|20)\d{2}\b", question)] or []
    full_years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", question)]
    dates = P.to_datetime_series(df[plan.time_column])
    values = P.to_numeric_series(df[plan.measure])
    frame = pd.DataFrame({"date": dates, "value": values}).dropna()
    semantic = types.get(plan.measure, "")

    if len(full_years) >= 2:
        left_year, right_year = full_years[0], full_years[1]
        left = frame.loc[frame["date"].dt.year == left_year, "value"]
        right = frame.loc[frame["date"].dt.year == right_year, "value"]
        if left.empty or right.empty:
            available = sorted(frame["date"].dt.year.unique().tolist())
            return _unsupported(
                f"The dataset does not contain data for both {left_year} and {right_year}. "
                f"Years available: {', '.join(str(y) for y in available)}.", [],
            )
        left_value = float(left.sum()) if plan.aggregation == "sum" else float(left.mean())
        right_value = float(right.sum()) if plan.aggregation == "sum" else float(right.mean())
        change = pct_change(right_value, left_value)
        return {
            "answer": (
                f"{plan.measure} was {format_value(left_value, semantic, currency)} in {left_year} "
                f"({len(left):,} records) and {format_value(right_value, semantic, currency)} in "
                f"{right_year} ({len(right):,} records)"
                + (f", a change of {format_delta(change)}." if change is not None
                   else f", a change of {format_value(right_value - left_value, semantic, currency)}.")
            ),
            "calculation": (
                f"{plan.aggregation.upper()}({plan.measure}) WHERE year({plan.time_column}) = "
                f"{left_year} versus {right_year}"
            ),
            "table": [
                {"period": str(left_year), plan.measure: format_value(left_value, semantic, currency),
                 "records": int(len(left))},
                {"period": str(right_year), plan.measure: format_value(right_value, semantic, currency),
                 "records": int(len(right))},
            ],
            "chart": {
                "type": "bar", "title": f"{plan.measure}: {left_year} vs {right_year}",
                "data": [{"name": str(left_year), "value": safe_float(left_value)},
                         {"name": str(right_year), "value": safe_float(right_value)}],
                "x_key": "name", "series": [{"key": "value", "label": plan.measure}],
                "value_format": semantic, "currency_symbol": currency,
            },
            "supported": True, "confidence": "high",
            "records_used": int(len(left) + len(right)),
        }

    trend = next((t for t in analysis.get("trends", []) if t["measure"] == plan.measure), None)
    if trend and trend.get("comparisons"):
        comparison = trend["comparisons"][0]
        return {
            "answer": (
                f"{comparison['label']}: {plan.measure} was "
                f"{format_value(comparison['current'], semantic, currency)} in "
                f"{comparison['current_label']} versus "
                f"{format_value(comparison['previous'], semantic, currency)} in "
                f"{comparison['previous_label']}, a change of "
                f"{format_delta(comparison['change_pct'])}."
            ),
            "calculation": f"{plan.aggregation.upper()}({plan.measure}) per period, consecutive comparison",
            "table": trend["comparisons"],
            "supported": True, "confidence": "high",
            "records_used": int(sum(p["records"] for p in trend["points"])),
        }
    return _answer_trend(question, df, analysis, plan, currency, types)


def _answer_correlation(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    correlations = analysis.get("correlations", {})
    if not correlations.get("available"):
        return _unsupported(
            correlations.get("reason", "Correlations need at least two numeric measures."), [],
        )
    pair = None
    if plan.measure and plan.second_measure:
        for candidate in correlations["pairs"]:
            if {candidate["x"], candidate["y"]} == {plan.measure, plan.second_measure}:
                pair = candidate
                break
    if not pair:
        pair = (correlations.get("meaningful") or correlations["pairs"])[0]
    return {
        "answer": pair["narrative"] + " " + correlations["caveat"],
        "calculation": "Pearson correlation on records where both values are present",
        "table": [
            {"pair": f"{p['x']} ~ {p['y']}", "r": round(p["pearson_r"], 3),
             "strength": p["strength"], "observations": p["observations"],
             "significant": p["significant"]}
            for p in correlations["pairs"][:10]
        ],
        "chart": {
            "type": "scatter", "title": f"{pair['y']} vs {pair['x']}",
            "data": _scatter(df, pair["x"], pair["y"]),
            "x_key": "x", "series": [{"key": "y", "label": pair["y"]}],
            "x_label": pair["x"], "y_label": pair["y"],
            "value_format": types.get(pair["y"], ""), "currency_symbol": currency,
        },
        "supported": True, "confidence": "medium",
        "records_used": pair["observations"],
        "caveat": correlations["caveat"],
    }


def _scatter(df: pd.DataFrame, x: str, y: str, limit: int = 600) -> list[dict[str, Any]]:
    frame = pd.DataFrame({"x": P.to_numeric_series(df[x]), "y": P.to_numeric_series(df[y])}).dropna()
    if len(frame) > limit:
        frame = frame.sample(limit, random_state=11)
    return [{"x": safe_float(row.x), "y": safe_float(row.y)} for row in frame.itertuples()]


def _answer_distribution(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    if not plan.measure:
        return _unsupported("No numeric measure matches the question.", [])
    stats = stats_engine.describe_numeric(df[plan.measure])
    if not stats:
        return _unsupported(f"{plan.measure} has no numeric values.", [])
    semantic = types.get(plan.measure, "")
    bins = stats_engine.histogram(df[plan.measure])
    interpretation = stats_engine.interpret_distribution(plan.measure, stats, semantic, currency)
    answer = (
        f"{plan.measure} has a mean of {format_value(stats['mean'], semantic, currency)} and a "
        f"median of {format_value(stats['median'], semantic, currency)}, ranging from "
        f"{format_value(stats['min'], semantic, currency)} to "
        f"{format_value(stats['max'], semantic, currency)} "
        f"(standard deviation {format_value(stats['std'], semantic, currency)})."
    )
    if interpretation:
        answer += " " + interpretation["narrative"]
    return {
        "answer": answer,
        "calculation": f"Descriptive statistics of {plan.measure} over {stats['count']:,} records",
        "table": [
            {"metric": key.title(), "value": format_value(stats[key], semantic, currency)}
            for key in ("mean", "median", "std", "min", "q1", "q3", "max")
        ],
        "chart": {
            "type": "histogram", "title": f"Distribution of {plan.measure}",
            "data": [{"name": b["bin"], "value": b["count"]} for b in bins],
            "x_key": "name", "series": [{"key": "value", "label": "Records"}],
            "value_format": P.INTEGER, "currency_symbol": currency,
        },
        "supported": True, "confidence": "high", "records_used": stats["count"],
    }


def _answer_outliers(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    anomalies = analysis.get("anomalies", {})
    items = anomalies.get("items", [])
    if plan.measure:
        items = [i for i in items if i["column"] == plan.measure] or items
    if not items:
        return {
            "answer": "No statistically unusual records or periods were detected in this dataset.",
            "calculation": "IQR fences plus modified z-score on every numeric measure",
            "supported": True, "confidence": "high", "records_used": int(len(df)),
        }
    top = items[0]
    return {
        "answer": (
            f"{top['headline']}. In total {anomalies['total']} anomaly finding(s) were detected "
            f"across {len(anomalies['affected_columns'])} column(s), affecting "
            f"{anomalies['affected_records']:,} records "
            f"({anomalies['affected_pct']:.2f}% of the dataset)."
        ),
        "calculation": top["method"],
        "table": [
            {"finding": i["headline"], "column": i["column"], "severity": i["severity"],
             "score": i["max_score"]}
            for i in items[:10]
        ],
        "supported": True, "confidence": "high",
        "records_used": anomalies.get("affected_records", 0),
        "anomaly_id": top["id"],
    }


def _answer_key_findings(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    insights = analysis.get("insights", [])[:5]
    if not insights:
        return {
            "answer": "No statistically notable pattern was found in this dataset.",
            "calculation": "Insight discovery across trends, segments, anomalies and correlations",
            "supported": True, "confidence": "high", "records_used": int(len(df)),
        }
    return {
        "answer": " ".join(f"{position}. {i['headline']}." for position, i in enumerate(insights, 1)),
        "calculation": "Findings ranked by the insight priority score",
        "table": [
            {"rank": i["rank"], "type": i["type_label"], "finding": i["headline"],
             "confidence": i["confidence"], "score": i["priority"]["score"]}
            for i in insights
        ],
        "supported": True, "confidence": "high",
        "records_used": analysis["profile"]["row_count"],
        "insight_ids": [i["id"] for i in insights],
    }


def _answer_recommendations(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    recommendations = analysis.get("recommendations", [])[:5]
    if not recommendations:
        return {
            "answer": "No data-supported recommendations were generated for this dataset.",
            "calculation": "Derived from ranked findings", "supported": True,
            "confidence": "high", "records_used": int(len(df)),
        }
    return {
        "answer": " ".join(
            f"{position}. [{r['priority'].upper()}] {r['action']}"
            for position, r in enumerate(recommendations, 1)
        ),
        "calculation": "Recommendations derived from the highest-priority findings",
        "table": [
            {"priority": r["priority"], "action": r["action"], "rationale": r["rationale"]}
            for r in recommendations
        ],
        "supported": True, "confidence": "medium",
        "records_used": analysis["profile"]["row_count"],
    }


def _answer_quality(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    quality = analysis.get("quality", {})
    return {
        "answer": (
            f"Data quality scores {quality.get('score', 0):.0f}/100 ({quality.get('grade')}). "
            + quality.get("explanation", "")
        ),
        "calculation": "Weighted completeness, uniqueness, validity, consistency and structure",
        "table": [
            {"issue": i["title"], "severity": i["severity"], "impact": i["impact"]}
            for i in quality.get("issues", [])[:10]
        ],
        "supported": True, "confidence": "high",
        "records_used": quality.get("metrics", {}).get("rows", len(df)),
    }


def _answer_summary(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    return {
        "answer": analysis.get("summary", "") + " " + analysis["story"]["sections"][0]["narrative"],
        "calculation": "Dataset profile plus the ranked findings",
        "supported": True, "confidence": "high",
        "records_used": analysis["profile"]["row_count"],
    }


def _answer_driver(question, df, analysis, plan, currency, types) -> dict[str, Any]:
    """What appears to be driving a change - association, never causation."""
    investigations = analysis.get("investigations", [])
    if plan.measure:
        matching = [i for i in investigations if i.get("measure") == plan.measure]
        investigations = matching or investigations
    drivers = [i for i in analysis.get("insights", []) if i["type"] == "driver"]

    if not investigations and not drivers:
        segments = analysis.get("segments", [])
        if plan.measure:
            segments = [s for s in segments if s["measure"] == plan.measure] or segments
        if segments:
            plan.dimension = plan.dimension or segments[0]["dimension"]
            result = _answer_ranking(question, df, analysis, plan, currency, types)
            result["caveat"] = (
                "This shows where the measure is concentrated. It does not establish cause - a "
                "factor outside this dataset may be responsible."
            )
            result["confidence"] = "low"
            return result
        return _unsupported(
            "No dimension in this dataset separates the change enough to point at a driver.", [],
        )

    investigation = investigations[0] if investigations else None
    lines: list[str] = []
    if investigation:
        lines.extend(investigation.get("explanations", [])[:3])
    for driver in drivers[:2]:
        if driver["fact"] not in lines:
            lines.append(driver["fact"])

    return {
        "answer": " ".join(lines) if lines else drivers[0]["fact"],
        "calculation": (
            f"Share of {investigation['measure']} by each dimension inside the flagged records "
            f"versus the rest of the dataset"
            if investigation else "Segment decomposition of the flagged change"
        ),
        "table": (
            [
                {"dimension": c["dimension"], "value": c["top_value"],
                 "share_pct": c["top_share_pct"], "normal_share_pct": c["rows"][0]["normal_share_pct"],
                 "shift_pts": c["top_shift_pct"]}
                for c in investigation["contributions"]
            ] if investigation else
            [{"finding": d["headline"], "confidence": d["confidence"]} for d in drivers[:5]]
        ),
        "supported": True,
        "confidence": "medium",
        "records_used": investigation["records_examined"] if investigation else len(df),
        "caveat": (
            investigation.get("caveat") if investigation else
            "These findings show association, not causation."
        ),
        "next_questions": investigation.get("next_questions", []) if investigation else [],
    }


def suggested_questions(analysis: dict[str, Any]) -> list[str]:
    """Starter questions generated from the columns this dataset actually has."""
    profile = analysis["profile"]
    measures = analysis.get("ranked_measures") or profile["roles"][P.MEASURE]
    dimensions = profile["roles"][P.DIMENSION]
    time_column = analysis.get("time_column")
    questions = ["What are the most important findings?"]
    if measures and dimensions:
        questions.append(f"Show the top 10 {dimensions[0]} by {measures[0]}")
        questions.append(f"Which {dimensions[0]} has the lowest {measures[0]}?")
    if measures and time_column:
        questions.append(f"How has {measures[0]} changed over time?")
    if measures and dimensions and time_column:
        questions.append(f"Which {dimensions[0]} is growing fastest?")
    if len(measures) >= 2:
        questions.append(f"Is {measures[0]} related to {measures[1]}?")
    if measures:
        questions.append(f"What is driving the change in {measures[0]}?")
    questions.append("Find unusual records")
    questions.append("What should management know?")
    questions.append("How reliable is this data?")
    return questions[:8]
