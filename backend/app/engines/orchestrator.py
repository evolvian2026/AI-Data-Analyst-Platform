"""Analytics orchestrator.

Runs the full pipeline in the order the product specification defines and
reports progress after each stage so the UI can show it live.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from app.core.config import settings
from app.engines import anomaly as anomaly_engine
from app.engines import cleaning as cleaning_engine
from app.engines import correlation as correlation_engine
from app.engines import derived as derived_engine
from app.engines import forecast as forecast_engine
from app.engines import insights as insight_engine
from app.engines import kpi as kpi_engine
from app.engines import narrative
from app.engines import profiler as P
from app.engines import quality as quality_engine
from app.engines import recommendations as recommendation_engine
from app.engines import segments as segment_engine
from app.engines import stats_engine
from app.engines import story as story_engine
from app.engines import trend as trend_engine
from app.engines import visualization
from app.engines.excel_parser import combinable_sheets, combine_sheets, read_workbook
from app.engines.formatting import jsonify
from app.engines.relationships import apply_join, detect_relationships

STAGES = [
    ("uploaded", "File uploaded"),
    ("workbook_read", "Workbook read"),
    ("dataset_understood", "Dataset understood"),
    ("quality_checked", "Data quality checked"),
    ("kpis_calculated", "KPIs calculated"),
    ("trends_detected", "Trends detected"),
    ("anomalies_detected", "Anomalies detected"),
    ("relationships_analyzed", "Relationships analyzed"),
    ("insights_ranked", "Insights ranked"),
    ("charts_generated", "Charts generated"),
    ("story_created", "Data Story created"),
    ("report_ready", "Report ready"),
]


@dataclass
class Progress:
    """Tracks pipeline progress; the callback persists it for polling clients."""

    callback: Callable[[dict[str, Any]], None] | None = None
    completed: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    current: str = ""

    def complete(self, key: str) -> None:
        if key not in self.completed:
            self.completed.append(key)
        index = [s[0] for s in STAGES].index(key) if key in [s[0] for s in STAGES] else -1
        self.current = STAGES[index + 1][0] if 0 <= index < len(STAGES) - 1 else ""
        self.emit()

    def emit(self) -> None:
        if self.callback:
            self.callback(self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        return {
            "stages": [
                {"key": key, "label": label, "done": key in self.completed,
                 "active": key == self.current}
                for key, label in STAGES
            ],
            "completed": len(self.completed),
            "total": len(STAGES),
            "percent": round(len(self.completed) / len(STAGES) * 100),
            "elapsed_seconds": round(time.time() - self.started_at, 2),
        }


def prepare_frame(
    frames: dict[str, pd.DataFrame],
    sheet: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Turn the sheets of a workbook into the one table that will be analysed.

    Three optional, user-controlled steps sit between the raw sheets and the
    analysis, and they live here - in one function used by both the analysis
    worker and the interactive endpoints - so that exploring rows can never
    show a different table from the one the numbers were calculated on.

    1. a cross-sheet **join**, when the user has acted on a detected relationship;
    2. otherwise, sheet selection or the union of compatible sheets;
    3. an accepted **cleaning recipe**, replayed onto a copy of the result.

    Column classification overrides are *not* applied here: they change how the
    table is interpreted, not what the table is, and belong to profiling.
    """
    config = config or {}
    context: dict[str, Any] = {
        "join": None, "cleaning": None, "attribute_columns": [], "combined_sheets": [],
    }

    join_spec = config.get("join") or None
    if join_spec:
        df, report = apply_join(
            frames, join_spec["left"], join_spec["right"], join_spec["key"],
            join_spec.get("how", "inner"), max_rows=settings.max_rows_analyzed,
        )
        context["join"] = report
        context["attribute_columns"] = report.get("duplicated_columns", [])
        context["active_sheet"] = f"{join_spec['left']} + {join_spec['right']}"
        context["scope"] = "join"
    elif sheet and sheet in frames:
        df = frames[sheet]
        context["active_sheet"] = sheet
        context["scope"] = "sheet"
    elif sheet and sheet not in frames:
        raise ValueError(
            f"Sheet '{sheet}' is not available for analysis. "
            f"Analyzable sheets: {', '.join(frames)}."
        )
    else:
        df = combine_sheets(frames)
        # Only the sheets that share a schema are stacked. Reporting "the whole
        # workbook" when one of three sheets was usable would overstate what the
        # numbers cover.
        combined = combinable_sheets(frames)
        context["active_sheet"] = "__workbook__" if len(combined) > 1 else combined[0]
        context["scope"] = "workbook" if len(combined) > 1 else "sheet"
        context["combined_sheets"] = combined

    recipe = config.get("cleaning") or []
    if recipe:
        rows_before = int(len(df))
        df, audit = cleaning_engine.apply_recipe(df, recipe)
        context["cleaning"] = cleaning_engine.summarize(audit, rows_before, int(len(df)))
    return df, context


def analyze_workbook(
    content: bytes,
    filename: str,
    sheet: str | None = None,
    progress: Progress | None = None,
    max_rows: int | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full pipeline: bytes in, complete analysis result out."""
    progress = progress or Progress()
    config = config or {}
    progress.complete("uploaded")

    frames, sheet_infos, meta = read_workbook(
        content, filename, max_rows=max_rows or settings.max_rows_analyzed
    )
    progress.complete("workbook_read")

    df, preparation = prepare_frame(frames, sheet, config)

    result = analyze_dataframe(
        df, meta, progress=progress, overrides=config.get("column_overrides"),
        attribute_columns=preparation.get("attribute_columns"),
    )
    result["meta"] = meta
    result["sheets"] = [info.to_dict() for info in sheet_infos]
    result["active_sheet"] = preparation["active_sheet"]
    result["scope"] = preparation["scope"]
    result["analyzable_sheets"] = list(frames)
    result["combined_sheets"] = preparation.get("combined_sheets") or [preparation["active_sheet"]]
    result["join"] = preparation["join"]
    result["cleaning"] = preparation["cleaning"]

    if len(frames) > 1:
        profiles = {name: P.profile_dataframe(frame, settings.sample_rows_for_profiling)
                    for name, frame in frames.items()}
        result["relationships"] = detect_relationships(frames, profiles)
    else:
        result["relationships"] = []

    progress.complete("report_ready")
    result["progress"] = progress.snapshot()
    return jsonify(result)


def analyze_dataframe(
    df: pd.DataFrame,
    meta: dict[str, Any] | None = None,
    progress: Progress | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    attribute_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Analyse a single prepared table.

    ``attribute_columns`` names columns whose values are repeated across rows -
    the lookup side of a many-to-one join. They describe an entity rather than
    an event, so they are never summed and never trended.
    """
    progress = progress or Progress()
    meta = meta or {}

    # --- understand ---------------------------------------------------------
    profile = P.profile_dataframe(df, settings.sample_rows_for_profiling)
    profile.pop("profiles", None)
    # User corrections are folded in before anything reads the profile, so every
    # downstream engine sees the corrected roles and aggregations as if they had
    # been inferred that way.
    P.apply_overrides(profile, overrides)
    attribute_columns = P.mark_attribute_columns(profile, attribute_columns)
    time_column = P.primary_time_column(profile)
    measures = profile["roles"][P.MEASURE]
    dimensions = profile["roles"][P.DIMENSION]
    identifiers = profile["roles"][P.IDENTIFIER_ROLE]
    summary = narrative.dataset_summary(profile, meta, time_column)
    derived_columns = derived_engine.detect_derived_columns(df, profile)
    derived_names = derived_engine.derived_column_names(derived_columns)
    for column in profile["columns"]:
        if column["name"] in derived_names:
            column["derived_from"] = next(
                d["formula"] for d in derived_columns if d["column"] == column["name"]
            )
    profile["derived_columns"] = derived_columns
    progress.complete("dataset_understood")

    # --- quality ------------------------------------------------------------
    outliers = quality_engine.outlier_scan(df, profile)
    quality = quality_engine.assess_quality(
        df, profile, outliers, injection_findings=meta.get("injection_findings"),
    )
    progress.complete("quality_checked")

    # --- KPIs ---------------------------------------------------------------
    kpis = kpi_engine.build_kpis(df, profile, time_column, settings.max_primary_kpis)
    progress.complete("kpis_calculated")

    # --- trends -------------------------------------------------------------
    ranked_measures = _rank_measures(measures, kpis)
    # A time series of a repeated attribute tracks which entities appear in each
    # period, not any change in the attribute, so those columns never enter it.
    trendable = [m for m in ranked_measures if m not in attribute_columns]
    trends = trend_engine.analyze_trends(df, profile, time_column, trendable)
    # A projection is derived from the measured series and kept beside it, never
    # inside it: nothing that sums or averages ``trends`` can pick up a forecast.
    forecasts = forecast_engine.forecast_trends(trends, profile)
    progress.complete("trends_detected")

    # --- anomalies ----------------------------------------------------------
    record_anomalies = anomaly_engine.detect_record_outliers(df, profile)
    timeseries_anomalies = anomaly_engine.detect_timeseries_anomalies(
        df, profile, time_column, trendable
    )
    anomalies = anomaly_engine.summarize_anomalies(
        record_anomalies, timeseries_anomalies, profile["row_count"]
    )
    # Investigating a single stray record produces a "driver" that is really one
    # row, so only anomalies with a meaningful number of records are decomposed.
    investigable = [
        item for item in anomalies["items"]
        if item["kind"] == "timeseries" or item.get("count", 0) >= 5
    ][:3]
    investigations = [
        anomaly_engine.investigate_anomaly(df, profile, item, time_column)
        for item in investigable
    ]
    investigations = [
        i for i in investigations if i.get("available") and i.get("records_examined", 0) >= 5
    ]
    progress.complete("anomalies_detected")

    # --- relationships between measures and segments ------------------------
    correlations = correlation_engine.analyze_correlations(df, profile, derived=derived_columns)
    segments = segment_engine.analyze_segments(
        df, profile, dimensions, ranked_measures, time_column
    )
    concentration = segment_engine.analyze_concentration(
        df, profile, dimensions, ranked_measures, identifiers
    )
    distributions = stats_engine.analyze_distributions(df, profile)
    progress.complete("relationships_analyzed")

    context: dict[str, Any] = {
        "profile": profile,
        "derived_columns": derived_columns,
        "meta": meta,
        "summary": summary,
        "time_column": time_column,
        "quality": quality,
        "kpis": kpis,
        "trends": trends,
        "forecasts": forecasts,
        "anomalies": anomalies,
        "investigations": investigations,
        "correlations": correlations,
        "segments": segments,
        "concentration": concentration,
        "distributions": distributions,
    }

    # --- insights -----------------------------------------------------------
    discovered = insight_engine.discover_insights(context)
    context["insights"] = discovered
    progress.complete("insights_ranked")

    # --- charts -------------------------------------------------------------
    charts = visualization.build_charts(df, context, settings.max_charts)
    visualization.attach_projections(charts, forecasts)
    visualization.attach_charts_to_insights(discovered, charts)
    context["charts"] = charts
    progress.complete("charts_generated")

    # --- recommendations, story, briefing ------------------------------------
    recommendations = recommendation_engine.build_recommendations(discovered, quality)
    context["recommendations"] = recommendations
    story = story_engine.build_story(context)
    briefing = recommendation_engine.build_briefing(context)
    score = insight_engine.story_score(discovered, quality, context)
    progress.complete("story_created")

    filters = _build_filters(df, profile)
    statistics = {
        "columns": {
            column["name"]: stats_engine.describe_numeric(df[column["name"]])
            for column in profile["columns"]
            if column["role"] == P.MEASURE
        },
        "categorical": {
            column["name"]: stats_engine.categorical_summary(df, column["name"])
            for column in profile["columns"]
            if column["role"] == P.DIMENSION and column["unique"] <= 200
        },
    }

    return {
        "summary": summary,
        "profile": profile,
        "derived_columns": derived_columns,
        "ranked_measures": ranked_measures,
        "time_column": time_column,
        "quality": quality,
        "kpis": kpis,
        "statistics": statistics,
        "distributions": distributions,
        "trends": trends,
        "forecasts": forecasts,
        "anomalies": anomalies,
        "investigations": investigations,
        "correlations": correlations,
        "segments": segments,
        "concentration": concentration,
        "insights": discovered,
        "top_insights": discovered[:5],
        "charts": charts,
        "recommendations": recommendations,
        "story": story,
        "briefing": briefing,
        "story_score": score,
        "filters": filters,
        "next_questions": story_engine.next_questions(context),
        "audiences": narrative.AUDIENCES,
        "column_options": [
            P.override_options(column, df[column["name"]] if column["name"] in df else None)
            for column in profile["columns"]
        ],
        "cleaning_proposals": cleaning_engine.propose_fixes(df, profile, quality),
    }


def _rank_measures(measures: list[str], kpis: dict[str, Any]) -> list[str]:
    """Order measures by the KPI engine's relevance so the important ones lead."""
    scores: dict[str, float] = {}
    for kpi in kpis["all"]:
        for column in kpi["source_columns"]:
            scores[column] = max(scores.get(column, 0.0), kpi["priority_score"])
    return sorted(measures, key=lambda m: -scores.get(m, 0.0))


def _build_filters(df: pd.DataFrame, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Filters generated from whichever dimensions the dataset actually has."""
    filters: list[dict[str, Any]] = []
    for column in profile["columns"]:
        name = column["name"]
        if column["role"] == P.TIME_DIMENSION and column["semantic_type"] != P.TIME:
            stats = column.get("temporal_stats") or {}
            if stats.get("min") and stats.get("max"):
                filters.append(
                    {
                        "column": name, "type": "date_range",
                        "min": stats["min"], "max": stats["max"], "label": name,
                    }
                )
        elif column["role"] == P.DIMENSION and 1 < column["unique"] <= 200:
            values = df[name].dropna().astype(str).value_counts().head(200)
            filters.append(
                {
                    "column": name, "type": "multi_select", "label": name,
                    "options": [{"value": str(index), "count": int(value)}
                                for index, value in values.items()],
                }
            )
        elif column["role"] == P.MEASURE and column.get("numeric_stats"):
            stats = column["numeric_stats"]
            if stats.get("min") is not None and stats["min"] != stats.get("max"):
                filters.append(
                    {
                        "column": name, "type": "numeric_range", "label": name,
                        "min": stats["min"], "max": stats["max"],
                    }
                )
    return filters


def apply_filters(df: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
    """Apply validated filter descriptors to a dataframe.

    Filters are structured descriptors, never expressions - user input is never
    evaluated as code.
    """
    if not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for item in filters:
        column = item.get("column")
        if not column or column not in df.columns:
            continue
        kind = item.get("type")
        if kind == "multi_select":
            values = [str(v) for v in (item.get("values") or [])]
            if values:
                mask &= df[column].astype(str).isin(values)
        elif kind == "date_range":
            dates = P.to_datetime_series(df[column])
            if item.get("from"):
                mask &= dates >= pd.Timestamp(item["from"])
            if item.get("to"):
                mask &= dates <= pd.Timestamp(item["to"])
        elif kind == "numeric_range":
            numeric = P.to_numeric_series(df[column])
            if item.get("min") is not None:
                mask &= numeric >= float(item["min"])
            if item.get("max") is not None:
                mask &= numeric <= float(item["max"])
    return df.loc[mask.fillna(False)]
