"""End-to-end tests.

Two things are checked here that the unit tests cannot:

1. **The whole journey works through the HTTP API**, in the order a real user
   performs it — register, upload, wait, read, filter, drill down, ask, export,
   share, re-analyse, delete.
2. **The numbers are true.** Every figure the platform reports is recomputed
   independently from the source workbook with plain pandas and compared. A
   pipeline can be internally consistent and still be wrong; this is the check
   that catches that.
"""
from __future__ import annotations

import io
import re
import time

import numpy as np
import pandas as pd
import pytest
from pypdf import PdfReader

from tests.conftest import write_workbook

# ---------------------------------------------------------------------------
# A dataset with known, planted properties. Every expectation below is derived
# from this frame directly, never from the platform's own output.
# ---------------------------------------------------------------------------

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Alpha", "Beta", "Gamma"]


@pytest.fixture(scope="module")
def source_frame() -> pd.DataFrame:
    rng = np.random.default_rng(2024)
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    rows = []
    for date in dates:
        for _ in range(2):
            region = rng.choice(REGIONS, p=[0.50, 0.20, 0.18, 0.12])
            product = rng.choice(PRODUCTS, p=[0.55, 0.30, 0.15])
            units = int(rng.integers(1, 25))
            price = float(max(rng.normal(900, 120), 120))
            revenue = round(units * price, 2)
            cost = round(revenue * 0.68, 2)
            rows.append({
                "Order ID": f"ORD{len(rows):06d}",
                "Order Date": date,
                "Region": region,
                "Product": product,
                "Units": units,
                "Revenue": revenue,
                "Cost": cost,
                "Profit": round(revenue - cost, 2),
                "Rating": round(float(np.clip(rng.normal(4.1, 0.4), 1, 5)), 1),
            })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def source_workbook(source_frame: pd.DataFrame) -> bytes:
    return write_workbook({"Orders": source_frame})


def wait_for(client, headers, session_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status", headers=headers).json()
        if status["status"] in {"completed", "failed"}:
            return status
        time.sleep(0.25)
    raise AssertionError("the analysis did not finish in time")


@pytest.fixture
def journey(client, auth_headers, source_workbook):
    """Upload the workbook and wait for the pipeline, once per test."""
    upload = client.post(
        "/api/datasets/upload", headers=auth_headers,
        files={"file": ("orders.xlsx", source_workbook, "application/vnd.ms-excel")},
    )
    assert upload.status_code == 202, upload.text
    session_id = upload.json()["id"]
    status = wait_for(client, auth_headers, session_id)
    assert status["status"] == "completed", status.get("error")
    return session_id


def parse_compact(text: str) -> float:
    """Turn a displayed figure such as '55.33M' or '₹1.2K' back into a number."""
    cleaned = re.sub(r"[^\d.\-KMBT]", "", text.replace(",", ""))
    multiplier = 1.0
    for suffix, factor in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if cleaned.endswith(suffix):
            multiplier = factor
            cleaned = cleaned[:-1]
            break
    return float(cleaned) * multiplier


# ---------------------------------------------------------------------------
# 1. The complete journey
# ---------------------------------------------------------------------------

def test_the_whole_journey(client, auth_headers, source_workbook, source_frame):
    """Every step a user takes, in order, through the public API."""
    # --- upload and wait ---------------------------------------------------
    upload = client.post(
        "/api/datasets/upload", headers=auth_headers,
        files={"file": ("orders.xlsx", source_workbook, "application/vnd.ms-excel")},
    )
    assert upload.status_code == 202
    session_id = upload.json()["id"]
    assert upload.json()["status"] == "pending"

    status = wait_for(client, auth_headers, session_id)
    assert status["status"] == "completed"
    assert status["progress"]["percent"] == 100
    assert all(stage["done"] for stage in status["progress"]["stages"])

    # --- read the analysis --------------------------------------------------
    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert analysis["profile"]["row_count"] == len(source_frame)
    assert analysis["insights"], "a dataset with planted structure must yield findings"
    assert analysis["charts"]
    assert analysis["story"]["cards"]

    # --- filter -------------------------------------------------------------
    filtered = client.post(f"/api/sessions/{session_id}/filter", headers=auth_headers, json={
        "filters": [{"column": "Region", "type": "multi_select", "values": ["North"]}],
    }).json()
    expected_rows = int((source_frame["Region"] == "North").sum())
    assert filtered["filter_summary"]["records"] == expected_rows

    # --- drill down ---------------------------------------------------------
    drilldown = client.post(f"/api/sessions/{session_id}/drilldown", headers=auth_headers, json={
        "dimension": "Region", "value": "North", "measure": "Revenue",
    }).json()
    assert drilldown["records"] == expected_rows

    # --- ask ----------------------------------------------------------------
    answer = client.post(f"/api/sessions/{session_id}/ask", headers=auth_headers, json={
        "question": "Show the top 5 Region by Revenue",
    }).json()
    assert answer["supported"]
    assert answer["table"]

    # --- investigate an anomaly, when there is one ---------------------------
    anomalies = analysis["anomalies"]["items"]
    if anomalies:
        investigation = client.get(
            f"/api/sessions/{session_id}/anomalies/{anomalies[0]['id']}/investigate",
            headers=auth_headers,
        )
        assert investigation.status_code == 200
        assert "causation" in investigation.json()["caveat"]

    # --- story and briefing --------------------------------------------------
    story = client.get(f"/api/sessions/{session_id}/story?audience=analyst",
                       headers=auth_headers).json()
    assert story["cards"]
    briefing = client.get(f"/api/sessions/{session_id}/briefing", headers=auth_headers).json()
    assert briefing["status"] in {"Positive", "Neutral", "Concerning"}

    # --- explore rows ---------------------------------------------------------
    page = client.post(f"/api/sessions/{session_id}/data", headers=auth_headers,
                       json={"limit": 20, "offset": 0}).json()
    assert page["total"] == len(source_frame)
    assert len(page["rows"]) == 20

    # --- exports ---------------------------------------------------------------
    pdf = client.post(f"/api/sessions/{session_id}/report/pdf", headers=auth_headers,
                      json={"style": "standard", "title": "Journey report"})
    assert pdf.content.startswith(b"%PDF")
    workbook = client.post(f"/api/sessions/{session_id}/export/excel", headers=auth_headers,
                           json={"include_data": False})
    assert workbook.content.startswith(b"PK")
    csv = client.post(f"/api/sessions/{session_id}/export/data", headers=auth_headers,
                      json={"data_row_limit": 100})
    assert csv.text.splitlines()[0].startswith("Order ID")

    # --- share -----------------------------------------------------------------
    share = client.post(f"/api/sessions/{session_id}/share", headers=auth_headers,
                        json={"expires_in_hours": 24}).json()
    shared = client.get(f"/api/shared/{share['token']}").json()
    assert shared["insights"]

    # --- personalise -----------------------------------------------------------
    client.patch(f"/api/sessions/{session_id}", headers=auth_headers, json={
        "name": "Journey test", "bookmarks": ["ins_001"], "notes": {"ins_001": "follow up"},
    })
    reread = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert reread["session"]["name"] == "Journey test"
    assert reread["session"]["bookmarks"] == ["ins_001"]

    # --- re-analyse a single sheet ----------------------------------------------
    client.post(f"/api/sessions/{session_id}/analyze", headers=auth_headers,
                json={"scope": "sheet", "sheet": "Orders"})
    assert wait_for(client, auth_headers, session_id)["status"] == "completed"

    # --- delete ------------------------------------------------------------------
    assert client.delete(f"/api/sessions/{session_id}",
                         headers=auth_headers).status_code == 204
    assert client.get(f"/api/sessions/{session_id}",
                      headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# 2. The numbers are true
# ---------------------------------------------------------------------------

def test_kpi_totals_match_the_source_workbook(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    by_key = {kpi["key"]: kpi for kpi in analysis["kpis"]["all"]}

    assert by_key["measure::Revenue::sum"]["value"] == pytest.approx(
        float(source_frame["Revenue"].sum()), rel=1e-9)
    assert by_key["measure::Profit::sum"]["value"] == pytest.approx(
        float(source_frame["Profit"].sum()), rel=1e-9)
    assert by_key["measure::Units::sum"]["value"] == pytest.approx(
        float(source_frame["Units"].sum()), rel=1e-9)
    # Rating is a score, so it is averaged rather than summed.
    assert by_key["measure::Rating::mean"]["value"] == pytest.approx(
        float(source_frame["Rating"].mean()), rel=1e-9)
    assert by_key["record_count"]["value"] == len(source_frame)


def test_derived_margin_matches_a_hand_calculation(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    margin = next(k for k in analysis["kpis"]["all"] if k["key"] == "derived::profit_margin")
    expected = source_frame["Profit"].sum() / source_frame["Revenue"].sum() * 100
    assert margin["value"] == pytest.approx(expected, rel=1e-9)
    assert margin["derived"] is True


def test_displayed_kpi_strings_match_their_own_values(client, auth_headers, journey):
    """The formatted string a user reads must agree with the underlying number."""
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    for kpi in analysis["kpis"]["all"]:
        if kpi["value"] is None or kpi["semantic_type"] == "percentage":
            continue
        displayed = parse_compact(kpi["formatted"])
        assert displayed == pytest.approx(abs(kpi["value"]), rel=0.01), kpi["label"]


def test_segment_totals_match_a_groupby(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    segment = next(s for s in analysis["segments"]
                   if s["dimension"] == "Region" and s["measure"] == "Revenue")
    expected = source_frame.groupby("Region")["Revenue"].sum()

    # Every group must be present, not merely every reported group correct - a
    # comparison that silently drops a segment is wrong even if what it shows
    # adds up.
    assert {g["group"] for g in segment["groups"]} == set(expected.index)
    assert segment["group_count"] == len(expected)
    assert sum(g["count"] for g in segment["groups"]) == len(source_frame)

    for group in segment["groups"]:
        assert group["value"] == pytest.approx(float(expected[group["group"]]), rel=1e-9)
        assert group["count"] == int((source_frame["Region"] == group["group"]).sum())
        assert group["share_pct"] == pytest.approx(
            float(expected[group["group"]]) / float(expected.sum()) * 100, abs=0.01)

    assert segment["best"]["group"] == expected.idxmax()
    assert segment["worst"]["group"] == expected.idxmin()


def test_concentration_shares_match_a_hand_calculation(client, auth_headers, journey,
                                                       source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    item = next((c for c in analysis["concentration"]
                 if c["dimension"] == "Region" and c["measure"] == "Revenue"), None)
    if item is None:
        pytest.skip("no concentration analysis for Region/Revenue")

    totals = source_frame.groupby("Region")["Revenue"].sum().sort_values(ascending=False)
    assert item["top_group"] == totals.index[0]
    assert item["top1_pct"] == pytest.approx(totals.iloc[0] / totals.sum() * 100, abs=0.05)
    assert item["group_count"] == source_frame["Region"].nunique()


def test_trend_points_match_a_resample(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    trend = next(t for t in analysis["trends"] if t["measure"] == "Revenue")
    assert trend["aggregation"] == "sum"

    monthly = (source_frame.set_index("Order Date")
               .resample("MS")["Revenue"].agg(["sum", "count"]))
    reported = {point["label"]: point for point in trend["points"]}

    for period, row in monthly.iterrows():
        label = period.strftime("%b %Y")
        if label not in reported:      # boundary periods may be trimmed
            continue
        assert reported[label]["value"] == pytest.approx(float(row["sum"]), rel=1e-9), label
        assert reported[label]["records"] == int(row["count"]), label

    # The whole series is covered: the dataset starts and ends on month boundaries.
    assert len(trend["points"]) == len(monthly)


def test_correlation_matches_pandas(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    pair = next((p for p in analysis["correlations"]["pairs"]
                 if {p["x"], p["y"]} == {"Units", "Revenue"}), None)
    assert pair is not None
    expected = source_frame["Units"].corr(source_frame["Revenue"])
    assert pair["pearson_r"] == pytest.approx(float(expected), abs=0.001)
    assert pair["observations"] == len(source_frame)


def test_statistics_match_pandas(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    stats = analysis["statistics"]["columns"]["Revenue"]
    column = source_frame["Revenue"]
    assert stats["mean"] == pytest.approx(float(column.mean()), rel=1e-9)
    assert stats["median"] == pytest.approx(float(column.median()), rel=1e-9)
    assert stats["std"] == pytest.approx(float(column.std(ddof=1)), rel=1e-9)
    assert stats["min"] == pytest.approx(float(column.min()), rel=1e-9)
    assert stats["max"] == pytest.approx(float(column.max()), rel=1e-9)
    assert stats["count"] == int(column.notna().sum())


def test_quality_metrics_match_the_source(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    metrics = analysis["quality"]["metrics"]
    assert metrics["rows"] == len(source_frame)
    assert metrics["columns"] == source_frame.shape[1]
    assert metrics["missing_cells"] == int(source_frame.isna().sum().sum())
    assert metrics["duplicate_rows"] == int(source_frame.duplicated().sum())


def test_filtered_analysis_matches_a_filtered_dataframe(client, auth_headers, journey,
                                                        source_frame):
    """Filtering must recalculate, not just hide."""
    filtered = client.post(f"/api/sessions/{journey}/filter", headers=auth_headers, json={
        "filters": [{"column": "Region", "type": "multi_select", "values": ["North", "South"]}],
    }).json()

    subset = source_frame[source_frame["Region"].isin(["North", "South"])]
    assert filtered["profile"]["row_count"] == len(subset)

    revenue = next(k for k in filtered["kpis"]["all"] if k["key"] == "measure::Revenue::sum")
    assert revenue["value"] == pytest.approx(float(subset["Revenue"].sum()), rel=1e-9)

    statistics = filtered["statistics"]["columns"]["Revenue"]
    assert statistics["mean"] == pytest.approx(float(subset["Revenue"].mean()), rel=1e-9)


def test_drilldown_metrics_match_the_source(client, auth_headers, journey, source_frame):
    drilldown = client.post(f"/api/sessions/{journey}/drilldown", headers=auth_headers, json={
        "dimension": "Region", "value": "North", "measure": "Revenue",
    }).json()

    subset = source_frame[source_frame["Region"] == "North"]
    assert drilldown["records"] == len(subset)
    assert drilldown["share_of_records_pct"] == pytest.approx(
        len(subset) / len(source_frame) * 100, abs=0.01)

    revenue = next(m for m in drilldown["metrics"] if m["measure"] == "Revenue")
    assert revenue["value"] == pytest.approx(float(subset["Revenue"].sum()), rel=1e-9)
    assert revenue["average"] == pytest.approx(float(subset["Revenue"].mean()), rel=1e-9)
    assert revenue["share_pct"] == pytest.approx(
        float(subset["Revenue"].sum()) / float(source_frame["Revenue"].sum()) * 100, abs=0.01)

    breakdown = next(b for b in drilldown["breakdowns"] if b["dimension"] == "Product")
    expected = subset.groupby("Product")["Revenue"].sum()
    assert {row["name"] for row in breakdown["rows"]} == set(expected.index)
    for row in breakdown["rows"]:
        assert row["value"] == pytest.approx(float(expected[row["name"]]), rel=1e-9)


def test_ask_answers_match_the_source(client, auth_headers, journey, source_frame):
    ranking = client.post(f"/api/sessions/{journey}/ask", headers=auth_headers, json={
        "question": "Show the top 4 Region by Revenue",
    }).json()
    expected = source_frame.groupby("Region")["Revenue"].sum().sort_values(ascending=False)
    assert [row["Region"] for row in ranking["table"]] == list(expected.index)
    assert ranking["records_used"] == len(source_frame)

    total = client.post(f"/api/sessions/{journey}/ask", headers=auth_headers, json={
        "question": "What is the total Revenue?",
    }).json()
    reported = next(row["value"] for row in total["table"] if row["metric"] == "Total")
    assert parse_compact(reported) == pytest.approx(
        float(source_frame["Revenue"].sum()), rel=0.01)

    counted = client.post(f"/api/sessions/{journey}/ask", headers=auth_headers, json={
        "question": "How many records are there?",
    }).json()
    assert f"{len(source_frame):,}" in counted["answer"]


def test_explore_rows_match_the_source(client, auth_headers, journey, source_frame):
    page = client.post(f"/api/sessions/{journey}/data", headers=auth_headers, json={
        "limit": 5, "sort_by": "Revenue", "sort_desc": True,
    }).json()
    expected = source_frame.nlargest(5, "Revenue")["Revenue"].tolist()
    assert [row["Revenue"] for row in page["rows"]] == pytest.approx(expected)

    searched = client.post(f"/api/sessions/{journey}/data", headers=auth_headers, json={
        "limit": 5, "search": "Gamma",
    }).json()
    assert searched["total"] == int((source_frame["Product"] == "Gamma").sum())


def test_exported_csv_matches_the_source(client, auth_headers, journey, source_frame):
    response = client.post(f"/api/sessions/{journey}/export/data", headers=auth_headers, json={
        "data_row_limit": 100000,
        "filters": [{"column": "Region", "type": "multi_select", "values": ["East"]}],
    })
    exported = pd.read_csv(io.StringIO(response.text))
    subset = source_frame[source_frame["Region"] == "East"]
    assert len(exported) == len(subset)
    assert exported["Revenue"].sum() == pytest.approx(float(subset["Revenue"].sum()), rel=1e-6)


def test_exported_workbook_matches_the_analysis(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    response = client.post(f"/api/sessions/{journey}/export/excel", headers=auth_headers,
                           json={"include_data": False})
    book = io.BytesIO(response.content)

    kpis = pd.read_excel(book, "KPIs", header=2)
    row = kpis.loc[kpis["KPI"] == "Total Revenue"].iloc[0]
    assert float(row["Raw value"]) == pytest.approx(float(source_frame["Revenue"].sum()), rel=1e-6)

    insights = pd.read_excel(io.BytesIO(response.content), "Key Insights", header=2)
    assert len(insights) == len(analysis["insights"])
    assert insights["Headline"].iloc[0] == analysis["insights"][0]["headline"]

    segments = pd.read_excel(io.BytesIO(response.content), "Segment Analysis", header=2)
    region_rows = segments[(segments["Dimension"] == "Region")
                           & (segments["Measure"] == "Revenue")]
    expected = source_frame.groupby("Region")["Revenue"].sum()
    for _, entry in region_rows.iterrows():
        assert float(entry["Value"]) == pytest.approx(
            float(expected[entry["Group"]]), rel=1e-6)


def test_exported_pdf_reports_the_same_figures(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    response = client.post(f"/api/sessions/{journey}/report/pdf", headers=auth_headers,
                           json={"style": "detailed", "title": "Verification report"})
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)

    # The report states the dataset's real size.
    assert f"{len(source_frame):,}" in text
    # The leading finding appears verbatim.
    assert analysis["insights"][0]["headline"][:50] in text
    # The headline KPI value appears as displayed in the app.
    assert analysis["kpis"]["primary"][0]["formatted"] in text
    # The quality score is carried through.
    assert f"{analysis['quality']['score']:.0f}/100" in text


# ---------------------------------------------------------------------------
# 3. Nothing is invented anywhere in the payload
# ---------------------------------------------------------------------------

def test_no_reported_figure_exceeds_the_source_data(client, auth_headers, journey, source_frame):
    """A total can never be larger than the sum of the column it came from."""
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    ceilings = {
        column: float(source_frame[column].abs().sum())
        for column in ("Revenue", "Cost", "Profit", "Units")
    }
    for kpi in analysis["kpis"]["all"]:
        if kpi["aggregation"] != "sum" or not kpi["source_columns"]:
            continue
        column = kpi["source_columns"][0]
        if column in ceilings:
            assert abs(kpi["value"]) <= ceilings[column] * 1.0001, kpi["label"]


def test_every_cited_column_exists(client, auth_headers, journey, source_frame):
    """No insight, chart or recommendation may cite a column that is not there."""
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    known = set(source_frame.columns)

    for insight in analysis["insights"]:
        for column in insight["evidence"].get("source_columns") or []:
            assert column in known, f"{insight['id']} cites {column}"
    for chart in analysis["charts"]:
        for column in chart["columns"]:
            assert column in known, f"{chart['id']} cites {column}"
    for recommendation in analysis["recommendations"]:
        for column in recommendation["source_columns"]:
            assert column in known, f"{recommendation['id']} cites {column}"


def test_record_counts_never_exceed_the_dataset(client, auth_headers, journey, source_frame):
    analysis = client.get(f"/api/sessions/{journey}/analysis", headers=auth_headers).json()
    total = len(source_frame)
    for insight in analysis["insights"]:
        used = insight["evidence"].get("records_used") or 0
        assert used <= total, f"{insight['id']} claims {used} of {total} records"
    for kpi in analysis["kpis"]["all"]:
        assert kpi["records_used"] <= total, kpi["label"]


# ---------------------------------------------------------------------------
# 4. Every sample dataset survives the full journey
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sample", ["sales", "students", "employees", "marketing", "subscriptions", "finance"],
)
def test_every_sample_completes_the_full_journey(client, auth_headers, sample):
    created = client.post(f"/api/samples/{sample}/load", headers=auth_headers)
    assert created.status_code == 202
    session_id = created.json()["id"]
    status = wait_for(client, auth_headers, session_id)
    assert status["status"] == "completed", status.get("error")

    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert analysis["summary"]
    assert analysis["insights"], f"{sample} produced no findings"
    assert analysis["charts"], f"{sample} produced no charts"
    assert analysis["story"]["cards"], f"{sample} produced no story"
    assert 0 <= analysis["quality"]["score"] <= 100

    for style in ("executive", "standard", "detailed"):
        pdf = client.post(f"/api/sessions/{session_id}/report/pdf", headers=auth_headers,
                          json={"style": style})
        assert pdf.status_code == 200, f"{sample}/{style}: {pdf.text[:200]}"
        assert pdf.content.startswith(b"%PDF")

    workbook = client.post(f"/api/sessions/{session_id}/export/excel", headers=auth_headers,
                           json={"include_data": True, "data_row_limit": 200})
    assert workbook.content.startswith(b"PK")

    for question in ("What are the most important findings?",
                     "How reliable is this data?",
                     "Find unusual records"):
        answer = client.post(f"/api/sessions/{session_id}/ask", headers=auth_headers,
                             json={"question": question}).json()
        assert answer["answer"], f"{sample}: no answer to '{question}'"

    # Every sample must also produce a projection or say why it cannot, and
    # offer whatever corrections its data actually warrants.
    forecast = client.get(f"/api/sessions/{session_id}/forecast", headers=auth_headers).json()
    for item in forecast["forecasts"]:
        assert item["available"] or item["reason"], f"{sample}: silent forecast refusal"
    fixes = client.get(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers).json()
    assert all(not proposal["accepted"] for proposal in fixes["proposals"]), \
        f"{sample}: a fix was applied without being accepted"


def test_the_two_sheet_sample_offers_a_join_that_holds_up(client, auth_headers):
    """The sample that exists to exercise joins must actually support one."""
    created = client.post("/api/samples/subscriptions/load", headers=auth_headers)
    session_id = created.json()["id"]
    assert wait_for(client, auth_headers, session_id)["status"] == "completed"

    detected = client.get(f"/api/sessions/{session_id}/joins", headers=auth_headers).json()
    assert detected["relationships"], "the two-sheet sample detected no relationship"
    relationship = detected["relationships"][0]
    assert relationship["join_ready"]

    spec = {"left": relationship["left"], "right": relationship["right"],
            "key": relationship["key"], "how": "inner"}
    report = client.post(f"/api/sessions/{session_id}/joins/preview", headers=auth_headers,
                         json=spec).json()
    assert report["safe"], report["warnings"]
    assert report["cardinality"] in {"many-to-one", "one-to-many", "one-to-one"}

    joined_id = client.post(f"/api/sessions/{session_id}/joins", headers=auth_headers,
                            json=spec).json()["id"]
    assert wait_for(client, auth_headers, joined_id)["status"] == "completed"
    joined = client.get(f"/api/sessions/{joined_id}/analysis", headers=auth_headers).json()

    # The join must add the lookup sheet's dimensions to the analysis...
    assert set(joined["profile"]["roles"]["dimension"]) > set(
        client.get(f"/api/sessions/{session_id}/analysis",
                   headers=auth_headers).json()["profile"]["roles"]["dimension"]
    )
    # ...without letting a repeated attribute be totalled or trended.
    attributes = joined["profile"].get("attribute_columns", [])
    assert attributes, "the lookup side's columns were not marked as repeated attributes"
    for name in attributes:
        column = next(c for c in joined["profile"]["columns"] if c["name"] == name)
        if column["role"] == "measure":
            assert column["aggregation"] == "mean", f"{name} would be summed across repeats"
            assert column["additive"] is False
        assert name not in [t["measure"] for t in joined["trends"]]


# ---------------------------------------------------------------------------
# 5. Failure paths behave
# ---------------------------------------------------------------------------

def test_a_workbook_that_cannot_be_analysed_fails_with_an_explanation(client, auth_headers):
    """A structurally valid xlsx with no usable table must fail cleanly."""
    content = write_workbook({"Sheet1": pd.DataFrame({"Only": [1]})})
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("thin.xlsx", content, "application/vnd.ms-excel")})
    assert upload.status_code == 202
    status = wait_for(client, auth_headers, upload.json()["id"])
    assert status["status"] == "failed"
    assert "analyzable" in status["error"].lower() or "header" in status["error"].lower()


def test_a_dataset_with_no_time_dimension_still_works(client, auth_headers):
    rng = np.random.default_rng(5)
    frame = pd.DataFrame({
        "Department": rng.choice(["Sales", "Ops", "Tech"], 300),
        "Headcount": rng.integers(1, 40, 300),
        "Budget": rng.normal(50000, 12000, 300).round(2),
    })
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("no_dates.xlsx", write_workbook({"D": frame}),
                                         "application/vnd.ms-excel")})
    session_id = upload.json()["id"]
    assert wait_for(client, auth_headers, session_id)["status"] == "completed"

    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert analysis["time_column"] is None
    assert analysis["trends"] == [], "no time dimension means no time comparisons"
    assert analysis["insights"], "segment findings should still be produced"

    answer = client.post(f"/api/sessions/{session_id}/ask", headers=auth_headers,
                         json={"question": "How has Budget changed over time?"}).json()
    assert answer["supported"] is False
    assert "date column" in answer["answer"].lower()


def test_a_dataset_with_no_measures_still_works(client, auth_headers):
    rng = np.random.default_rng(6)
    frame = pd.DataFrame({
        "Status": rng.choice(["Open", "Closed", "Pending"], 200),
        "Owner": rng.choice(["A", "B", "C", "D"], 200),
        "Priority": rng.choice(["Low", "High"], 200),
    })
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("categories.xlsx", write_workbook({"C": frame}),
                                         "application/vnd.ms-excel")})
    session_id = upload.json()["id"]
    assert wait_for(client, auth_headers, session_id)["status"] == "completed"

    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert analysis["profile"]["roles"]["measure"] == []
    assert analysis["charts"], "frequency charts should stand in for measures"
    pdf = client.post(f"/api/sessions/{session_id}/report/pdf", headers=auth_headers,
                      json={"style": "standard"})
    assert pdf.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# 6. Deployment configuration
#
# These settings are only exercised when the app is actually deployed, which is
# where a mistake is most expensive: the process fails to start.
# ---------------------------------------------------------------------------

def test_env_settings_parse_the_documented_forms(monkeypatch):
    """Every value shown in .env.example must actually load."""
    from app.core.config import Settings

    cases = {
        "http://localhost:8080": ["http://localhost:8080"],
        "https://a.example.com,https://b.example.com":
            ["https://a.example.com", "https://b.example.com"],
        ' https://spaced.example.com , https://other.example.com ':
            ["https://spaced.example.com", "https://other.example.com"],
        '["https://json.example.com"]': ["https://json.example.com"],
    }
    for raw, expected in cases.items():
        monkeypatch.setenv("CORS_ORIGINS", raw)
        assert Settings().cors_origins == expected, raw

    monkeypatch.delenv("CORS_ORIGINS")
    assert Settings().cors_origins  # a sane default when unset


def test_scalar_env_settings_load(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("MAX_UPLOAD_MB", "250")
    monkeypatch.setenv("FILE_RETENTION_HOURS", "24")
    monkeypatch.setenv("ALLOW_REGISTRATION", "false")
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_ALLOW_RAW_ROWS", "false")

    settings = Settings()
    assert settings.max_upload_mb == 250
    assert settings.max_upload_bytes == 250 * 1024 * 1024
    assert settings.file_retention_hours == 24
    assert settings.allow_registration is False
    assert settings.ai_provider == "anthropic"
    assert settings.ai_allow_raw_rows is False


def test_an_unconfigured_ai_provider_falls_back_to_deterministic(monkeypatch):
    """Naming a provider without a key must not break narration."""
    from app.core import config as config_module
    from app.engines import ai_provider

    monkeypatch.setattr(config_module.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(config_module.settings, "ai_api_key", "")
    monkeypatch.setattr(ai_provider.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(ai_provider.settings, "ai_api_key", "")

    assert ai_provider.get_provider().name == "deterministic"
    assert ai_provider.narrate("x", {"a": 1}, "fallback")["text"] == "fallback"


# ---------------------------------------------------------------------------
# 7. Connection discipline
#
# SQLite tolerates a transaction held open across a long computation.
# PostgreSQL does not: an idle-in-transaction connection blocks DDL, stops
# autovacuum reclaiming dead tuples, and holds a pool slot. This is the
# regression guard for that.
# ---------------------------------------------------------------------------

def test_analysis_holds_no_database_connection_while_it_runs(client, monkeypatch,
                                                            source_workbook):
    """The pipeline must not pin a connection for the duration of the analysis."""
    from app.core.database import SessionLocal, engine
    from app.models import AnalysisSession, User
    from app.services import analysis_service

    db = SessionLocal()
    try:
        user = User(email=f"pool+{time.time()}@example.com", hashed_password="x")
        db.add(user)
        db.flush()
        session = analysis_service.create_session(
            db, user.id, "pool.xlsx", source_workbook, name="pool test",
        )
        session_id = session.id
    finally:
        db.close()

    checked_out_during_analysis: list[int] = []
    original = analysis_service.analyze_workbook

    def watching_analyze(*args, **kwargs):
        # Sampled at the moment the expensive work begins.
        checked_out_during_analysis.append(engine.pool.checkedout())
        return original(*args, **kwargs)

    monkeypatch.setattr(analysis_service, "analyze_workbook", watching_analyze)
    analysis_service.run_analysis(session_id)

    assert checked_out_during_analysis, "the analysis never ran"
    assert checked_out_during_analysis[0] == 0, (
        "a database connection was held while the analysis ran: "
        f"{checked_out_during_analysis[0]} checked out"
    )

    db = SessionLocal()
    try:
        stored = db.get(AnalysisSession, session_id)
        assert stored.status == "completed"
        assert stored.result["profile"]["row_count"] > 0
    finally:
        db.close()


def test_a_session_deleted_mid_analysis_is_handled(client, source_workbook):
    """Deleting a session while its analysis runs must not raise or hang."""
    from app.core.database import SessionLocal
    from app.models import AnalysisSession, User
    from app.services import analysis_service

    db = SessionLocal()
    try:
        user = User(email=f"gone+{time.time()}@example.com", hashed_password="x")
        db.add(user)
        db.flush()
        session_id = analysis_service.create_session(
            db, user.id, "gone.xlsx", source_workbook, name="deleted mid-run",
        ).id
        db.query(AnalysisSession).filter(AnalysisSession.id == session_id).delete()
        db.commit()
    finally:
        db.close()

    analysis_service.run_analysis(session_id)  # must return quietly
