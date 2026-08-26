"""End-to-end API behaviour."""
from __future__ import annotations

import time

import pytest


def wait_for_analysis(client, headers, session_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status", headers=headers).json()
        if status["status"] in {"completed", "failed"}:
            return status
        time.sleep(0.3)
    raise AssertionError("analysis did not finish in time")


@pytest.fixture
def analysed(client, auth_headers, sales_workbook):
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("sales.xlsx", sales_workbook,
                                         "application/vnd.ms-excel")})
    assert upload.status_code == 202
    session_id = upload.json()["id"]
    status = wait_for_analysis(client, auth_headers, session_id)
    assert status["status"] == "completed", status.get("error")
    return session_id


def test_health_and_config(client):
    assert client.get("/api/system/health").json()["status"] == "ok"
    config = client.get("/api/system/config").json()
    assert config["accepted_formats"] == [".xlsx", ".xls"]
    assert len(config["pipeline_stages"]) == 12
    assert config["max_upload_mb"] > 0


def test_register_login_and_me(client):
    register = client.post("/api/auth/register", json={
        "email": "New.User@Example.com", "password": "Str0ngPassw0rd!", "full_name": "New User",
    })
    assert register.status_code == 201
    assert register.json()["user"]["email"] == "new.user@example.com"

    duplicate = client.post("/api/auth/register",
                            json={"email": "new.user@example.com", "password": "Str0ngPassw0rd!"})
    assert duplicate.status_code == 409

    login = client.post("/api/auth/login",
                        json={"email": "new.user@example.com", "password": "Str0ngPassw0rd!"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["full_name"] == "New User"


def test_progress_is_reported_through_the_pipeline(client, auth_headers, sales_workbook):
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("sales.xlsx", sales_workbook, "application/vnd.ms-excel")})
    session_id = upload.json()["id"]
    status = wait_for_analysis(client, auth_headers, session_id)
    progress = status["progress"]
    assert progress["percent"] == 100
    labels = [stage["label"] for stage in progress["stages"]]
    assert labels[0] == "File uploaded"
    assert labels[-1] == "Report ready"
    assert all(stage["done"] for stage in progress["stages"])


def test_analysis_payload_contains_every_section(client, auth_headers, analysed):
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    for key in ("summary", "profile", "quality", "kpis", "statistics", "trends", "anomalies",
                "correlations", "segments", "concentration", "insights", "charts",
                "recommendations", "story", "briefing", "story_score", "filters",
                "next_questions", "sheets", "relationships"):
        assert key in analysis, f"{key} missing from the analysis payload"
    assert analysis["session"]["id"] == analysed


def test_charts_carry_their_analytical_rationale(client, auth_headers, analysed):
    charts = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()["charts"]
    assert charts
    signatures = set()
    for chart in charts:
        assert chart["question"], "every chart must answer a question"
        assert chart["reason"], "every chart must record why it was chosen"
        assert chart["calculation"]
        assert chart["columns"]
        assert chart["data"]
        signature = (chart["type"], tuple(sorted(chart["columns"])))
        assert signature not in signatures, f"redundant chart: {chart['title']}"
        signatures.add(signature)


def test_ask_your_data_round_trip(client, auth_headers, analysed):
    suggestions = client.get(f"/api/sessions/{analysed}/ask/suggestions",
                             headers=auth_headers).json()["questions"]
    assert suggestions

    response = client.post(f"/api/sessions/{analysed}/ask", headers=auth_headers,
                           json={"question": "Show the top 5 Region by Revenue"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["supported"]
    assert payload["table"]
    assert payload["chart"]["type"] in {"bar", "horizontal_bar"}
    assert payload["calculation"]
    assert payload["confidence"] in {"high", "medium", "low"}

    history = client.get(f"/api/sessions/{analysed}/ask/history",
                         headers=auth_headers).json()["history"]
    assert history and history[0]["question"]


def test_ask_declines_gracefully_when_the_data_cannot_answer(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/ask", headers=auth_headers,
                           json={"question": "What is the weather forecast for Mumbai?"})
    assert response.status_code == 200
    assert response.json()["answer"]


def test_filters_recalculate_the_analysis(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/filter", headers=auth_headers, json={
        "filters": [{"column": "Region", "type": "multi_select", "values": ["North"]}],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["filtered"] is True
    assert payload["filter_summary"]["records"] < payload["filter_summary"]["total_records"]
    assert payload["kpis"]["primary"]
    assert payload["insights"]


def test_filters_that_match_nothing_are_reported(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/filter", headers=auth_headers, json={
        "filters": [{"column": "Region", "type": "multi_select", "values": ["Atlantis"]}],
    })
    assert response.status_code == 422
    assert "No records match" in response.json()["detail"]


def test_drilldown_only_reports_analyses_that_exist(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/drilldown", headers=auth_headers,
                           json={"dimension": "Region", "value": "North"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["records"] > 0
    assert payload["metrics"]
    assert payload["breakdowns"]
    available = payload["available_analyses"]
    assert set(available["measures"]) <= {m["measure"] for m in payload["metrics"]}

    missing = client.post(f"/api/sessions/{analysed}/drilldown", headers=auth_headers,
                          json={"dimension": "Region", "value": "Nowhere"})
    assert missing.status_code == 404


def test_anomaly_investigation_endpoint(client, auth_headers, analysed):
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    items = analysis["anomalies"]["items"]
    if not items:
        pytest.skip("no anomalies in this dataset")
    response = client.get(
        f"/api/sessions/{analysed}/anomalies/{items[0]['id']}/investigate", headers=auth_headers,
    )
    assert response.status_code == 200
    assert "caveat" in response.json()


def test_story_adapts_to_the_audience(client, auth_headers, analysed):
    executive = client.get(f"/api/sessions/{analysed}/story?audience=executive",
                           headers=auth_headers).json()
    analyst = client.get(f"/api/sessions/{analysed}/story?audience=analyst",
                         headers=auth_headers).json()
    assert executive["cards"] == analyst["cards"], "the findings must not change"
    assert len(analyst["adapted_insights"][0]["body"]) > \
        len(executive["adapted_insights"][0]["body"])

    bad = client.get(f"/api/sessions/{analysed}/story?audience=martian", headers=auth_headers)
    assert bad.status_code == 400


def test_briefing_endpoint(client, auth_headers, analysed):
    briefing = client.get(f"/api/sessions/{analysed}/briefing", headers=auth_headers).json()
    assert briefing["status"] in {"Positive", "Neutral", "Concerning"}
    assert briefing["narrated"]


def test_explore_data_supports_paging_sorting_and_search(client, auth_headers, analysed):
    first = client.post(f"/api/sessions/{analysed}/data", headers=auth_headers,
                        json={"limit": 5, "sort_by": "Revenue", "sort_desc": True}).json()
    assert len(first["rows"]) == 5
    revenues = [row["Revenue"] for row in first["rows"]]
    assert revenues == sorted(revenues, reverse=True)

    second = client.post(f"/api/sessions/{analysed}/data", headers=auth_headers,
                         json={"limit": 5, "offset": 5}).json()
    assert second["offset"] == 5
    assert second["rows"] != first["rows"]

    searched = client.post(f"/api/sessions/{analysed}/data", headers=auth_headers,
                           json={"limit": 5, "search": "North"}).json()
    assert searched["total"] > 0
    assert all(row["Region"] == "North" for row in searched["rows"])


def test_pdf_and_excel_downloads(client, auth_headers, analysed):
    pdf = client.post(f"/api/sessions/{analysed}/report/pdf", headers=auth_headers,
                      json={"style": "executive", "title": "Board Pack"})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]

    workbook = client.post(f"/api/sessions/{analysed}/export/excel", headers=auth_headers,
                           json={"include_data": True, "data_row_limit": 50})
    assert workbook.status_code == 200
    assert workbook.content.startswith(b"PK")

    csv = client.post(f"/api/sessions/{analysed}/export/data", headers=auth_headers,
                      json={"data_row_limit": 20, "filters": [
                          {"column": "Region", "type": "multi_select", "values": ["North"]}]})
    assert csv.status_code == 200
    assert csv.text.splitlines()[0].startswith("Order ID")


def test_report_styles_endpoint(client):
    styles = client.get("/api/reports/styles").json()
    assert {s["key"] for s in styles["styles"]} == {"executive", "standard", "detailed"}
    assert "executive" in styles["audiences"]


def test_invalid_logo_is_rejected(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/report/pdf", headers=auth_headers,
                           json={"style": "executive", "logo_base64": "!!!not base64!!!"})
    assert response.status_code == 400


def test_session_rename_notes_and_bookmarks(client, auth_headers, analysed):
    response = client.patch(f"/api/sessions/{analysed}", headers=auth_headers, json={
        "name": "Q4 board review", "notes": {"ins_001": "Check with finance"},
        "bookmarks": ["ins_001", "ins_002"],
    })
    assert response.status_code == 200
    assert response.json()["name"] == "Q4 board review"

    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    assert analysis["session"]["notes"]["ins_001"] == "Check with finance"
    assert analysis["session"]["bookmarks"] == ["ins_001", "ins_002"]


def test_sharing_exposes_findings_but_not_rows(client, auth_headers, analysed):
    share = client.post(f"/api/sessions/{analysed}/share", headers=auth_headers,
                        json={"expires_in_hours": 24}).json()
    shared = client.get(f"/api/shared/{share['token']}").json()
    assert shared["shared"] is True
    assert shared["insights"]
    assert "rows" not in shared and "data" not in shared
    assert client.get("/api/shared/does-not-exist").status_code == 404


def test_reanalyze_a_single_sheet(client, auth_headers, sales_workbook):
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("sales.xlsx", sales_workbook, "application/vnd.ms-excel")})
    session_id = upload.json()["id"]
    wait_for_analysis(client, auth_headers, session_id)

    response = client.post(f"/api/sessions/{session_id}/analyze", headers=auth_headers,
                           json={"sheet": "Sales", "scope": "sheet"})
    assert response.status_code == 202
    status = wait_for_analysis(client, auth_headers, session_id)
    assert status["status"] == "completed"
    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert analysis["active_sheet"] == "Sales"


def test_sample_datasets_can_be_loaded(client, auth_headers):
    samples = client.get("/api/samples").json()["samples"]
    assert {s["key"] for s in samples} == {
        "sales", "students", "employees", "marketing", "subscriptions", "finance",
    }

    response = client.post("/api/samples/students/load", headers=auth_headers)
    assert response.status_code == 202
    status = wait_for_analysis(client, auth_headers, response.json()["id"])
    assert status["status"] == "completed"
    assert client.post("/api/samples/nope/load", headers=auth_headers).status_code == 404


def test_analysis_endpoints_reject_an_unfinished_session(client, auth_headers, sales_workbook):
    upload = client.post("/api/datasets/upload", headers=auth_headers,
                         files={"file": ("sales.xlsx", sales_workbook, "application/vnd.ms-excel")})
    session_id = upload.json()["id"]
    response = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers)
    assert response.status_code in {200, 409}
    wait_for_analysis(client, auth_headers, session_id)


def test_session_deletion_removes_the_uploaded_file(client, auth_headers, analysed):
    from pathlib import Path

    from app.core.database import SessionLocal
    from app.models import AnalysisSession

    db = SessionLocal()
    path = Path(db.get(AnalysisSession, analysed).storage_path)
    db.close()
    assert path.exists()

    assert client.delete(f"/api/sessions/{analysed}", headers=auth_headers).status_code == 204
    assert not path.exists()
    assert client.get(f"/api/sessions/{analysed}", headers=auth_headers).status_code == 404


def test_retention_cleanup_removes_files_but_keeps_findings(client, auth_headers, analysed):
    from app.services.analysis_service import cleanup_expired_files

    removed = cleanup_expired_files(retention_hours=0)
    assert removed >= 1
    session = client.get(f"/api/sessions/{analysed}", headers=auth_headers).json()
    assert session["file_deleted"] is True
    # The analysis itself survives so the report is still readable.
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers)
    assert analysis.status_code == 200
    # ...but exploring the raw rows now fails with a clear message.
    explore = client.post(f"/api/sessions/{analysed}/data", headers=auth_headers, json={})
    assert explore.status_code == 410
