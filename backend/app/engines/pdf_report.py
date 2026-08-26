"""Professional PDF report generation (ReportLab).

Three report styles - executive (2-5 pages), standard (5-15) and detailed
(15+) - and the length adapts to what was actually discovered rather than
padding to a fixed page count. Charts are drawn natively so the PDF has no
dependency on the browser.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.doughnut import Doughnut
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.engines.formatting import format_value
from app.engines.sanitize import neutralize_text

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
ACCENT = colors.HexColor("#2563EB")
LINE = colors.HexColor("#E2E8F0")
SURFACE = colors.HexColor("#F8FAFC")
POSITIVE = colors.HexColor("#059669")
NEGATIVE = colors.HexColor("#DC2626")
WARNING = colors.HexColor("#D97706")

SERIES_COLORS = [
    colors.HexColor("#2563EB"), colors.HexColor("#0D9488"), colors.HexColor("#D97706"),
    colors.HexColor("#7C3AED"), colors.HexColor("#DB2777"), colors.HexColor("#059669"),
    colors.HexColor("#DC2626"), colors.HexColor("#0891B2"),
]

STYLE_PRESETS = {
    "executive": {
        "label": "Executive", "pages": "2-5 pages", "max_pages": 5,
        "sections": ["cover", "briefing", "executive_summary", "kpis", "story", "recommendations"],
        "max_story_cards": 4, "max_charts": 2, "max_insights": 5, "max_recommendations": 4,
        "group_limit": 2,
    },
    "standard": {
        "label": "Standard", "pages": "5-15 pages", "max_pages": 15,
        "sections": ["cover", "toc", "briefing", "executive_summary", "kpis", "quality", "story",
                     "trends", "winners", "anomalies", "risks", "opportunities",
                     "recommendations", "charts"],
        "max_story_cards": 8, "max_charts": 6, "max_insights": 12, "max_recommendations": 6,
        "group_limit": 3,
    },
    "detailed": {
        "label": "Detailed", "pages": "15+ pages", "max_pages": None,
        "sections": ["cover", "toc", "briefing", "executive_summary", "kpis", "quality", "story",
                     "trends", "drivers", "winners", "underperformers", "anomalies",
                     "relationships", "risks", "opportunities", "recommendations", "charts",
                     "analytics", "statistics", "correlations", "appendix"],
        "max_story_cards": 24, "max_charts": 14, "max_insights": 40, "max_recommendations": 12,
        "group_limit": 5,
    },
}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=30, leading=35, textColor=INK, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=13, leading=18,
                                   textColor=MUTED, alignment=TA_LEFT),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                             fontSize=17, leading=21, textColor=INK, spaceBefore=14, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12.5, leading=16, textColor=INK, spaceBefore=10, spaceAfter=5),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold",
                             fontSize=10.5, leading=14, textColor=ACCENT, spaceBefore=7, spaceAfter=3),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.6, leading=14.2,
                               textColor=INK, alignment=TA_JUSTIFY, spaceAfter=5),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8.2, leading=11.5,
                                textColor=MUTED, spaceAfter=3),
        "kpi_label": ParagraphStyle("kpi_label", parent=base["Normal"], fontSize=7.6, leading=9.5,
                                    textColor=MUTED, alignment=TA_CENTER),
        "kpi_value": ParagraphStyle("kpi_value", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=14, leading=17, textColor=INK, alignment=TA_CENTER),
        "toc": ParagraphStyle("toc", parent=base["Normal"], fontSize=10, leading=17, textColor=INK),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.2, leading=10.8,
                               textColor=INK),
        "cell_head": ParagraphStyle("cell_head", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=8.2, leading=10.8, textColor=colors.white),
    }


def _text(value: Any, limit: int = 4000) -> str:
    cleaned = neutralize_text(value, limit)
    return cleaned.replace("&", "&amp;").replace("‹", "&lt;").replace("›", "&gt;")


class ReportDocument(BaseDocTemplate):
    """Adds running headers, footers and page numbers to every non-cover page."""

    def __init__(self, buffer: io.BytesIO, config: dict[str, Any]) -> None:
        super().__init__(
            buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN + 8 * mm, bottomMargin=MARGIN,
            title=config.get("title", "Analytics Report"),
            author=config.get("author", "AI Data Analyst"),
            subject="Automated analytics report",
        )
        self.config = config
        frame = Frame(MARGIN, MARGIN, CONTENT_WIDTH,
                      PAGE_HEIGHT - MARGIN - (MARGIN + 8 * mm), id="body")
        cover_frame = Frame(MARGIN, MARGIN, CONTENT_WIDTH, PAGE_HEIGHT - 2 * MARGIN, id="cover")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=self._cover_page),
            PageTemplate(id="body", frames=[frame], onPage=self._body_page),
        ])

    def _cover_page(self, canvas, document) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#0B1220"))
        canvas.rect(0, PAGE_HEIGHT - 92 * mm, PAGE_WIDTH, 92 * mm, stroke=0, fill=1)
        canvas.setFillColor(ACCENT)
        canvas.rect(0, PAGE_HEIGHT - 92 * mm, PAGE_WIDTH, 2.2 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def _body_page(self, canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        header_y = PAGE_HEIGHT - MARGIN - 2 * mm
        canvas.line(MARGIN, header_y, PAGE_WIDTH - MARGIN, header_y)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, header_y + 2.6 * mm, _text(self.config.get("title", ""), 90))
        canvas.drawRightString(
            PAGE_WIDTH - MARGIN, header_y + 2.6 * mm,
            _text(self.config.get("organization") or self.config.get("dataset_name", ""), 60),
        )
        canvas.line(MARGIN, MARGIN - 2 * mm, PAGE_WIDTH - MARGIN, MARGIN - 2 * mm)
        canvas.drawString(MARGIN, MARGIN - 6.5 * mm,
                          f"Generated {self.config.get('generated_at', '')}")
        canvas.drawRightString(PAGE_WIDTH - MARGIN, MARGIN - 6.5 * mm, f"Page {canvas.getPageNumber()}")
        canvas.drawCentredString(
            PAGE_WIDTH / 2, MARGIN - 6.5 * mm,
            "Figures calculated by the analytics engine",
        )
        canvas.restoreState()


# --- chart rendering --------------------------------------------------------

def _short(value: Any, limit: int = 14) -> str:
    text = neutralize_text(value, limit + 4)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _axis_number(value: float) -> str:
    magnitude = abs(value)
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if magnitude >= threshold:
            return f"{value / threshold:,.1f}{suffix}"
    if magnitude >= 10:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def draw_chart(chart: dict[str, Any], width: float = CONTENT_WIDTH,
               height: float = 62 * mm) -> Drawing | None:
    """Render a chart descriptor into a ReportLab drawing."""
    kind = chart.get("type")
    data = chart.get("data") or []
    if not data:
        return None
    try:
        if kind in {"line", "area"}:
            return _line_chart(chart, width, height)
        if kind == "pareto":
            return _pareto_chart(chart, width, height)
        if kind in {"bar", "histogram"}:
            return _bar_chart(chart, width, height)
        if kind == "horizontal_bar":
            return _horizontal_bar_chart(chart, width, height)
        if kind in {"donut", "pie"}:
            return _donut_chart(chart, width, height)
        if kind == "stacked_bar":
            return _stacked_chart(chart, width, height)
        if kind == "scatter":
            return _scatter_chart(chart, width, height)
        if kind == "correlation_matrix":
            return _matrix_chart(chart, width, height)
        if kind in {"heatmap"}:
            return _heatmap_chart(chart, width, height)
        if kind in {"box", "geographic"}:
            return _bar_chart({**chart, "type": "bar"}, width, height)
    except Exception:  # noqa: BLE001 - a chart must never break a report
        return None
    return None


def _numeric(values: list[Any]) -> list[float]:
    return [float(v) if isinstance(v, (int, float)) else 0.0 for v in values]


def _line_chart(chart, width, height) -> Drawing:
    drawing = Drawing(width, height)
    data = chart["data"]
    values = _numeric([row.get("value") for row in data])
    graph = HorizontalLineChart()
    graph.x, graph.y = 34, 24
    graph.width, graph.height = width - 50, height - 40
    graph.data = [values]
    graph.lines[0].strokeColor = SERIES_COLORS[0]
    graph.lines[0].strokeWidth = 1.7
    graph.lines[0].symbol = None
    step = max(1, len(data) // 9)
    graph.categoryAxis.categoryNames = [
        _short(row.get("name"), 10) if index % step == 0 else ""
        for index, row in enumerate(data)
    ]
    graph.categoryAxis.labels.fontSize = 6.4
    graph.categoryAxis.labels.angle = 30
    graph.categoryAxis.labels.dy = -6
    graph.categoryAxis.labels.boxAnchor = "ne"
    graph.valueAxis.labelTextFormat = _axis_number
    graph.valueAxis.labels.fontSize = 6.6
    graph.valueAxis.valueMin = min(0.0, min(values)) if values else 0
    drawing.add(graph)
    return drawing


def _bar_chart(chart, width, height) -> Drawing:
    drawing = Drawing(width, height)
    data = chart["data"][:14]
    values = _numeric([row.get("value") for row in data])
    graph = VerticalBarChart()
    graph.x, graph.y = 34, 26
    graph.width, graph.height = width - 50, height - 42
    graph.data = [values]
    graph.bars[0].fillColor = SERIES_COLORS[0]
    graph.bars[0].strokeColor = None
    graph.barSpacing = 1.5
    graph.groupSpacing = 6
    graph.categoryAxis.categoryNames = [_short(row.get("name"), 12) for row in data]
    graph.categoryAxis.labels.fontSize = 6.4
    graph.categoryAxis.labels.angle = 25
    graph.categoryAxis.labels.dy = -6
    graph.categoryAxis.labels.boxAnchor = "ne"
    graph.valueAxis.labelTextFormat = _axis_number
    graph.valueAxis.labels.fontSize = 6.6
    graph.valueAxis.valueMin = min(0.0, min(values)) if values else 0
    drawing.add(graph)
    return drawing


def _pareto_chart(chart, width, height) -> Drawing:
    """Share and cumulative share on a single percentage axis."""
    drawing = Drawing(width, height)
    data = chart["data"][:12]
    shares = _numeric([row.get("share") for row in data])
    cumulative = _numeric([row.get("cumulative") for row in data])
    graph = VerticalBarChart()
    graph.x, graph.y = 34, 30
    graph.width, graph.height = width - 50, height - 48
    graph.data = [shares]
    graph.bars[0].fillColor = SERIES_COLORS[0]
    graph.bars[0].strokeColor = None
    graph.categoryAxis.categoryNames = [_short(row.get("name"), 12) for row in data]
    graph.categoryAxis.labels.fontSize = 6.4
    graph.categoryAxis.labels.angle = 25
    graph.categoryAxis.labels.dy = -6
    graph.categoryAxis.labels.boxAnchor = "ne"
    graph.valueAxis.valueMin = 0
    graph.valueAxis.valueMax = 100
    graph.valueAxis.labelTextFormat = lambda v: f"{v:.0f}%"
    graph.valueAxis.labels.fontSize = 6.6
    drawing.add(graph)

    line = HorizontalLineChart()
    line.x, line.y = graph.x, graph.y
    line.width, line.height = graph.width, graph.height
    line.data = [cumulative]
    line.lines[0].strokeColor = SERIES_COLORS[1]
    line.lines[0].strokeWidth = 2
    line.categoryAxis.visible = 0
    line.valueAxis.visible = 0
    line.valueAxis.valueMin = 0
    line.valueAxis.valueMax = 100
    drawing.add(line)

    legend = Legend()
    legend.x, legend.y = 34, height - 4
    legend.fontSize = 6.6
    legend.columnMaximum = 1
    legend.deltax = 96
    legend.dxTextSpace = 3
    legend.boxAnchor = "nw"
    legend.colorNamePairs = [
        (SERIES_COLORS[0], "Share %"), (SERIES_COLORS[1], "Cumulative %"),
    ]
    drawing.add(legend)
    return drawing


def _horizontal_bar_chart(chart, width, height) -> Drawing:
    data = chart["data"][:12]
    height = max(height, 10 * len(data) + 26)
    drawing = Drawing(width, height)
    values = _numeric([row.get("value") for row in data])
    graph = HorizontalBarChart()
    graph.x, graph.y = 92, 18
    graph.width, graph.height = width - 108, height - 30
    graph.data = [list(reversed(values))]
    graph.bars[0].fillColor = SERIES_COLORS[0]
    graph.bars[0].strokeColor = None
    graph.categoryAxis.categoryNames = [_short(row.get("name"), 20) for row in reversed(data)]
    graph.categoryAxis.labels.fontSize = 6.6
    graph.valueAxis.labelTextFormat = _axis_number
    graph.valueAxis.labels.fontSize = 6.6
    graph.valueAxis.valueMin = min(0.0, min(values)) if values else 0
    drawing.add(graph)
    return drawing


def _donut_chart(chart, width, height) -> Drawing:
    drawing = Drawing(width, height)
    data = chart["data"][:8]
    values = [abs(float(row.get("value") or 0)) for row in data]
    if sum(values) <= 0:
        return drawing
    pie = Doughnut()
    pie.x, pie.y = 18, 8
    pie.width = pie.height = height - 16
    pie.data = values
    pie.labels = [_short(row.get("name"), 12) for row in data]
    pie.innerRadiusFraction = 0.55
    for index in range(len(values)):
        pie.slices[index].fillColor = SERIES_COLORS[index % len(SERIES_COLORS)]
        pie.slices[index].strokeColor = colors.white
        pie.slices[index].strokeWidth = 0.8
    drawing.add(pie)
    legend = Legend()
    legend.x, legend.y = height + 16, height - 16
    legend.fontSize = 6.8
    legend.dxTextSpace = 4
    legend.deltay = 9
    legend.columnMaximum = 8
    legend.colorNamePairs = [
        (SERIES_COLORS[index % len(SERIES_COLORS)],
         f"{_short(row.get('name'), 16)} ({row.get('share') or 0:.0f}%)")
        for index, row in enumerate(data)
    ]
    drawing.add(legend)
    return drawing


def _stacked_chart(chart, width, height) -> Drawing:
    drawing = Drawing(width, height)
    data = chart["data"][-18:]
    keys = [s["key"] for s in chart.get("series", [])][:6]
    if not keys:
        return drawing
    graph = VerticalBarChart()
    graph.x, graph.y = 34, 30
    graph.width, graph.height = width - 50, height - 48
    graph.categoryAxis.style = "stacked"
    graph.data = [_numeric([row.get(key) for row in data]) for key in keys]
    for index in range(len(keys)):
        graph.bars[index].fillColor = SERIES_COLORS[index % len(SERIES_COLORS)]
        graph.bars[index].strokeColor = None
    step = max(1, len(data) // 8)
    graph.categoryAxis.categoryNames = [
        _short(row.get("name"), 9) if index % step == 0 else ""
        for index, row in enumerate(data)
    ]
    graph.categoryAxis.labels.fontSize = 6.2
    graph.categoryAxis.labels.angle = 25
    graph.categoryAxis.labels.dy = -6
    graph.categoryAxis.labels.boxAnchor = "ne"
    graph.valueAxis.labelTextFormat = _axis_number
    graph.valueAxis.labels.fontSize = 6.6
    drawing.add(graph)
    legend = Legend()
    legend.x, legend.y = 34, height - 4
    legend.fontSize = 6.6
    legend.alignment = "right"
    legend.columnMaximum = 1
    legend.deltax = 68
    legend.dxTextSpace = 3
    legend.boxAnchor = "nw"
    legend.colorNamePairs = [
        (SERIES_COLORS[index % len(SERIES_COLORS)], _short(key, 14))
        for index, key in enumerate(keys)
    ]
    drawing.add(legend)
    return drawing


def _scatter_chart(chart, width, height) -> Drawing:
    drawing = Drawing(width, height)
    data = chart["data"][:400]
    xs = [float(row.get("x") or 0) for row in data]
    ys = [float(row.get("y") or 0) for row in data]
    if not xs or not ys:
        return drawing
    left, bottom = 38.0, 26.0
    plot_width, plot_height = width - left - 12, height - bottom - 14
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = (x_max - x_min) or 1
    y_range = (y_max - y_min) or 1
    drawing.add(Rect(left, bottom, plot_width, plot_height, fillColor=SURFACE,
                     strokeColor=LINE, strokeWidth=0.5))
    for x, y in zip(xs, ys):
        cx = left + (x - x_min) / x_range * plot_width
        cy = bottom + (y - y_min) / y_range * plot_height
        drawing.add(Rect(cx - 0.9, cy - 0.9, 1.8, 1.8, fillColor=SERIES_COLORS[0],
                         strokeColor=None))
    drawing.add(String(left, bottom - 10, _axis_number(x_min), fontSize=6.4, fillColor=MUTED))
    drawing.add(String(left + plot_width - 24, bottom - 10, _axis_number(x_max),
                       fontSize=6.4, fillColor=MUTED))
    drawing.add(String(4, bottom + plot_height - 6, _axis_number(y_max), fontSize=6.4,
                       fillColor=MUTED))
    drawing.add(String(4, bottom, _axis_number(y_min), fontSize=6.4, fillColor=MUTED))
    drawing.add(String(left + plot_width / 2 - 20, bottom - 19,
                       _short(chart.get("x_label", "x"), 24), fontSize=6.8, fillColor=MUTED))
    return drawing


def _matrix_chart(chart, width, height) -> Drawing:
    columns = chart.get("matrix_columns") or []
    rows = chart.get("data") or []
    if not columns or not rows:
        return Drawing(width, height)
    size = min(width / (len(columns) + 2.6), 15.0)
    height = size * len(rows) + 34
    drawing = Drawing(width, height)
    left = min(96.0, width * 0.28)
    for r_index, row in enumerate(rows):
        y = height - 26 - (r_index + 1) * size
        drawing.add(String(4, y + size / 3, _short(row.get("column"), 16), fontSize=6,
                           fillColor=INK))
        for c_index, column in enumerate(columns):
            value = row.get(column)
            x = left + c_index * size
            if value is None:
                fill = colors.HexColor("#F1F5F9")
            else:
                intensity = min(abs(float(value)), 1.0)
                fill = colors.linearlyInterpolatedColor(
                    colors.white, ACCENT if float(value) >= 0 else NEGATIVE, 0, 1, intensity
                )
            drawing.add(Rect(x, y, size - 1, size - 1, fillColor=fill, strokeColor=colors.white,
                             strokeWidth=0.4))
            if value is not None and size >= 12:
                drawing.add(String(x + 1, y + size / 3, f"{float(value):.2f}", fontSize=4.6,
                                   fillColor=INK))
    for c_index, column in enumerate(columns):
        drawing.add(String(left + c_index * size, height - 20, _short(column, 9), fontSize=5.4,
                           fillColor=MUTED, angle=45))
    return drawing


def _heatmap_chart(chart, width, height) -> Drawing:
    columns = chart.get("column_values") or []
    rows = chart.get("data") or []
    if not columns or not rows:
        return Drawing(width, height)
    cell_height = 14.0
    cell_width = min((width - 110) / max(len(columns), 1), 60.0)
    height = cell_height * len(rows) + 32
    drawing = Drawing(width, height)
    values = [float(row.get(c) or 0) for row in rows for c in columns]
    maximum = max(values) if values else 1
    minimum = min(values) if values else 0
    span = (maximum - minimum) or 1
    for r_index, row in enumerate(rows):
        y = height - 24 - (r_index + 1) * cell_height
        drawing.add(String(4, y + 4, _short(row.get("row"), 16), fontSize=6.2, fillColor=INK))
        for c_index, column in enumerate(columns):
            value = float(row.get(column) or 0)
            fill = colors.linearlyInterpolatedColor(
                colors.HexColor("#EFF6FF"), ACCENT, 0, 1, (value - minimum) / span
            )
            drawing.add(Rect(100 + c_index * cell_width, y, cell_width - 1, cell_height - 1,
                             fillColor=fill, strokeColor=colors.white, strokeWidth=0.4))
    for c_index, column in enumerate(columns):
        drawing.add(String(100 + c_index * cell_width, height - 18, _short(column, 10),
                           fontSize=5.6, fillColor=MUTED, angle=30))
    return drawing


# --- building blocks --------------------------------------------------------

def _table(rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle],
           align_right: set[int] | None = None) -> Table:
    align_right = align_right or set()
    body = [
        [Paragraph(_text(cell, 400), styles["cell_head"] if index == 0 else styles["cell"])
         for cell in row]
        for index, row in enumerate(rows)
    ]
    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for column in align_right:
        style.append(("ALIGN", (column, 1), (column, -1), "RIGHT"))
    table.setStyle(TableStyle(style))
    return table


def _kpi_grid(kpis: list[dict[str, Any]], styles: dict[str, ParagraphStyle],
              per_row: int = 4) -> list[Any]:
    flowables: list[Any] = []
    for start in range(0, len(kpis), per_row):
        chunk = kpis[start:start + per_row]
        labels = [Paragraph(_text(k["label"], 60), styles["kpi_label"]) for k in chunk]
        values = [Paragraph(_text(k["formatted"], 30), styles["kpi_value"]) for k in chunk]
        notes = [
            Paragraph(
                _text(
                    (f"{k['change']['pct']:+.1f}% vs previous period"
                     if k.get("change") else ("Derived metric" if k.get("derived") else
                                              f"{k['records_used']:,} records")),
                    60,
                ),
                styles["kpi_label"],
            )
            for k in chunk
        ]
        while len(labels) < per_row:
            labels.append(Paragraph("", styles["kpi_label"]))
            values.append(Paragraph("", styles["kpi_value"]))
            notes.append(Paragraph("", styles["kpi_label"]))
        column_width = CONTENT_WIDTH / per_row
        table = Table([labels, values, notes], colWidths=[column_width] * per_row, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        flowables.extend([table, Spacer(1, 5)])
    return flowables


def _insight_block(insight: dict[str, Any], styles: dict[str, ParagraphStyle],
                   show_evidence: bool = True) -> list[Any]:
    evidence = insight.get("evidence", {})
    parts: list[Any] = [
        Paragraph(_text(insight["headline"], 300), styles["h3"]),
        Paragraph(
            f"<font color='#64748B'><b>{insight['type_label']}</b> · confidence "
            f"{insight['confidence']} · priority {insight['priority']['score']:.0f}</font>",
            styles["small"],
        ),
        Paragraph(f"<b>Fact.</b> {_text(insight['fact'], 900)}", styles["body"]),
        Paragraph(f"<b>Interpretation.</b> {_text(insight['interpretation'], 900)}", styles["body"]),
    ]
    if insight.get("so_what"):
        parts.append(Paragraph(f"<b>Why it matters.</b> {_text(insight['so_what'], 700)}",
                               styles["body"]))
    parts.append(Paragraph(f"<b>Recommendation.</b> {_text(insight['recommendation'], 700)}",
                           styles["body"]))
    if show_evidence and evidence:
        math = evidence.get("math") or {}
        detail = (
            f"Source columns: {', '.join(evidence.get('source_columns') or []) or 'n/a'} · "
            f"Calculation: {evidence.get('calculation', 'n/a')} · "
            f"Records used: {evidence.get('records_used', 0):,}"
        )
        if math.get("formula"):
            detail += f" · {math['formula']}"
            if math.get("result"):
                detail += f" = {math['result']}"
        parts.append(Paragraph(_text(detail, 900), styles["small"]))
    parts.append(Spacer(1, 4))
    return parts


# --- report assembly --------------------------------------------------------

def generate_pdf(
    analysis: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> bytes:
    config = dict(config or {})
    style_key = str(config.get("style", "standard")).lower()
    preset = STYLE_PRESETS.get(style_key, STYLE_PRESETS["standard"])
    requested_sections = config.get("sections")
    sections = [s for s in preset["sections"] if not requested_sections or s in requested_sections
                or s in {"cover", "toc"}]
    include_charts = config.get("include_charts", True)
    audience = config.get("audience", "manager")

    meta = analysis.get("meta", {})
    profile = analysis["profile"]
    dataset_name = config.get("dataset_name") or meta.get("filename") or "Dataset"
    generated_at = datetime.now(timezone.utc).strftime("%d %B %Y %H:%M UTC")

    document_config = {
        "title": config.get("title") or f"{dataset_name} - Analytics Report",
        "organization": config.get("organization", ""),
        "author": config.get("author", "AI Data Analyst"),
        "dataset_name": dataset_name,
        "generated_at": generated_at,
    }

    styles = _styles()

    def render(active: dict[str, Any]) -> tuple[bytes, int]:
        buffer = io.BytesIO()
        document = ReportDocument(buffer, document_config)
        story: list[Any] = []
        toc_entries: list[str] = []

        def heading(text: str) -> Paragraph:
            toc_entries.append(text)
            return Paragraph(_text(text, 120), styles["h1"])

        # --- cover ---------------------------------------------------------------
        story.append(Spacer(1, 12 * mm))
        logo = config.get("logo_bytes")
        if logo:
            try:
                image = Image(io.BytesIO(logo))
                ratio = image.imageHeight / max(image.imageWidth, 1)
                image.drawWidth = min(46 * mm, CONTENT_WIDTH)
                image.drawHeight = image.drawWidth * ratio
                image.hAlign = "LEFT"
                story.extend([image, Spacer(1, 8 * mm)])
            except Exception:  # noqa: BLE001 - a bad logo must not break the report
                pass
        story.append(Paragraph(
            f"<font color='#93C5FD'>{_text(config.get('organization') or 'Analytics Report', 90)}</font>",
            styles["subtitle"]))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            f"<font color='#FFFFFF'>{_text(document_config['title'], 140)}</font>", styles["title"]))
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(
            f"<font color='#CBD5E1'>{_text(analysis.get('summary', ''), 600)}</font>",
            styles["subtitle"]))
        story.append(Spacer(1, 30 * mm))

        quality = analysis.get("quality", {})
        score = analysis.get("story_score", {})
        cover_rows = [
            ["Dataset", "Records", "Columns", "Data quality", "Story strength"],
            [
                _text(dataset_name, 40), f"{profile['row_count']:,}", f"{profile['column_count']}",
                f"{quality.get('score', 0):.0f}/100 {quality.get('grade', '')}",
                f"{score.get('score', 0):.0f}/100 {score.get('label', '')}",
            ],
        ]
        story.append(_table(cover_rows, [CONTENT_WIDTH / 5] * 5, styles))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            f"Prepared by {_text(config.get('author', 'AI Data Analyst'), 60)} · {generated_at}"
            + (f" · Period {_text(config.get('date_range'), 60)}" if config.get("date_range") else ""),
            styles["small"],
        ))
        story.append(Paragraph(
            "Every figure in this report is calculated directly from the uploaded dataset. "
            "Interpretations are labelled with a confidence level and each finding carries the "
            "columns, calculation and record count behind it.",
            styles["small"],
        ))
        story.append(NextPageTemplate("body"))
        story.append(PageBreak())

        body: list[Any] = []
        _build_body(body, analysis, config, active, sections, styles, heading,
                    include_charts, audience)

        # --- table of contents ---------------------------------------------------
        if "toc" in sections and len(toc_entries) > 4:
            toc: list[Any] = [Paragraph("Contents", styles["h1"])]
            for index, entry in enumerate(toc_entries, start=1):
                toc.append(Paragraph(f"{index}. {_text(entry, 110)}", styles["toc"]))
            toc.append(PageBreak())
            story.extend(toc)
        story.extend(body)

        document.build(story)
        return buffer.getvalue(), int(getattr(document, "page", 0))

    # A style declares a page range, so the report has to honour it. Rather than
    # truncating mid-section, the least important content is trimmed and the
    # report re-rendered: fewer supporting insights, charts and story cards, in
    # that order of sacrifice. Two attempts is enough to bring a long dataset
    # inside its budget, and the last render is used either way - an
    # over-long report beats no report.
    budget = preset.get("max_pages")
    active = dict(preset)
    rendered, pages = render(active)
    for _ in range(3):
        if not budget or pages <= budget:
            break
        active = {
            **active,
            "max_insights": max(4, int(active["max_insights"] * 0.7)),
            "max_charts": max(2, int(active["max_charts"] * 0.7)),
            "max_story_cards": max(3, int(active["max_story_cards"] * 0.75)),
            "group_limit": max(2, active["group_limit"] - 1),
        }
        rendered, pages = render(active)
    return rendered


def _build_body(story, analysis, config, preset, sections, styles, heading,
                include_charts, audience) -> None:
    profile = analysis["profile"]
    charts = {c["id"]: c for c in analysis.get("charts", [])}
    insights = analysis.get("insights", [])
    quality = analysis.get("quality", {})
    briefing = analysis.get("briefing", {})
    currency = profile.get("currency_symbol", "")

    def by_type(kind: str, limit: int) -> list[dict[str, Any]]:
        return [i for i in insights if i["type"] == kind][:limit]

    # --- executive briefing --------------------------------------------------
    if "briefing" in sections and briefing:
        story.append(heading("Executive Briefing"))
        status_color = {"Positive": "#059669", "Neutral": "#D97706", "Concerning": "#DC2626"}.get(
            briefing.get("status", "Neutral"), "#64748B"
        )
        story.append(Paragraph(
            f"<b>Overall status:</b> <font color='{status_color}'><b>{briefing['status']}</b></font>",
            styles["body"]))
        story.append(Paragraph(_text(briefing.get("status_reason", ""), 800), styles["body"]))
        for title, key in (("Biggest wins", "wins"), ("Biggest concerns", "concerns"),
                           ("Important trends", "trends"), ("Opportunities", "opportunities")):
            items = briefing.get(key) or []
            if not items:
                continue
            story.append(Paragraph(title, styles["h3"]))
            for item in items[:3]:
                story.append(Paragraph(
                    f"• <b>{_text(item['headline'], 220)}</b> — {_text(item['detail'], 500)}",
                    styles["body"]))
        actions = briefing.get("actions") or []
        if actions:
            story.append(Paragraph("Recommended actions", styles["h3"]))
            story.append(_table(
                [["Priority", "Action"]] + [[a["priority"].title(), a["action"]] for a in actions],
                [26 * mm, CONTENT_WIDTH - 26 * mm], styles,
            ))
        numbers = briefing.get("key_numbers") or []
        if numbers:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Key numbers", styles["h3"]))
            story.append(_table(
                [["Metric", "Value"]] + [[n["label"], n["value"]] for n in numbers],
                [CONTENT_WIDTH * 0.62, CONTENT_WIDTH * 0.38], styles, align_right={1},
            ))

    # --- executive summary ---------------------------------------------------
    if "executive_summary" in sections:
        story.append(heading("Executive Summary"))
        story.append(Paragraph(_text(analysis.get("summary", ""), 1200), styles["body"]))
        story_sections = {s["key"]: s for s in analysis.get("story", {}).get("sections", [])}
        if "executive_summary" in story_sections:
            story.append(Paragraph(_text(story_sections["executive_summary"]["narrative"], 2000),
                                   styles["body"]))
        if "big_picture" in story_sections:
            story.append(Paragraph("The big picture", styles["h3"]))
            story.append(Paragraph(_text(story_sections["big_picture"]["narrative"], 2000),
                                   styles["body"]))

    # --- KPI dashboard -------------------------------------------------------
    if "kpis" in sections:
        kpis = analysis.get("kpis", {}).get("primary", [])
        if kpis:
            story.append(heading("KPI Dashboard"))
            story.extend(_kpi_grid(kpis, styles))
            story.append(Paragraph(
                "Metrics marked as derived are calculated from two or more columns; the formula is "
                "listed in the appendix.", styles["small"]))

    # --- data quality --------------------------------------------------------
    if "quality" in sections and quality:
        story.append(heading("Data Quality"))
        story.append(Paragraph(
            f"<b>Score: {quality['score']:.0f}/100 ({quality['grade']})</b>", styles["body"]))
        story.append(Paragraph(_text(quality.get("explanation", ""), 1500), styles["body"]))
        components = quality.get("components", {})
        if components:
            story.append(_table(
                [["Dimension", "Score"]] + [[k.title(), f"{v:.0f}/100"] for k, v in components.items()],
                [CONTENT_WIDTH * 0.6, CONTENT_WIDTH * 0.4], styles, align_right={1},
            ))
        issues = quality.get("issues", [])[:8]
        if issues:
            story.append(Spacer(1, 5))
            story.append(Paragraph("Issues and their analytical impact", styles["h3"]))
            story.append(_table(
                [["Severity", "Issue", "Impact on this analysis"]]
                + [[i["severity"].title(), i["title"], i["impact"]] for i in issues],
                [20 * mm, CONTENT_WIDTH * 0.34, CONTENT_WIDTH - 20 * mm - CONTENT_WIDTH * 0.34],
                styles,
            ))
        recommendations = quality.get("recommendations", [])
        if recommendations:
            story.append(Paragraph("Data quality recommendations", styles["h3"]))
            for item in recommendations[:6]:
                story.append(Paragraph(f"• {_text(item, 500)}", styles["body"]))

    # --- data story ----------------------------------------------------------
    if "story" in sections:
        story.append(heading("Data Story"))
        cards = analysis.get("story", {}).get("cards", [])[:preset["max_story_cards"]]
        chart_budget = preset["max_charts"] if include_charts else 0
        for card in cards:
            block: list[Any] = [Paragraph(_text(card["headline"], 240), styles["h2"])]
            if card.get("fact"):
                block.append(Paragraph(f"<b>Fact.</b> {_text(card['fact'], 900)}", styles["body"]))
            if card.get("explanation"):
                block.append(Paragraph(_text(card["explanation"], 1400), styles["body"]))
            if card.get("so_what"):
                block.append(Paragraph(f"<b>Why it matters.</b> {_text(card['so_what'], 700)}",
                                       styles["body"]))
            if card.get("recommendation"):
                block.append(Paragraph(f"<b>Recommendation.</b> {_text(card['recommendation'], 700)}",
                                       styles["body"]))
            evidence = card.get("evidence") or {}
            block.append(Paragraph(
                _text(
                    f"Evidence — columns: {', '.join(evidence.get('source_columns') or []) or 'n/a'}; "
                    f"calculation: {evidence.get('calculation', 'n/a')}; "
                    f"records: {evidence.get('records_used', 0):,}; "
                    f"confidence: {card.get('confidence', 'n/a')}", 900,
                ),
                styles["small"],
            ))
            story.append(KeepTogether(block))
            chart = charts.get(card.get("chart_id"))
            if chart and chart_budget > 0:
                drawing = draw_chart(chart)
                if drawing:
                    story.append(Paragraph(_text(chart["title"], 140), styles["h3"]))
                    story.append(drawing)
                    story.append(Paragraph(_text(chart["question"], 240), styles["small"]))
                    chart_budget -= 1
            story.append(Spacer(1, 5))

    # --- insight groups ------------------------------------------------------
    group_sections = [
        ("trends", "Major Trends", "trend"),
        ("drivers", "Key Drivers", "driver"),
        ("winners", "Winners", "performance"),
        ("underperformers", "Underperformers", "opportunity"),
        ("anomalies", "Anomalies", "anomaly"),
        ("relationships", "Relationships", "relationship"),
        ("risks", "Risks", "risk"),
        ("opportunities", "Opportunities", "opportunity"),
    ]
    used: set[str] = set()
    for key, title, insight_type in group_sections:
        if key not in sections:
            continue
        limit = preset.get("group_limit", 3)
        items = [i for i in by_type(insight_type, limit + len(used)) if i["id"] not in used][:limit]
        if not items:
            continue
        story.append(heading(title))
        for insight in items:
            used.add(insight["id"])
            story.append(KeepTogether(_insight_block(insight, styles)))

    # --- recommendations -----------------------------------------------------
    if "recommendations" in sections:
        recommendations = analysis.get("recommendations", [])[:preset["max_recommendations"]]
        if recommendations:
            story.append(heading("Recommendations"))
            story.append(_table(
                [["Priority", "Recommended action", "Evidence"]]
                + [
                    [
                        r["priority"].title(), r["action"],
                        f"{r['rationale']} (records: {r['evidence'].get('records_used') or 0:,})",
                    ]
                    for r in recommendations
                ],
                [20 * mm, CONTENT_WIDTH * 0.42, CONTENT_WIDTH - 20 * mm - CONTENT_WIDTH * 0.42],
                styles,
            ))

    # --- charts appendix -----------------------------------------------------
    if "charts" in sections and include_charts:
        remaining = [c for c in analysis.get("charts", [])][:preset["max_charts"]]
        if remaining:
            story.append(heading("Visual Analysis"))
            for chart in remaining:
                drawing = draw_chart(chart)
                if not drawing:
                    continue
                block = [
                    Paragraph(_text(chart["title"], 160), styles["h2"]),
                    Paragraph(f"<b>Question.</b> {_text(chart['question'], 300)}", styles["body"]),
                    drawing,
                    Paragraph(
                        _text(f"Why this chart: {chart['reason']} · Calculation: "
                              f"{chart['calculation']}", 700),
                        styles["small"],
                    ),
                ]
                if chart.get("insight"):
                    block.append(Paragraph(_text(chart["insight"], 400), styles["body"]))
                story.append(KeepTogether(block))
                story.append(Spacer(1, 6))

    # --- detailed analytics --------------------------------------------------
    if "analytics" in sections:
        story.append(heading("Detailed Analytics"))
        story.append(Paragraph("Dataset structure", styles["h3"]))
        story.append(_table(
            [["Column", "Detected type", "Role", "Missing", "Distinct"]]
            + [
                [c["name"], c["semantic_type"], c["role"], f"{c['missing_pct']:.1f}%",
                 f"{c['unique']:,}"]
                for c in profile["columns"]
            ],
            [CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.19, CONTENT_WIDTH * 0.17,
             CONTENT_WIDTH * 0.17, CONTENT_WIDTH * 0.17],
            styles, align_right={3, 4},
        ))
        derived = analysis.get("derived_columns") or []
        if derived:
            story.append(Paragraph("Columns calculated from other columns", styles["h3"]))
            for item in derived:
                story.append(Paragraph(f"• {_text(item['narrative'], 400)}", styles["body"]))

    if "statistics" in sections:
        statistics = analysis.get("statistics", {}).get("columns", {})
        if statistics:
            story.append(heading("Statistical Analysis"))
            rows = [["Measure", "Mean", "Median", "Std dev", "Min", "Max", "Skew"]]
            for name, stats in list(statistics.items())[:22]:
                if not stats:
                    continue
                rows.append([
                    name,
                    f"{stats['mean']:,.2f}" if stats.get("mean") is not None else "n/a",
                    f"{stats['median']:,.2f}" if stats.get("median") is not None else "n/a",
                    f"{stats['std']:,.2f}" if stats.get("std") is not None else "n/a",
                    f"{stats['min']:,.2f}" if stats.get("min") is not None else "n/a",
                    f"{stats['max']:,.2f}" if stats.get("max") is not None else "n/a",
                    f"{stats['skewness']:.2f}" if stats.get("skewness") is not None else "n/a",
                ])
            widths = [CONTENT_WIDTH * 0.22] + [CONTENT_WIDTH * 0.13] * 6
            story.append(_table(rows, widths, styles, align_right={1, 2, 3, 4, 5, 6}))

    if "correlations" in sections:
        correlations = analysis.get("correlations", {})
        if correlations.get("pairs"):
            story.append(heading("Correlations"))
            story.append(Paragraph(_text(correlations.get("caveat", ""), 700), styles["body"]))
            story.append(_table(
                [["Pair", "r", "Strength", "Observations", "Significant"]]
                + [
                    [f"{p['x']} ~ {p['y']}", f"{p['pearson_r']:.2f}", p["strength"],
                     f"{p['observations']:,}", "yes" if p["significant"] else "no"]
                    for p in correlations["pairs"][:18]
                ],
                [CONTENT_WIDTH * 0.36, CONTENT_WIDTH * 0.1, CONTENT_WIDTH * 0.22,
                 CONTENT_WIDTH * 0.18, CONTENT_WIDTH * 0.14],
                styles, align_right={1, 3},
            ))

    # --- appendix ------------------------------------------------------------
    if "appendix" in sections:
        story.append(heading("Appendix: Methodology and Evidence"))
        story.append(Paragraph(
            "Every figure in this report is computed from the uploaded dataset by the analytics "
            "engine. Interpretations are separated from facts and each carries a confidence level: "
            "<b>high</b> means directly calculated, <b>medium</b> means strong analytical evidence "
            "that still requires interpretation, and <b>low</b> means a possible explanation that "
            "needs further investigation.", styles["body"]))
        story.append(Paragraph("Methods used", styles["h3"]))
        for line in (
            "Semantic type inference from cell values, not column names.",
            "Trends: ordinary least squares regression on the aggregated series, with incomplete "
            "boundary periods removed.",
            "Anomalies: interquartile fences confirmed by a modified z-score (median absolute "
            "deviation), plus de-trended residual analysis for time series.",
            "Correlations: Pearson and Spearman coefficients with significance testing, excluding "
            "pairs where one column is arithmetically derived from the other.",
            "Concentration: Pareto cumulative shares and the Herfindahl-Hirschman index.",
            "Data quality: weighted completeness, uniqueness, validity, consistency and structure.",
        ):
            story.append(Paragraph(f"• {line}", styles["body"]))

        derived_kpis = [k for k in analysis.get("kpis", {}).get("all", []) if k.get("derived")]
        if derived_kpis:
            story.append(Paragraph("Derived metric formulas", styles["h3"]))
            story.append(_table(
                [["Metric", "Formula", "Value"]]
                + [[k["label"], k["calculation"], k["formatted"]] for k in derived_kpis],
                [CONTENT_WIDTH * 0.34, CONTENT_WIDTH * 0.42, CONTENT_WIDTH * 0.24],
                styles, align_right={2},
            ))

        story.append(Paragraph("All findings by priority", styles["h3"]))
        story.append(_table(
            [["#", "Type", "Finding", "Confidence", "Score"]]
            + [
                [str(i["rank"]), i["type_label"], i["headline"], i["confidence"],
                 f"{i['priority']['score']:.0f}"]
                for i in insights[:40]
            ],
            [10 * mm, 24 * mm, CONTENT_WIDTH - 10 * mm - 24 * mm - 22 * mm - 14 * mm,
             22 * mm, 14 * mm],
            styles, align_right={4},
        ))
