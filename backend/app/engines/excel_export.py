"""Excel analysis workbook export.

Produces a multi-sheet workbook containing the analysis rather than the raw
data. Every written string is escaped so a value that starts with ``=`` cannot
execute as a formula when the file is reopened.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.engines.formatting import is_text_column
from app.engines.sanitize import escape_for_spreadsheet, neutralize_text

MAX_SHEET_NAME = 31


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = "".join(c for c in str(name) if c not in "[]:*?/\\")[:MAX_SHEET_NAME] or "Sheet"
    candidate, suffix = cleaned, 1
    while candidate.lower() in used:
        suffix += 1
        candidate = f"{cleaned[:MAX_SHEET_NAME - 3]}_{suffix}"
    used.add(candidate.lower())
    return candidate


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if is_text_column(result[column]):
            result[column] = result[column].map(
                lambda v: escape_for_spreadsheet(neutralize_text(v, 900))
                if isinstance(v, str) else v
            ).astype(object)
    result.columns = [escape_for_spreadsheet(str(c))[:120] for c in result.columns]
    return result


def build_workbook(analysis: dict[str, Any], data: pd.DataFrame | None = None,
                   config: dict[str, Any] | None = None) -> bytes:
    config = config or {}
    profile = analysis["profile"]
    buffer = io.BytesIO()
    used: set[str] = set()

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        book = writer.book
        title_format = book.add_format({"bold": True, "font_size": 14, "font_color": "#0F172A"})
        header_format = book.add_format({
            "bold": True, "bg_color": "#1E293B", "font_color": "white", "border": 1,
            "text_wrap": True, "valign": "top",
        })
        wrap_format = book.add_format({"text_wrap": True, "valign": "top"})

        def write(name: str, frame: pd.DataFrame, widths: list[int] | None = None,
                  note: str | None = None) -> None:
            if frame is None or frame.empty:
                return
            sheet_name = _safe_sheet_name(name, used)
            frame = _clean_frame(frame)
            start_row = 2 if note else 0
            frame.to_excel(writer, sheet_name=sheet_name, index=False,
                           startrow=start_row + 1, header=False)
            worksheet = writer.sheets[sheet_name]
            if note:
                worksheet.write(0, 0, escape_for_spreadsheet(name), title_format)
                worksheet.write(1, 0, escape_for_spreadsheet(note), wrap_format)
            for index, column in enumerate(frame.columns):
                worksheet.write(start_row, index, str(column), header_format)
            for index, column in enumerate(frame.columns):
                width = (widths[index] if widths and index < len(widths) else None)
                if width is None:
                    sample = frame[column].head(120).astype("string").fillna("")
                    longest = int(sample.str.len().max()) if len(sample) else 12
                    width = int(min(max(12, longest, len(str(column)) + 2), 60))
                worksheet.set_column(index, index, width, wrap_format)
            worksheet.freeze_panes(start_row + 1, 0)
            worksheet.autofilter(start_row, 0, start_row + len(frame), max(len(frame.columns) - 1, 0))

        meta = analysis.get("meta", {})
        quality = analysis.get("quality", {})
        score = analysis.get("story_score", {})
        briefing = analysis.get("briefing", {})

        # --- Executive summary ---------------------------------------------
        summary_rows = [
            ("Report generated", datetime.now(timezone.utc).strftime("%d %B %Y %H:%M UTC")),
            ("Dataset", meta.get("filename", "")),
            ("Records analysed", f"{profile['row_count']:,}"),
            ("Columns", str(profile["column_count"])),
            ("Data quality score", f"{quality.get('score', 0):.0f}/100 ({quality.get('grade', '')})"),
            ("Data story strength", f"{score.get('score', 0):.0f}/100 ({score.get('label', '')})"),
            ("Overall status", briefing.get("status", "")),
            ("Status reason", briefing.get("status_reason", "")),
            ("Dataset summary", analysis.get("summary", "")),
        ]
        story_sections = {s["key"]: s for s in analysis.get("story", {}).get("sections", [])}
        if "executive_summary" in story_sections:
            summary_rows.append(("Executive summary", story_sections["executive_summary"]["narrative"]))
        if "big_picture" in story_sections:
            summary_rows.append(("The big picture", story_sections["big_picture"]["narrative"]))
        write("Executive Summary",
              pd.DataFrame(summary_rows, columns=["Item", "Value"]), [28, 110])

        # --- KPIs -------------------------------------------------------------
        kpis = analysis.get("kpis", {}).get("all", [])
        if kpis:
            write("KPIs", pd.DataFrame([
                {
                    "KPI": k["label"], "Value": k["formatted"], "Raw value": k["value"],
                    "Aggregation": k["aggregation"], "Derived": "yes" if k["derived"] else "no",
                    "Formula": k["calculation"], "Source columns": ", ".join(k["source_columns"]),
                    "Records used": k["records_used"], "Priority score": k["priority_score"],
                    "Description": k["description"],
                }
                for k in kpis
            ]), note="Every KPI with the formula and record count behind it.")

        # --- Data story --------------------------------------------------------
        cards = analysis.get("story", {}).get("cards", [])
        if cards:
            write("Data Story", pd.DataFrame([
                {
                    "#": c.get("position"), "Section": c["section"], "Headline": c["headline"],
                    "Fact": c.get("fact", ""), "Explanation": c.get("explanation", ""),
                    "Why it matters": c.get("so_what", ""),
                    "Recommendation": c.get("recommendation", ""),
                    "Confidence": c.get("confidence", ""),
                    "Calculation": (c.get("evidence") or {}).get("calculation", ""),
                    "Records used": (c.get("evidence") or {}).get("records_used", ""),
                }
                for c in cards
            ]), [5, 20, 46, 60, 60, 50, 50, 12, 44, 14],
                note="The narrative in the order the engine determined by analytical importance.")

        # --- Insights ----------------------------------------------------------
        insights = analysis.get("insights", [])
        if insights:
            write("Key Insights", pd.DataFrame([
                {
                    "Rank": i["rank"], "Type": i["type_label"], "Headline": i["headline"],
                    "Fact": i["fact"], "Interpretation": i["interpretation"],
                    "Why it matters": i.get("so_what", ""),
                    "Recommendation": i["recommendation"], "Confidence": i["confidence"],
                    "Confidence reason": i["confidence_reason"],
                    "Priority score": i["priority"]["score"],
                    "Source columns": ", ".join(i["evidence"].get("source_columns") or []),
                    "Calculation": i["evidence"].get("calculation", ""),
                    "Records used": i["evidence"].get("records_used", 0),
                }
                for i in insights
            ]), note="Every discovered finding with its evidence, ranked by priority score.")

        # --- Data quality ------------------------------------------------------
        if quality:
            write("Data Quality", pd.DataFrame(
                [("Score", f"{quality['score']:.0f}/100"), ("Grade", quality["grade"]),
                 ("Explanation", quality["explanation"])]
                + [(f"Component: {k}", f"{v:.0f}/100") for k, v in quality.get("components", {}).items()]
                + [(f"Metric: {k}", str(v)) for k, v in quality.get("metrics", {}).items()
                   if not isinstance(v, (dict, list))],
                columns=["Item", "Value"]), [34, 110])
            issues = quality.get("issues", [])
            if issues:
                write("Quality Issues", pd.DataFrame([
                    {"Severity": i["severity"], "Column": i.get("column") or "-",
                     "Issue": i["title"], "Detail": i["detail"], "Impact": i["impact"],
                     "Affected records": i.get("affected_records", 0),
                     "Affected %": i.get("affected_pct", 0)}
                    for i in issues
                ]))

        # --- Statistics --------------------------------------------------------
        statistics = analysis.get("statistics", {}).get("columns", {})
        rows = []
        for name, stats in statistics.items():
            if not stats:
                continue
            rows.append({"Column": name, **{
                key.title(): stats.get(key)
                for key in ("count", "missing", "sum", "mean", "median", "mode", "min", "max",
                            "std", "variance", "q1", "q3", "iqr", "skewness", "kurtosis", "cv")
            }})
        if rows:
            write("Statistics", pd.DataFrame(rows),
                  note="Descriptive statistics for every numeric measure.")

        # --- Correlations ------------------------------------------------------
        correlations = analysis.get("correlations", {})
        if correlations.get("pairs"):
            write("Correlations", pd.DataFrame([
                {"Column A": p["x"], "Column B": p["y"], "Pearson r": p["pearson_r"],
                 "Spearman r": p["spearman_r"], "r squared": p["r_squared"],
                 "p value": p["pearson_p"], "Observations": p["observations"],
                 "Strength": p["strength"], "Significant": "yes" if p["significant"] else "no",
                 "Derived pair": "yes" if p["derived_pair"] else "no"}
                for p in correlations["pairs"]
            ]), note=correlations.get("caveat", ""))
            if correlations.get("matrix"):
                write("Correlation Matrix", pd.DataFrame(correlations["matrix"]))

        # --- Outliers / anomalies ----------------------------------------------
        anomalies = analysis.get("anomalies", {})
        if anomalies.get("items"):
            write("Outliers", pd.DataFrame([
                {"Finding": i["headline"], "Kind": i["kind"], "Column": i["column"],
                 "Severity": i["severity"], "Score": i["max_score"],
                 "Records affected": i.get("count", 0), "Method": i["method"],
                 "Period": i.get("period", ""), "Deviation %": i.get("deviation_pct", "")}
                for i in anomalies["items"]
            ]), note="Anomalies detected by IQR fences, modified z-scores and de-trended residuals.")

        # --- Segment analysis ---------------------------------------------------
        segment_rows = []
        for segment in analysis.get("segments", []):
            for group in segment["groups"]:
                segment_rows.append({
                    "Dimension": segment["dimension"], "Measure": segment["measure"],
                    "Aggregation": segment.get("aggregation", "sum"), "Group": group["group"],
                    "Value": group["value"], "Total": group["total"], "Average": group["mean"],
                    "Median": group["median"], "Records": group["count"],
                    "Share %": group["share_pct"], "Growth %": group["growth_pct"],
                })
        if segment_rows:
            write("Segment Analysis", pd.DataFrame(segment_rows),
                  note="Every dimension-measure comparison the engine calculated.")

        concentration = analysis.get("concentration", [])
        if concentration:
            write("Concentration", pd.DataFrame([
                {"Dimension": c["dimension"], "Measure": c["measure"], "Groups": c["group_count"],
                 "Top group": c["top_group"], "Top 1 %": c["top1_pct"], "Top 3 %": c["top3_pct"],
                 "Top 5 %": c["top5_pct"], "Groups for 80%": c["groups_for_80pct"],
                 "HHI": c["hhi"], "Concentration risk": "yes" if c["is_risk"] else "no"}
                for c in concentration
            ]))

        # --- Aggregated data and chart data ---------------------------------------
        trends = analysis.get("trends", [])
        aggregate_rows = []
        for trend in trends:
            for point in trend["points"]:
                aggregate_rows.append({
                    "Measure": trend["measure"], "Aggregation": trend.get("aggregation", "sum"),
                    "Period": point["label"], "Value": point["value"], "Records": point["records"],
                })
        if aggregate_rows:
            write("Aggregated Data", pd.DataFrame(aggregate_rows),
                  note="Time series behind the trend analysis.")

        chart_rows = []
        for chart in analysis.get("charts", []):
            for row in chart["data"][:400]:
                entry = {"Chart": chart["title"], "Type": chart["type"],
                         "Question": chart["question"]}
                entry.update({str(k): v for k, v in row.items()})
                chart_rows.append(entry)
        if chart_rows:
            write("Chart Data", pd.DataFrame(chart_rows),
                  note="The exact values plotted in each chart.")

        # --- Recommendations ------------------------------------------------------
        recommendations = analysis.get("recommendations", [])
        if recommendations:
            write("Recommendations", pd.DataFrame([
                {"Priority": r["priority"], "Action": r["action"], "Rationale": r["rationale"],
                 "Impact": r["impact"], "Confidence": r["confidence"],
                 "Source columns": ", ".join(r["source_columns"]),
                 "Evidence": r["evidence"].get("calculation", ""),
                 "Records used": r["evidence"].get("records_used", "")}
                for r in recommendations
            ]))

        # --- Column profile --------------------------------------------------------
        write("Column Profile", pd.DataFrame([
            {"Column": c["name"], "Detected type": c["semantic_type"], "Role": c["role"],
             "Aggregation": c.get("aggregation", ""), "Records": c["count"],
             "Missing": c["missing"], "Missing %": c["missing_pct"], "Distinct": c["unique"],
             "Distinct %": c["unique_pct"], "Derived from": c.get("derived_from", ""),
             "Notes": "; ".join(c.get("notes") or [])}
            for c in profile["columns"]
        ]), note="How each column was classified and why.")

        # --- Optional filtered raw data ---------------------------------------------
        if data is not None and config.get("include_data"):
            limit = int(config.get("data_row_limit", 50_000))
            write("Data", data.head(limit), note=f"First {min(limit, len(data)):,} rows analysed.")

    return buffer.getvalue()
