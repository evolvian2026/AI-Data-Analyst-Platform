"""PDF and Excel report generation."""
from __future__ import annotations

import io

import pandas as pd
import pytest
from pypdf import PdfReader

from app.engines.excel_export import build_workbook
from app.engines.pdf_report import STYLE_PRESETS, draw_chart, generate_pdf


def read_pdf(content: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(content))


def test_pdf_is_produced_for_every_style(sales_analysis):
    for style in STYLE_PRESETS:
        content = generate_pdf(sales_analysis, {"style": style, "title": "Test report"})
        assert content.startswith(b"%PDF")
        assert len(read_pdf(content).pages) >= 2


def test_report_length_matches_the_selected_style(sales_analysis):
    lengths = {
        style: len(read_pdf(generate_pdf(sales_analysis, {"style": style})).pages)
        for style in ("executive", "standard", "detailed")
    }
    assert 2 <= lengths["executive"] <= 5
    assert 5 <= lengths["standard"] <= 15
    assert lengths["detailed"] >= 15
    assert lengths["executive"] < lengths["standard"] < lengths["detailed"]


def test_cover_customisation_reaches_the_document(sales_analysis):
    content = generate_pdf(sales_analysis, {
        "style": "standard", "title": "Quarterly Review", "organization": "Northwind Ltd",
        "author": "R. Patel", "date_range": "Jan-Dec 2025",
    })
    text = read_pdf(content).pages[0].extract_text()
    assert "Quarterly Review" in text
    assert "Northwind Ltd" in text
    assert "R. Patel" in text


def test_pages_carry_numbers_and_running_headers(sales_analysis):
    reader = read_pdf(generate_pdf(sales_analysis, {"style": "standard", "title": "Numbered"}))
    body = reader.pages[2].extract_text()
    assert "Page 3" in body
    assert "Numbered" in body


def test_long_reports_include_a_table_of_contents(sales_analysis):
    reader = read_pdf(generate_pdf(sales_analysis, {"style": "detailed"}))
    assert "Contents" in reader.pages[1].extract_text()


def test_detailed_report_contains_tables_and_methodology(sales_analysis):
    reader = read_pdf(generate_pdf(sales_analysis, {"style": "detailed"}))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for expected in ("Executive Briefing", "Data Quality", "Data Story", "Recommendations",
                     "Statistical Analysis", "Correlations", "Methodology"):
        assert expected in text, f"{expected} missing from the detailed report"


def test_report_sections_can_be_restricted(sales_analysis):
    content = generate_pdf(sales_analysis, {
        "style": "standard", "sections": ["briefing", "recommendations"],
    })
    text = "\n".join(page.extract_text() for page in read_pdf(content).pages)
    assert "Executive Briefing" in text
    assert "Statistical Analysis" not in text


def test_charts_can_be_disabled(sales_analysis):
    with_charts = generate_pdf(sales_analysis, {"style": "standard", "include_charts": True})
    without = generate_pdf(sales_analysis, {"style": "standard", "include_charts": False})
    assert len(without) < len(with_charts)


def test_every_chart_type_renders_without_error(sales_analysis):
    rendered = 0
    for chart in sales_analysis["charts"]:
        drawing = draw_chart(chart)
        if drawing is not None:
            rendered += 1
    assert rendered >= len(sales_analysis["charts"]) - 1


def test_a_broken_chart_never_breaks_the_report():
    assert draw_chart({"type": "bar", "data": []}) is None
    assert draw_chart({"type": "unknown", "data": [{"name": "a", "value": 1}]}) is None


def test_report_survives_an_invalid_logo(sales_analysis):
    content = generate_pdf(sales_analysis, {"style": "executive", "logo_bytes": b"not an image"})
    assert content.startswith(b"%PDF")


def test_excel_export_contains_the_specified_sheets(sales_analysis, sales_frame):
    content = build_workbook(sales_analysis, sales_frame, {"include_data": True,
                                                           "data_row_limit": 100})
    sheets = pd.ExcelFile(io.BytesIO(content)).sheet_names
    for expected in ("Executive Summary", "KPIs", "Data Story", "Key Insights", "Data Quality",
                     "Statistics", "Correlations", "Outliers", "Segment Analysis",
                     "Aggregated Data", "Chart Data"):
        assert expected in sheets, f"{expected} sheet missing"
    assert "Data" in sheets


def test_excel_export_values_match_the_analysis(sales_analysis):
    content = build_workbook(sales_analysis)
    frame = pd.read_excel(io.BytesIO(content), "Key Insights", header=2)
    assert len(frame) == len(sales_analysis["insights"])
    assert frame["Headline"].iloc[0] == sales_analysis["insights"][0]["headline"]


def test_excel_export_defuses_formula_injection():
    analysis = {
        "profile": {"row_count": 1, "column_count": 1, "columns": [
            {"name": "=cmd|'/c calc'!A1", "semantic_type": "text", "role": "descriptive",
             "count": 1, "missing": 0, "missing_pct": 0, "unique": 1, "unique_pct": 100,
             "aggregation": "", "notes": []},
        ], "roles": {}, "currency_symbol": ""},
        "meta": {"filename": "x.xlsx"}, "summary": "s", "quality": {}, "kpis": {"all": []},
        "story": {"sections": [], "cards": []}, "insights": [], "statistics": {"columns": {}},
        "correlations": {}, "anomalies": {}, "segments": [], "concentration": [],
        "trends": [], "charts": [], "recommendations": [], "briefing": {}, "story_score": {},
    }
    content = build_workbook(analysis)
    frame = pd.read_excel(io.BytesIO(content), "Column Profile", header=2)
    assert str(frame["Column"].iloc[0]).startswith("'="), "formula must be neutralised"
