"""Visualization engine.

Charts are selected to answer analytical questions, not to fill space. Every
chart carries the question it answers, the columns and calculation behind it,
why it was selected and the insight it supports. A de-duplication pass removes
charts that would show the same relationship twice.
"""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pandas as pd

from app.engines import profiler as P
from app.engines.formatting import format_value, safe_float
from app.engines.stats_engine import box_summary, categorical_summary, histogram
from app.engines.trend import _label, build_series, choose_frequency

BAR = "bar"
HORIZONTAL_BAR = "horizontal_bar"
LINE = "line"
AREA = "area"
STACKED_BAR = "stacked_bar"
HISTOGRAM = "histogram"
BOX = "box"
SCATTER = "scatter"
DONUT = "donut"
HEATMAP = "heatmap"
CORRELATION_MATRIX = "correlation_matrix"
PARETO = "pareto"
MAP = "geographic"


class ChartBuilder:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.currency = profile.get("currency_symbol", "")
        self.types = {c["name"]: c["semantic_type"] for c in profile["columns"]}
        self._charts: list[dict[str, Any]] = []
        self._counter = itertools.count(1)
        self._signatures: set[str] = set()

    def add(
        self, *, chart_type: str, title: str, question: str, reason: str,
        columns: list[str], calculation: str, data: list[dict[str, Any]],
        x_key: str, series: list[dict[str, Any]], insight: str = "",
        value_format: str = "", drilldown: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None, signature: str | None = None,
        priority: float = 50.0,
    ) -> dict[str, Any] | None:
        signature = signature or f"{chart_type}:{'|'.join(sorted(columns))}"
        if signature in self._signatures or not data:
            return None
        self._signatures.add(signature)
        chart = {
            "id": f"chart_{next(self._counter):02d}",
            "type": chart_type,
            "title": title,
            "question": question,
            "reason": reason,
            "columns": columns,
            "calculation": calculation,
            "insight": insight,
            "data": data,
            "x_key": x_key,
            "series": series,
            "value_format": value_format,
            "currency_symbol": self.currency,
            "drilldown": drilldown,
            "priority": priority,
            **(extra or {}),
        }
        self._charts.append(chart)
        return chart

    @property
    def charts(self) -> list[dict[str, Any]]:
        return self._charts


def _fmt(value: Any, semantic: str, currency: str) -> str:
    return format_value(value, semantic, currency)


def _trend_caption(trend: dict[str, Any], classification: dict[str, Any], measure: str) -> str:
    """Describe the series without contradicting itself.

    A series can end well below where it started and still have no significant
    trend, so "stable (-41%)" has to be said as two separate facts.
    """
    direction = classification.get("direction", "stable")
    change = trend.get("total_change_pct")
    label = trend.get("aggregation_label", "Total")
    if direction in {"increasing", "decreasing"} and change is not None:
        return (
            f"{label} {measure} is {direction}: {change:+.1f}% from {trend['first_period']} to "
            f"{trend['last_period']}."
        )
    if direction == "stable":
        ending = (
            f" It ended the period {change:+.1f}% against its first {trend['unit']}, but the "
            f"movement is within the normal variation of this series."
            if change is not None else ""
        )
        return f"{label} {measure} shows no statistically significant trend.{ending}"
    return f"{label} {measure} has too few periods to establish a trend."


def build_charts(
    df: pd.DataFrame,
    context: dict[str, Any],
    max_charts: int = 14,
) -> list[dict[str, Any]]:
    profile = context["profile"]
    builder = ChartBuilder(profile)
    currency = builder.currency
    types = builder.types

    measures = [c["name"] for c in profile["columns"] if c["role"] == P.MEASURE]
    dimensions = [c["name"] for c in profile["columns"] if c["role"] == P.DIMENSION]
    geo_dimensions = [
        c["name"] for c in profile["columns"]
        if c["role"] == P.DIMENSION and c["semantic_type"] == P.GEOGRAPHIC
    ]
    time_column = context.get("time_column")
    primary_measure = measures[0] if measures else None
    primary_additive = bool(
        primary_measure and next(
            (c.get("additive", True) for c in profile["columns"] if c["name"] == primary_measure),
            True,
        )
    )
    primary_agg = "sum" if primary_additive else "mean"
    primary_agg_label = "Total" if primary_additive else "Average"

    # --- 1. Trend of the leading measures -----------------------------------
    for trend in context.get("trends", [])[:3]:
        measure = trend["measure"]
        semantic = types.get(measure, "")
        classification = trend["classification"]
        builder.add(
            chart_type=LINE if len(trend["points"]) > 12 else AREA,
            title=f"{trend.get('aggregation_label', 'Total')} {measure} over time",
            question=f"How has {measure} changed over time?",
            reason=(
                f"A time dimension ({trend['time_column']}) exists, so the shape of the "
                f"{trend.get('aggregation_label', 'total').lower()} {measure} series is the first "
                f"thing to establish."
            ),
            columns=[measure, trend["time_column"]],
            calculation=(
                f"{trend.get('aggregation', 'sum').upper()}({measure}) grouped by {trend['unit']} "
                f"of {trend['time_column']}"
            ),
            data=[
                {"name": point["label"], "value": point["value"], "records": point["records"]}
                for point in trend["points"]
            ],
            x_key="name",
            series=[{"key": "value", "label": measure}],
            insight=_trend_caption(trend, classification, measure),
            value_format=semantic,
            drilldown={"type": "period", "measure": measure, "time_column": trend["time_column"]},
            priority=95 - len(builder.charts),
            signature=f"trend:{measure}",
        )

    # --- 2. Leading measure by the strongest dimension ----------------------
    used_dimensions: set[str] = set()
    for segment in context.get("segments", [])[:6]:
        dimension, measure = segment["dimension"], segment["measure"]
        if dimension in used_dimensions and len(used_dimensions) >= 3:
            continue
        used_dimensions.add(dimension)
        semantic = segment["semantic_type"]
        rows = segment["groups"]
        agg_label = segment.get("aggregation_label", "Total")
        horizontal = len(rows) > 6 or max((len(r["group"]) for r in rows), default=0) > 12
        chart = builder.add(
            chart_type=HORIZONTAL_BAR if horizontal else BAR,
            title=f"{agg_label} {measure} by {dimension}",
            question=(
                f"Which {dimension} values contribute most to {measure}?"
                if segment.get("shares_valid", True)
                else f"How does {agg_label.lower()} {measure} compare across {dimension}?"
            ),
            reason=(
                f"{dimension} has {segment['group_count']} distinct values, small enough to compare "
                f"directly and large enough for the ranking to be informative."
            ),
            columns=[measure, dimension],
            calculation=(
                f"{segment.get('aggregation', 'sum').upper()}({measure}) GROUP BY {dimension} "
                f"ORDER BY value DESC"
            ),
            data=[
                {
                    "name": row["group"],
                    "value": row["value"],
                    "share": row["share_pct"],
                    "records": row["count"],
                    "average": row["mean"],
                }
                for row in rows
            ],
            x_key="name",
            series=[{"key": "value", "label": measure}],
            insight=(
                (
                    f"{segment['best']['group']} leads with {segment['best']['share_pct']:.1f}% of "
                    f"{measure}."
                ) if segment.get("best") and segment.get("shares_valid")
                and segment["best"].get("share_pct") is not None
                else (
                    f"{segment['best']['group']} has the highest {agg_label.lower()} {measure} "
                    f"({segment['best']['formatted_value']})."
                    if segment.get("best") else ""
                )
            ),
            value_format=semantic,
            drilldown={"type": "dimension", "dimension": dimension, "measure": measure},
            priority=90 - len(builder.charts),
            signature=f"segment:{dimension}:{measure}",  # one chart per pair
        )
        if chart and len(builder.charts) >= 6:
            break

    # --- 3. Pareto / concentration ------------------------------------------
    for item in context.get("concentration", [])[:2]:
        if not item["is_risk"]:
            continue
        semantic = types.get(item["measure"], "")
        builder.add(
            chart_type=PARETO,
            title=f"Concentration of {item['measure']} by {item['dimension']}",
            question=f"How concentrated is {item['measure']} across {item['dimension']}?",
            reason=(
                f"{item['groups_for_80pct']} of {item['group_count']} {item['dimension']} values "
                f"produce 80% of {item['measure']}, which is a dependency worth showing explicitly."
            ),
            columns=[item["measure"], item["dimension"]],
            calculation=(
                f"SUM({item['measure']}) GROUP BY {item['dimension']}, sorted descending with a "
                f"running cumulative share"
            ),
            data=[
                {"name": row["group"], "value": row["value"],
                 "cumulative": row["cumulative_pct"], "share": row["share_pct"]}
                for row in item["pareto"]
            ],
            x_key="name",
            # Both series are percentages of the same total, so they share one
            # axis - a second y-scale would let the reader compare two
            # incompatible scales by eye.
            series=[
                {"key": "share", "label": f"Share of {item['measure']} %", "type": "bar"},
                {"key": "cumulative", "label": "Cumulative %", "type": "line"},
            ],
            insight=item["narrative"],
            value_format=P.PERCENTAGE,
            extra={"measure_format": semantic},
            drilldown={"type": "dimension", "dimension": item["dimension"],
                       "measure": item["measure"]},
            priority=88,
            signature=f"pareto:{item['dimension']}:{item['measure']}",
        )

    # --- 4. Composition over time (stacked) ---------------------------------
    if time_column and primary_measure and dimensions:
        dimension = _best_dimension_for_stack(df, dimensions)
        if dimension:
            stacked = _stacked_series(df, time_column, primary_measure, dimension, primary_agg)
            if stacked:
                data, keys = stacked
                builder.add(
                    chart_type=STACKED_BAR,
                    title=f"{primary_agg_label} {primary_measure} by {dimension} over time",
                    question=f"Has the mix of {dimension} in {primary_measure} shifted over time?",
                    reason=(
                        "Combining the time dimension with the strongest categorical dimension shows "
                        "whether the total is changing because of a shift in mix."
                    ),
                    columns=[primary_measure, dimension, time_column],
                    calculation=f"{primary_agg.upper()}({primary_measure}) GROUP BY period, {dimension}",
                    data=data,
                    x_key="name",
                    series=[{"key": key, "label": key} for key in keys],
                    insight=f"Each band shows one {dimension} value's contribution per period.",
                    value_format=types.get(primary_measure, ""),
                    drilldown={"type": "dimension", "dimension": dimension,
                               "measure": primary_measure},
                    priority=80,
                    signature=f"stacked:{dimension}:{primary_measure}",
                )

    # --- 5. Relationship between two measures --------------------------------
    for pair in context.get("correlations", {}).get("meaningful", [])[:2]:
        sample = _scatter_sample(df, pair["x"], pair["y"], dimensions)
        if not sample:
            continue
        builder.add(
            chart_type=SCATTER,
            title=f"{pair['y']} vs {pair['x']}",
            question=f"Do {pair['x']} and {pair['y']} move together?",
            reason=(
                f"These two measures have the strongest statistically significant correlation in "
                f"the dataset (r = {pair['pearson_r']:.2f})."
            ),
            columns=[pair["x"], pair["y"]],
            calculation=f"Record-level {pair['x']} plotted against {pair['y']} (sampled for display)",
            data=sample,
            x_key="x",
            series=[{"key": "y", "label": pair["y"]}],
            insight=pair["narrative"],
            value_format=types.get(pair["y"], ""),
            extra={"x_label": pair["x"], "y_label": pair["y"],
                   "correlation": pair["pearson_r"], "r_squared": pair["r_squared"]},
            priority=78,
            signature=f"scatter:{pair['x']}:{pair['y']}",
        )

    # --- 6. Derived metric by dimension (e.g. margin by region) --------------
    ratio_chart = _ratio_by_dimension(df, profile, measures, dimensions, builder)
    if ratio_chart:
        pass  # already appended

    # --- 7. Distribution of the most skewed measure --------------------------
    for interpretation in context.get("distributions", {}).get("interpretations", [])[:2]:
        column = interpretation["column"]
        bins = histogram(df[column])
        if not bins:
            continue
        stats = interpretation["stats"]
        builder.add(
            chart_type=HISTOGRAM,
            title=f"Distribution of {column}",
            question=f"How is {column} distributed across records?",
            reason=(
                f"The mean and median of {column} differ by {interpretation['gap_pct']:.0f}%, so the "
                f"shape of the distribution matters more than the average."
            ),
            columns=[column],
            calculation=f"Record counts of {column} across {len(bins)} equal-width bins",
            data=[{"name": b["bin"], "value": b["count"], "start": b["start"]} for b in bins],
            x_key="name",
            series=[{"key": "value", "label": "Records"}],
            insight=interpretation["narrative"],
            value_format=P.INTEGER,
            extra={
                "mean": stats["mean"], "median": stats["median"],
                "measure_format": types.get(column, ""),
            },
            priority=70,
            signature=f"hist:{column}",
        )

    # --- 8. Box plot by dimension for variability ----------------------------
    if primary_measure and dimensions:
        dimension = dimensions[0]
        boxes = _box_by_dimension(df, dimension, primary_measure, aggregation=primary_agg)
        if boxes:
            builder.add(
                chart_type=BOX,
                title=f"{primary_measure} spread by {dimension}",
                question=f"How much does {primary_measure} vary within each {dimension}?",
                reason=(
                    "Totals hide variability; the quartile spread shows whether a group is "
                    "consistently strong or driven by a few extreme records."
                ),
                columns=[primary_measure, dimension],
                calculation=f"Quartiles of {primary_measure} for each {dimension} value",
                data=boxes,
                x_key="name",
                series=[{"key": "median", "label": "Median"}],
                insight=(
                    "Wide boxes indicate inconsistent performance within that group; dots beyond the "
                    "whiskers are outliers."
                ),
                value_format=types.get(primary_measure, ""),
                priority=66,
                signature=f"box:{dimension}:{primary_measure}",
            )

    # --- 9. Heatmap: two dimensions vs one measure ---------------------------
    if primary_measure and len(dimensions) >= 2:
        heat = _heatmap(df, dimensions[0], dimensions[1], primary_measure, primary_agg)
        if heat:
            data, columns_list = heat
            builder.add(
                chart_type=HEATMAP,
                title=f"{primary_agg_label} {primary_measure} by {dimensions[0]} and {dimensions[1]}",
                question=(
                    f"Which combinations of {dimensions[0]} and {dimensions[1]} perform best?"
                ),
                reason=(
                    "A two-dimensional view surfaces pockets of strength or weakness that neither "
                    "dimension shows on its own."
                ),
                columns=[primary_measure, dimensions[0], dimensions[1]],
                calculation=(
                    f"{primary_agg.upper()}({primary_measure}) GROUP BY {dimensions[0]}, "
                    f"{dimensions[1]}"
                ),
                data=data,
                x_key="row",
                series=[{"key": column, "label": column} for column in columns_list],
                insight=f"Darker cells indicate a higher {primary_agg_label.lower()}.",
                value_format=types.get(primary_measure, ""),
                extra={"row_label": dimensions[0], "column_label": dimensions[1],
                       "column_values": columns_list},
                priority=64,
                signature=f"heat:{dimensions[0]}:{dimensions[1]}:{primary_measure}",
            )

    # --- 10. Geographic view -------------------------------------------------
    if geo_dimensions and primary_measure:
        geo = geo_dimensions[0]
        summary = _dimension_totals(
            df, geo, primary_measure, top=20,
            aggregation=primary_agg,
        )
        if summary:
            builder.add(
                chart_type=MAP,
                title=f"{primary_agg_label} {primary_measure} by {geo}",
                question=(
                    f"Where is {primary_measure} concentrated geographically?"
                    if primary_additive
                    else f"How does average {primary_measure} vary by {geo}?"
                ),
                reason=f"{geo} was detected as a geographic dimension.",
                columns=[primary_measure, geo],
                calculation=f"{primary_agg.upper()}({primary_measure}) GROUP BY {geo}",
                data=summary,
                x_key="name",
                series=[{"key": "value", "label": primary_measure}],
                insight=(
                    f"{summary[0]['name']} has the highest {primary_agg_label.lower()} "
                    f"{primary_measure}."
                ),
                value_format=types.get(primary_measure, ""),
                drilldown={"type": "dimension", "dimension": geo, "measure": primary_measure},
                priority=62,
                signature=f"geo:{geo}:{primary_measure}",
            )

    # --- 11. Correlation matrix ---------------------------------------------
    correlations = context.get("correlations", {})
    if correlations.get("available") and len(correlations.get("columns", [])) >= 3:
        builder.add(
            chart_type=CORRELATION_MATRIX,
            title="Correlation between measures",
            question="Which numeric measures are related to each other?",
            reason=(
                f"{len(correlations['columns'])} numeric measures are available, so a matrix shows "
                f"all pairwise relationships at once."
            ),
            columns=correlations["columns"],
            calculation="Pearson correlation for every pair of numeric measures",
            data=correlations["matrix"],
            x_key="column",
            series=[{"key": column, "label": column} for column in correlations["columns"]],
            insight=correlations["caveat"],
            value_format="",
            extra={"matrix_columns": correlations["columns"]},
            priority=58,
            signature="corr_matrix",
        )

    # --- 12. Composition donut ----------------------------------------------
    if primary_measure and dimensions and primary_additive:
        for dimension in dimensions:
            unique = df[dimension].nunique(dropna=True)
            if 2 <= unique <= 6:
                summary = _dimension_totals(df, dimension, primary_measure, top=6)
                if summary:
                    builder.add(
                        chart_type=DONUT,
                        title=f"Share of {primary_measure} by {dimension}",
                        question=f"How is {primary_measure} split across {dimension}?",
                        reason=(
                            f"{dimension} has only {unique} values, so a part-to-whole view is "
                            f"readable and communicates share directly."
                        ),
                        columns=[primary_measure, dimension],
                        calculation=f"SUM({primary_measure}) GROUP BY {dimension} as a share of total",
                        data=summary,
                        x_key="name",
                        series=[{"key": "value", "label": primary_measure}],
                        insight=f"{summary[0]['name']} holds {summary[0]['share']:.1f}% of the total.",
                        value_format=types.get(primary_measure, ""),
                        drilldown={"type": "dimension", "dimension": dimension,
                                   "measure": primary_measure},
                        priority=56,
                        signature=f"donut:{dimension}:{primary_measure}",
                    )
                    break

    # --- 13. Categorical record counts when there are no measures ------------
    if not measures and dimensions:
        for dimension in dimensions[:3]:
            summary = categorical_summary(df, dimension, top=12)
            if not summary:
                continue
            builder.add(
                chart_type=HORIZONTAL_BAR,
                title=f"Record count by {dimension}",
                question=f"How are records distributed across {dimension}?",
                reason="The dataset has no numeric measures, so frequency is the available signal.",
                columns=[dimension],
                calculation=f"COUNT(rows) GROUP BY {dimension}",
                data=[{"name": r["value"], "value": r["count"], "share": r["pct"]} for r in summary],
                x_key="name",
                series=[{"key": "value", "label": "Records"}],
                insight=f"{summary[0]['value']} is the most common {dimension} value.",
                value_format=P.INTEGER,
                drilldown={"type": "dimension", "dimension": dimension, "measure": None},
                priority=60,
                signature=f"count:{dimension}",
            )

    charts = sorted(builder.charts, key=lambda c: -c["priority"])[:max_charts]
    return charts


# --- helpers ----------------------------------------------------------------

def _dimension_totals(df: pd.DataFrame, dimension: str, measure: str,
                      top: int = 12, aggregation: str = "sum") -> list[dict[str, Any]]:
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame({"group": df[dimension].astype("string"), "value": values}).dropna()
    if frame.empty:
        return []
    totals = frame.groupby("group")["value"].agg(["sum", "mean", "count"])
    key = "sum" if aggregation == "sum" else "mean"
    totals = totals.sort_values(key, ascending=False)
    grand = float(totals["sum"].sum()) or 1.0
    return [
        {
            "name": str(index),
            "value": safe_float(row[key]),
            "records": int(row["count"]),
            "share": round(float(row["sum"]) / grand * 100, 2) if aggregation == "sum" else None,
        }
        for index, row in totals.head(top).iterrows()
    ]


def _best_dimension_for_stack(df: pd.DataFrame, dimensions: list[str]) -> str | None:
    for dimension in dimensions:
        unique = df[dimension].nunique(dropna=True)
        if 2 <= unique <= 6:
            return dimension
    return None


def _stacked_series(df: pd.DataFrame, time_column: str, measure: str,
                    dimension: str, aggregation: str = "sum",
                    ) -> tuple[list[dict[str, Any]], list[str]] | None:
    dates = P.to_datetime_series(df[time_column])
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame(
        {"date": dates, "value": values, "group": df[dimension].astype("string")}
    ).dropna()
    if frame.empty:
        return None
    freq, _ = choose_frequency(frame["date"])
    frame["period"] = frame["date"].dt.to_period(
        {"D": "D", "W": "W", "MS": "M", "QS": "Q", "YS": "Y"}[freq]
    ).dt.to_timestamp()
    pivot = frame.pivot_table(index="period", columns="group", values="value",
                              aggfunc=aggregation, fill_value=0)
    if pivot.empty or pivot.shape[1] > 8:
        return None
    keys = [str(column) for column in pivot.columns]
    data = []
    for period, row in pivot.iterrows():
        entry: dict[str, Any] = {"name": _label(period, freq)}
        for key, value in zip(keys, row.to_numpy()):
            entry[key] = safe_float(value)
        data.append(entry)
    return data[-36:], keys


def _scatter_sample(df: pd.DataFrame, x: str, y: str, dimensions: list[str],
                    limit: int = 800) -> list[dict[str, Any]]:
    frame = pd.DataFrame(
        {"x": P.to_numeric_series(df[x]), "y": P.to_numeric_series(df[y])}
    )
    group_column = dimensions[0] if dimensions and df[dimensions[0]].nunique(dropna=True) <= 8 else None
    if group_column:
        frame["group"] = df[group_column].astype("string")
    frame = frame.dropna(subset=["x", "y"])
    if frame.empty:
        return []
    if len(frame) > limit:
        frame = frame.sample(limit, random_state=5)
    records = []
    for row in frame.itertuples():
        entry = {"x": safe_float(row.x), "y": safe_float(row.y)}
        if group_column:
            entry["group"] = str(getattr(row, "group", ""))
        records.append(entry)
    return records


def _box_by_dimension(df: pd.DataFrame, dimension: str, measure: str,
                      top: int = 8, aggregation: str = "sum") -> list[dict[str, Any]]:
    if df[dimension].nunique(dropna=True) > 20:
        return []
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame({"group": df[dimension].astype("string"), "value": values}).dropna()
    if frame.empty:
        return []
    grouped = frame.groupby("group")["value"]
    ranking = grouped.sum() if aggregation == "sum" else grouped.mean()
    order = ranking.sort_values(ascending=False).head(top).index
    result = []
    for group in order:
        subset = frame.loc[frame["group"] == group, "value"]
        if len(subset) < 5:
            continue
        summary = box_summary(subset)
        if not summary:
            continue
        result.append({"name": str(group), **summary, "records": int(len(subset))})
    return result


def _heatmap(df: pd.DataFrame, row_dimension: str, column_dimension: str,
             measure: str, aggregation: str = "sum",
             ) -> tuple[list[dict[str, Any]], list[str]] | None:
    if df[row_dimension].nunique(dropna=True) > 15 or df[column_dimension].nunique(dropna=True) > 10:
        return None
    values = P.to_numeric_series(df[measure])
    frame = pd.DataFrame(
        {
            "row": df[row_dimension].astype("string"),
            "column": df[column_dimension].astype("string"),
            "value": values,
        }
    ).dropna()
    if frame.empty:
        return None
    pivot = frame.pivot_table(index="row", columns="column", values="value",
                              aggfunc=aggregation, fill_value=0)
    if pivot.empty:
        return None
    columns_list = [str(c) for c in pivot.columns]
    data = []
    for index, row in pivot.iterrows():
        entry: dict[str, Any] = {"row": str(index)}
        for key, value in zip(columns_list, row.to_numpy()):
            entry[key] = safe_float(value)
        data.append(entry)
    return data, columns_list


def _ratio_by_dimension(df: pd.DataFrame, profile: dict[str, Any], measures: list[str],
                        dimensions: list[str], builder: ChartBuilder) -> dict[str, Any] | None:
    """Margin-style ratio by dimension when two compatible measures exist."""
    lowered = {m.lower(): m for m in measures}
    numerator = next((lowered[k] for k in lowered if "profit" in k), None)
    denominator = next((lowered[k] for k in lowered if any(t in k for t in ("revenue", "sales", "amount"))), None)
    if not numerator or not denominator or numerator == denominator or not dimensions:
        return None
    dimension = dimensions[0]
    frame = pd.DataFrame(
        {
            "group": df[dimension].astype("string"),
            "num": P.to_numeric_series(df[numerator]),
            "den": P.to_numeric_series(df[denominator]),
        }
    ).dropna()
    if frame.empty:
        return None
    grouped = frame.groupby("group")[["num", "den"]].sum()
    grouped = grouped[grouped["den"] != 0]
    if grouped.empty:
        return None
    grouped["ratio"] = grouped["num"] / grouped["den"] * 100
    grouped = grouped.sort_values("ratio", ascending=False).head(12)
    data = [
        {"name": str(index), "value": safe_float(row["ratio"]),
         "numerator": safe_float(row["num"]), "denominator": safe_float(row["den"])}
        for index, row in grouped.iterrows()
    ]
    spread = float(grouped["ratio"].max() - grouped["ratio"].min())
    # If every group converts at the same rate the chart answers nothing.
    if spread < 2.0:
        return None
    return builder.add(
        chart_type=BAR,
        title=f"{numerator} margin by {dimension}",
        question=f"Which {dimension} values convert {denominator} into {numerator} most efficiently?",
        reason=(
            f"Both {numerator} and {denominator} exist, so a ratio is mathematically valid and "
            f"separates efficiency from raw size."
        ),
        columns=[numerator, denominator, dimension],
        calculation=f"(SUM({numerator}) ÷ SUM({denominator})) × 100 GROUP BY {dimension}",
        data=data,
        x_key="name",
        series=[{"key": "value", "label": f"{numerator} margin %"}],
        insight=(
            f"Margin ranges from {grouped['ratio'].min():.1f}% to {grouped['ratio'].max():.1f}% "
            f"across {dimension} - a spread of {spread:.1f} percentage points."
        ),
        value_format=P.PERCENTAGE,
        drilldown={"type": "dimension", "dimension": dimension, "measure": numerator},
        priority=76,
        signature=f"ratio:{dimension}:{numerator}",
    )


def attach_charts_to_insights(insights: list[dict[str, Any]],
                              charts: list[dict[str, Any]]) -> None:
    """Link every insight to the chart that best evidences it."""
    by_signature: dict[str, str] = {}
    for chart in charts:
        by_signature[f"{chart['type']}:{'|'.join(chart['columns'])}"] = chart["id"]

    for insight in insights:
        hint = insight.get("chart_hint") or {}
        kind = hint.get("kind")
        chosen: str | None = None
        for chart in charts:
            columns = set(chart["columns"])
            if kind == "trend" and chart["type"] in {LINE, AREA} and hint.get("measure") in columns:
                chosen = chart["id"]
                break
            if kind in {"segment", "segment_growth"} and chart["type"] in {BAR, HORIZONTAL_BAR} \
                    and hint.get("dimension") in columns and hint.get("measure") in columns:
                chosen = chart["id"]
                break
            if kind == "pareto" and chart["type"] == PARETO and hint.get("dimension") in columns:
                chosen = chart["id"]
                break
            if kind == "scatter" and chart["type"] == SCATTER and hint.get("x") in columns:
                chosen = chart["id"]
                break
            if kind == "histogram" and chart["type"] == HISTOGRAM and hint.get("measure") in columns:
                chosen = chart["id"]
                break
            if kind == "anomaly" and chart["type"] in {LINE, AREA, HISTOGRAM, BOX} \
                    and hint.get("measure") in columns:
                chosen = chart["id"]
                break
            if kind in {"investigation", "seasonality"} and hint.get("measure") in columns:
                chosen = chart["id"]
                break
        if not chosen:
            # fall back to any chart mentioning the insight's evidence columns
            evidence_columns = set(insight.get("evidence", {}).get("source_columns") or [])
            for chart in charts:
                if evidence_columns & set(chart["columns"]):
                    chosen = chart["id"]
                    break
        insight["chart_id"] = chosen
