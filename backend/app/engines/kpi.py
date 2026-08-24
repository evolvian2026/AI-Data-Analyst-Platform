"""KPI engine.

Selects the handful of metrics that actually matter instead of emitting a wall
of cards. Derived metrics (margin, conversion rate, per-customer averages) are
produced only when the underlying columns make them mathematically valid, and
are always labelled as derived with the formula attached.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import compact_number, format_value, safe_float
from app.engines.trend import build_series, choose_frequency, pct_change

# Column-name families used to spot valid derived metrics.
_FAMILIES = {
    "revenue": ("revenue", "sales", "turnover", "income", "gmv", "amount", "billing"),
    "profit": ("profit", "margin amount", "net income", "earnings", "surplus"),
    "cost": ("cost", "expense", "cogs", "spend", "opex"),
    "quantity": ("quantity", "qty", "units", "volume", "orders", "transactions"),
    "customers": ("customer", "client", "account", "user", "member", "subscriber"),
    "clicks": ("click",),
    "impressions": ("impression", "views", "reach"),
    "conversions": ("conversion", "purchase", "signup", "sale count"),
    "leads": ("lead", "enquiry", "inquiry", "prospect"),
    "budget": ("budget", "target", "forecast", "plan"),
}


def _family(name: str) -> str | None:
    lowered = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower())
    for family, tokens in _FAMILIES.items():
        if any(token in lowered for token in tokens):
            return family
    return None


def _find(columns: list[str], family: str) -> str | None:
    for column in columns:
        if _family(column) == family:
            return column
    return None


def _aggregation_for(column_profile: dict[str, Any]) -> str:
    """Additive measures get summed; rates and scores get averaged."""
    name = column_profile["name"].lower()
    semantic = column_profile["semantic_type"]
    if semantic == P.PERCENTAGE:
        return "mean"
    if any(token in name for token in ("rate", "ratio", "score", "rating", "index", "average",
                                       "avg", "per ", "%", "margin %", "utilisation", "utilization")):
        return "mean"
    if semantic in {P.CURRENCY, P.DECIMAL, P.INTEGER}:
        if any(token in name for token in ("price", "age", "tenure", "years", "hours", "duration",
                                           "temperature", "weight", "height", "balance", "level")):
            return "mean"
        return "sum"
    return "sum"


def _relevance(name: str) -> float:
    lowered = name.lower()
    weights = [
        (("revenue", "sales", "profit", "income", "turnover", "gmv"), 30),
        (("cost", "expense", "spend", "budget"), 22),
        (("margin", "conversion", "growth", "churn", "attrition"), 20),
        (("quantity", "units", "orders", "volume", "count", "headcount"), 16),
        (("score", "rating", "marks", "salary", "attendance"), 14),
    ]
    for tokens, weight in weights:
        if any(token in lowered for token in tokens):
            return weight
    return 8.0


def build_kpis(
    df: pd.DataFrame,
    profile: dict[str, Any],
    time_column: str | None,
    max_primary: int = 8,
) -> dict[str, Any]:
    columns = {c["name"]: c for c in profile["columns"]}
    measures = [c for c in profile["columns"] if c["role"] == P.MEASURE]
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]
    currency = profile.get("currency_symbol", "")
    row_count = int(len(df))

    kpis: list[dict[str, Any]] = []

    # --- record count is always relevant ------------------------------------
    kpis.append(
        _kpi(
            key="record_count",
            label="Total Records",
            value=row_count,
            formatted=f"{row_count:,}",
            aggregation="count",
            source_columns=[],
            calculation="COUNT(rows)",
            math={"formula": "COUNT(rows)", "substitution": f"{row_count:,} rows",
                  "result": f"{row_count:,}"},
            relevance=12,
            magnitude=6,
            records_used=row_count,
            description="Number of rows analysed after removing empty rows.",
        )
    )

    # --- direct measure KPIs -------------------------------------------------
    for column in measures:
        name = column["name"]
        numeric = P.to_numeric_series(df[name]).dropna()
        if numeric.empty:
            continue
        aggregation = column.get("aggregation") or _aggregation_for(column)
        value = float(numeric.sum()) if aggregation == "sum" else float(numeric.mean())
        semantic = column["semantic_type"]
        label = f"{'Total' if aggregation == 'sum' else 'Average'} {name}"
        formula = f"{'SUM' if aggregation == 'sum' else 'AVERAGE'}({name})"
        kpis.append(
            _kpi(
                key=f"measure::{name}::{aggregation}",
                label=label,
                value=value,
                formatted=format_value(value, semantic, currency),
                aggregation=aggregation,
                source_columns=[name],
                calculation=formula,
                math={
                    "formula": formula,
                    "substitution": (
                        f"SUM of {len(numeric):,} values"
                        if aggregation == "sum"
                        else f"{format_value(float(numeric.sum()), semantic, currency)} ÷ {len(numeric):,}"
                    ),
                    "result": format_value(value, semantic, currency),
                },
                relevance=_relevance(name),
                magnitude=float(np.log10(abs(value) + 1) * 3),
                records_used=int(len(numeric)),
                semantic_type=semantic,
                secondary={
                    "median": format_value(safe_float(numeric.median()), semantic, currency),
                    "min": format_value(safe_float(numeric.min()), semantic, currency),
                    "max": format_value(safe_float(numeric.max()), semantic, currency),
                    "count": int(len(numeric)),
                    "distinct": int(numeric.nunique()),
                },
                description=(
                    f"{'Sum' if aggregation == 'sum' else 'Mean'} of {name} across "
                    f"{len(numeric):,} non-empty records."
                ),
            )
        )

    # --- distinct counts for identifiers and key dimensions -----------------
    for name in (identifiers[:2] + dimensions[:3]):
        if name not in df.columns:
            continue
        distinct = int(df[name].nunique(dropna=True))
        if distinct <= 1 or distinct == row_count:
            continue
        kpis.append(
            _kpi(
                key=f"distinct::{name}",
                label=f"Distinct {name}",
                value=distinct,
                formatted=f"{distinct:,}",
                aggregation="distinct",
                source_columns=[name],
                calculation=f"COUNT(DISTINCT {name})",
                math={"formula": f"COUNT(DISTINCT {name})",
                      "substitution": f"{distinct:,} unique values in {row_count:,} rows",
                      "result": f"{distinct:,}"},
                relevance=11 if name in identifiers else 9,
                magnitude=float(np.log10(distinct + 1) * 2),
                records_used=int(df[name].notna().sum()),
                description=f"Number of unique {name} values in the dataset.",
            )
        )

    # --- derived metrics -----------------------------------------------------
    kpis.extend(_derived_kpis(df, profile, columns, currency))

    # --- growth --------------------------------------------------------------
    growth_kpis = _growth_kpis(df, profile, time_column, measures, currency)
    kpis.extend(growth_kpis)

    # --- scoring -------------------------------------------------------------
    for kpi in kpis:
        coverage = kpi["records_used"] / max(row_count, 1) * 100 if kpi["records_used"] else 100
        kpi["priority_components"] = {
            "relevance": round(kpi.pop("_relevance"), 1),
            "magnitude": round(min(kpi.pop("_magnitude"), 20), 1),
            "availability": round(coverage / 5, 1),
            "analytical_usefulness": round(kpi.pop("_usefulness"), 1),
        }
        kpi["priority_score"] = round(sum(kpi["priority_components"].values()), 1)

    kpis.sort(key=lambda k: -k["priority_score"])

    # Keep the KPI strip diverse: at most two cards per source column.
    primary: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for kpi in kpis:
        signature = kpi["source_columns"][0] if kpi["source_columns"] else kpi["key"]
        if used.get(signature, 0) >= 2:
            continue
        used[signature] = used.get(signature, 0) + 1
        primary.append(kpi)
        if len(primary) >= max_primary:
            break

    return {
        "primary": primary,
        "all": kpis,
        "count": len(kpis),
        "currency_symbol": currency,
    }


def _kpi(
    key: str, label: str, value: Any, formatted: str, aggregation: str,
    source_columns: list[str], calculation: str, math: dict[str, str],
    relevance: float, magnitude: float, records_used: int,
    semantic_type: str = "", secondary: dict[str, Any] | None = None,
    description: str = "", derived: bool = False, change: dict[str, Any] | None = None,
    usefulness: float = 8.0,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": safe_float(value) if isinstance(value, (int, float, np.number)) else value,
        "formatted": formatted,
        "aggregation": aggregation,
        "source_columns": source_columns,
        "calculation": calculation,
        "math": math,
        "records_used": int(records_used),
        "semantic_type": semantic_type,
        "secondary": secondary or {},
        "description": description,
        "derived": derived,
        "change": change,
        "_relevance": relevance,
        "_magnitude": magnitude,
        "_usefulness": usefulness,
    }


def _derived_kpis(
    df: pd.DataFrame, profile: dict[str, Any], columns: dict[str, Any], currency: str,
) -> list[dict[str, Any]]:
    measure_names = [c["name"] for c in profile["columns"] if c["role"] == P.MEASURE]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]
    results: list[dict[str, Any]] = []
    row_count = len(df)

    def total(column: str) -> float | None:
        series = P.to_numeric_series(df[column]).dropna()
        return float(series.sum()) if len(series) else None

    revenue = _find(measure_names, "revenue")
    profit = _find(measure_names, "profit")
    cost = _find(measure_names, "cost")
    quantity = _find(measure_names, "quantity")
    clicks = _find(measure_names, "clicks")
    impressions = _find(measure_names, "impressions")
    conversions = _find(measure_names, "conversions")
    budget = _find(measure_names, "budget")
    # A column that is the budget is not also "spend"; treating it as both would
    # emit the same ratio twice under two different names.
    spend = next(
        (c for c in measure_names
         if ("spend" in c.lower() or "budget" in c.lower()) and c != budget),
        None,
    )

    def ratio_kpi(key, label, numerator_col, denominator_col, numerator, denominator,
                  formula, as_percent, relevance, description, unit_semantic=""):
        if not numerator or not denominator:
            return
        value = numerator / denominator * (100 if as_percent else 1)
        formatted = f"{value:,.1f}%" if as_percent else compact_number(
            value, currency if unit_semantic == P.CURRENCY else ""
        )
        results.append(
            _kpi(
                key=key, label=label, value=value, formatted=formatted, aggregation="derived",
                source_columns=[numerator_col, denominator_col], calculation=formula,
                math={
                    "formula": formula,
                    "substitution": (
                        f"({compact_number(numerator, currency)} ÷ {compact_number(denominator, currency)})"
                        + (" × 100" if as_percent else "")
                    ),
                    "result": formatted,
                },
                relevance=relevance,
                magnitude=8.0,
                records_used=row_count,
                semantic_type=P.PERCENTAGE if as_percent else unit_semantic,
                description=description,
                derived=True,
                usefulness=14.0,
            )
        )

    if revenue and profit and revenue != profit:
        total_revenue, total_profit = total(revenue), total(profit)
        if total_revenue:
            ratio_kpi(
                "derived::profit_margin", "Profit Margin (derived)", profit, revenue,
                total_profit, total_revenue, f"({profit} ÷ {revenue}) × 100", True, 30,
                f"Share of {revenue} retained as {profit}.",
            )
    if revenue and cost and not profit:
        total_revenue, total_cost = total(revenue), total(cost)
        if total_revenue and total_cost is not None:
            ratio_kpi(
                "derived::gross_margin", f"Margin of {revenue} over {cost} (derived)", revenue, cost,
                total_revenue - total_cost, total_revenue,
                f"(({revenue} − {cost}) ÷ {revenue}) × 100", True, 28,
                f"Share of {revenue} left after {cost}.",
            )
    if revenue and quantity:
        total_revenue, total_quantity = total(revenue), total(quantity)
        if total_quantity:
            ratio_kpi(
                "derived::revenue_per_unit", f"{revenue} per {quantity} (derived)", revenue, quantity,
                total_revenue, total_quantity, f"{revenue} ÷ {quantity}", False, 20,
                f"Average {revenue} generated per unit of {quantity}.",
                unit_semantic=columns.get(revenue, {}).get("semantic_type", ""),
            )
    if clicks and impressions:
        total_clicks, total_impressions = total(clicks), total(impressions)
        if total_impressions:
            ratio_kpi(
                "derived::ctr", "Click-through Rate (derived)", clicks, impressions,
                total_clicks, total_impressions, f"({clicks} ÷ {impressions}) × 100", True, 24,
                "Share of impressions that produced a click.",
            )
    if conversions and clicks:
        total_conversions, total_clicks = total(conversions), total(clicks)
        if total_clicks:
            ratio_kpi(
                "derived::cvr", "Conversion Rate (derived)", conversions, clicks,
                total_conversions, total_clicks, f"({conversions} ÷ {clicks}) × 100", True, 26,
                "Share of clicks that converted.",
            )
    if spend and conversions:
        total_spend, total_conversions = total(spend), total(conversions)
        if total_conversions:
            ratio_kpi(
                "derived::cpa", f"{spend} per {conversions} (derived)", spend, conversions,
                total_spend, total_conversions, f"{spend} ÷ {conversions}", False, 25,
                "Average spend required per conversion.",
                unit_semantic=columns.get(spend, {}).get("semantic_type", ""),
            )
    if revenue and spend and revenue != spend:
        total_revenue, total_spend = total(revenue), total(spend)
        if total_spend:
            ratio_kpi(
                "derived::roas", f"{revenue} per unit of {spend} (derived)", revenue, spend,
                total_revenue, total_spend, f"{revenue} ÷ {spend}", False, 26,
                f"{revenue} generated per unit of {spend}.",
            )
    if budget and revenue and budget != revenue:
        total_budget, total_revenue = total(budget), total(revenue)
        if total_budget:
            ratio_kpi(
                "derived::budget_attainment", "Budget Attainment (derived)", revenue, budget,
                total_revenue, total_budget, f"({revenue} ÷ {budget}) × 100", True, 24,
                f"Actual {revenue} as a share of {budget}.",
            )

    # Per-entity averages, e.g. orders per customer.
    customer_column = next(
        (c for c in identifiers + [col["name"] for col in profile["columns"] if col["role"] == P.DIMENSION]
         if _family(c) == "customers"),
        None,
    )
    if customer_column and customer_column in df.columns:
        distinct_customers = int(df[customer_column].nunique(dropna=True))
        if 1 < distinct_customers < row_count:
            ratio_kpi(
                "derived::records_per_customer", f"Records per {customer_column} (derived)",
                customer_column, customer_column, float(row_count), float(distinct_customers),
                f"COUNT(rows) ÷ COUNT(DISTINCT {customer_column})", False, 18,
                f"Average number of records per distinct {customer_column}.",
            )
            if revenue:
                total_revenue = total(revenue)
                if total_revenue:
                    ratio_kpi(
                        "derived::revenue_per_customer", f"{revenue} per {customer_column} (derived)",
                        revenue, customer_column, total_revenue, float(distinct_customers),
                        f"SUM({revenue}) ÷ COUNT(DISTINCT {customer_column})", False, 22,
                        f"Average {revenue} per distinct {customer_column}.",
                        unit_semantic=columns.get(revenue, {}).get("semantic_type", ""),
                    )
    return results


def _growth_kpis(
    df: pd.DataFrame, profile: dict[str, Any], time_column: str | None,
    measures: list[dict[str, Any]], currency: str,
) -> list[dict[str, Any]]:
    if not time_column:
        return []
    results = []
    dates = P.to_datetime_series(df[time_column]).dropna()
    if dates.empty:
        return []
    freq, unit = choose_frequency(dates)
    for column in measures[:4]:
        name = column["name"]
        aggregation = column.get("aggregation") or _aggregation_for(column)
        series = build_series(df, time_column, name, aggregation, freq)
        if len(series) < 4:
            continue
        values = series["value"].to_numpy(dtype=float)
        current, previous = float(values[-1]), float(values[-2])
        change_pct = pct_change(current, previous)
        if change_pct is None:
            continue
        semantic = column["semantic_type"]
        results.append(
            _kpi(
                key=f"growth::{name}",
                label=f"{name} {unit.title()}-over-{unit.title()} Change",
                value=change_pct,
                formatted=f"{change_pct:+,.1f}%",
                aggregation="growth",
                source_columns=[name, time_column],
                calculation=f"((current {unit} − previous {unit}) ÷ previous {unit}) × 100",
                math={
                    "formula": "((Current − Previous) ÷ Previous) × 100",
                    "substitution": (
                        f"(({format_value(current, semantic, currency)} − "
                        f"{format_value(previous, semantic, currency)}) ÷ "
                        f"{format_value(previous, semantic, currency)}) × 100"
                    ),
                    "result": f"{change_pct:+,.1f}%",
                },
                relevance=_relevance(name) * 0.9 + 8,
                magnitude=min(abs(change_pct) / 3, 18),
                records_used=int(series["records"].iloc[-1] + series["records"].iloc[-2]),
                semantic_type=P.PERCENTAGE,
                secondary={
                    "current_period": series["period"].iloc[-1].strftime("%b %Y"),
                    "previous_period": series["period"].iloc[-2].strftime("%b %Y"),
                    "current": format_value(current, semantic, currency),
                    "previous": format_value(previous, semantic, currency),
                },
                description=f"Change in {name} between the two most recent complete {unit}s.",
                usefulness=16.0,
                change={"direction": "up" if change_pct >= 0 else "down", "pct": round(change_pct, 1)},
            )
        )
    return results
