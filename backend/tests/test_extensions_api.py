"""The new endpoints, driven the way a user drives them.

Covers column overrides, propose-and-confirm cleaning, cross-sheet joins,
dataset comparison, insight feedback, forecasts and result retention -
including the isolation and refusal behaviour each one has to hold.
"""
from __future__ import annotations

import io
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


def wait_for_analysis(client, headers, session_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}/status", headers=headers).json()
        if status["status"] in {"completed", "failed"}:
            assert status["status"] == "completed", status.get("error")
            return status
        time.sleep(0.3)
    raise AssertionError("analysis did not finish in time")


def upload(client, headers, content, filename="data.xlsx"):
    response = client.post("/api/datasets/upload", headers=headers,
                           files={"file": (filename, content, "application/vnd.ms-excel")})
    assert response.status_code == 202, response.text
    session_id = response.json()["id"]
    wait_for_analysis(client, headers, session_id)
    return session_id


@pytest.fixture
def analysed(client, auth_headers, sales_workbook):
    return upload(client, auth_headers, sales_workbook, "sales.xlsx")


@pytest.fixture(scope="session")
def messy_workbook() -> bytes:
    frame = pd.DataFrame({
        "Cust ID": ["C001", "C002", "C003", "C003", "C005", None, "C007", "C008"] * 6,
        "Region": ["North", "north", " North ", "South", "SOUTH", "East", None, "East"] * 6,
        "Amount": ["1200", "2400", "not a number", "900", "1100", "5600", "700", "800"] * 6,
        "Joined": ["2024-01-15", "2024-02-20", "bad date", "2024-04-02",
                   "2024-05-11", "2024-06-30", "2024-07-04", "2024-08-19"] * 6,
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        frame.to_excel(writer, sheet_name="Messy", index=False)
    return buffer.getvalue()


@pytest.fixture(scope="session")
def two_sheet_workbook() -> bytes:
    rng = np.random.default_rng(3)
    orders = pd.DataFrame({
        "Order ID": [f"O{i:04d}" for i in range(300)],
        "Customer ID": [f"C{rng.integers(1, 41):03d}" for _ in range(300)],
        "Order Date": pd.date_range("2024-01-01", periods=300, freq="D"),
        "Revenue": rng.normal(1000, 200, 300).round(2),
    })
    customers = pd.DataFrame({
        "Customer ID": [f"C{i:03d}" for i in range(1, 41)],
        "Segment": rng.choice(["Enterprise", "SMB", "Consumer"], 40),
        "Country": rng.choice(["India", "UK", "US"], 40),
        "Credit Limit": rng.integers(1000, 90000, 40),
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        orders.to_excel(writer, sheet_name="Orders", index=False)
        customers.to_excel(writer, sheet_name="Customers", index=False)
    return buffer.getvalue()


# --- column classification --------------------------------------------------

def test_columns_endpoint_offers_only_supportable_classifications(client, auth_headers, analysed):
    response = client.get(f"/api/sessions/{analysed}/columns", headers=auth_headers)
    assert response.status_code == 200
    columns = {c["name"]: c for c in response.json()["columns"]}
    assert "measure" in columns["Revenue"]["options"]["roles"]
    assert "measure" not in columns["Region"]["options"]["roles"]
    assert columns["Region"]["options"]["blocked"]


def test_a_correction_re_runs_the_analysis_and_changes_the_numbers(client, auth_headers,
                                                                   analysed):
    before = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    units_before = next(c for c in before["profile"]["columns"] if c["name"] == "Units")
    assert units_before["aggregation"] == "sum"

    response = client.post(f"/api/sessions/{analysed}/columns", headers=auth_headers,
                           json={"overrides": {"Units": {"aggregation": "mean"}}})
    assert response.status_code == 202, response.text
    wait_for_analysis(client, auth_headers, analysed)

    after = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    units_after = next(c for c in after["profile"]["columns"] if c["name"] == "Units")
    assert units_after["aggregation"] == "mean"
    assert units_after["overridden"] == ["aggregation"]


def test_an_impossible_correction_is_refused(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/columns", headers=auth_headers,
                           json={"overrides": {"Region": {"role": "measure"}}})
    assert response.status_code == 422
    assert "cannot be used as a measure" in response.json()["detail"]


def test_clearing_a_correction_restores_the_inferred_classification(client, auth_headers,
                                                                    analysed):
    client.post(f"/api/sessions/{analysed}/columns", headers=auth_headers,
                json={"overrides": {"Units": {"aggregation": "mean"}}})
    wait_for_analysis(client, auth_headers, analysed)
    client.post(f"/api/sessions/{analysed}/columns", headers=auth_headers,
                json={"overrides": {}})
    wait_for_analysis(client, auth_headers, analysed)
    result = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    units = next(c for c in result["profile"]["columns"] if c["name"] == "Units")
    assert units["aggregation"] == "sum"
    assert units.get("overridden", []) == []


# --- quality fixes ----------------------------------------------------------

def test_fixes_are_proposed_but_not_applied(client, auth_headers, messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    response = client.get(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["proposals"]
    assert all(p["accepted"] is False for p in body["proposals"])
    assert body["applied"] == []
    assert "never modified" in body["policy"]


def test_previewing_a_fix_changes_nothing(client, auth_headers, messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    proposals = client.get(f"/api/sessions/{session_id}/quality/fixes",
                           headers=auth_headers).json()["proposals"]
    before = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()

    preview = client.post(f"/api/sessions/{session_id}/quality/fixes/preview",
                          headers=auth_headers, json={"fixes": proposals})
    assert preview.status_code == 200
    assert preview.json()["applied_count"] == len(proposals)

    after = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert after["quality"]["score"] == before["quality"]["score"]
    assert after["profile"]["row_count"] == before["profile"]["row_count"]


def test_accepting_fixes_cleans_the_analysis_and_records_an_audit(client, auth_headers,
                                                                  messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    proposals = client.get(f"/api/sessions/{session_id}/quality/fixes",
                           headers=auth_headers).json()["proposals"]
    before = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()

    response = client.post(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers,
                           json={"fixes": proposals})
    assert response.status_code == 202, response.text
    wait_for_analysis(client, auth_headers, session_id)

    after = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert after["quality"]["score"] > before["quality"]["score"]
    assert after["cleaning"]["applied_count"] == len(proposals)
    assert "uploaded file itself is unchanged" in after["cleaning"]["statement"]


def test_exploring_rows_shows_the_same_table_the_numbers_came_from(client, auth_headers,
                                                                   messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    proposals = client.get(f"/api/sessions/{session_id}/quality/fixes",
                           headers=auth_headers).json()["proposals"]
    client.post(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers,
                json={"fixes": proposals})
    wait_for_analysis(client, auth_headers, session_id)

    analysis = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    rows = client.post(f"/api/sessions/{session_id}/data", headers=auth_headers,
                       json={"limit": 5}).json()
    assert rows["total"] == analysis["profile"]["row_count"]


def test_removing_the_fixes_restores_the_original_analysis(client, auth_headers, messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    original = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    proposals = client.get(f"/api/sessions/{session_id}/quality/fixes",
                           headers=auth_headers).json()["proposals"]

    client.post(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers,
                json={"fixes": proposals})
    wait_for_analysis(client, auth_headers, session_id)
    client.post(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers,
                json={"fixes": []})
    wait_for_analysis(client, auth_headers, session_id)

    restored = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert restored["profile"]["row_count"] == original["profile"]["row_count"]
    assert restored["quality"]["score"] == original["quality"]["score"]


def test_an_unknown_fix_type_is_rejected(client, auth_headers, messy_workbook):
    session_id = upload(client, auth_headers, messy_workbook, "messy.xlsx")
    response = client.post(f"/api/sessions/{session_id}/quality/fixes", headers=auth_headers,
                           json={"fixes": [{"id": "x", "type": "drop_all", "column": "Region"}]})
    assert response.status_code == 422


# --- joins ------------------------------------------------------------------

def test_relationships_are_detected_and_previewable(client, auth_headers, two_sheet_workbook):
    session_id = upload(client, auth_headers, two_sheet_workbook, "biz.xlsx")
    detected = client.get(f"/api/sessions/{session_id}/joins", headers=auth_headers).json()
    assert detected["relationships"]
    assert set(detected["sheets"]) == {"Orders", "Customers"}

    preview = client.post(f"/api/sessions/{session_id}/joins/preview", headers=auth_headers,
                          json={"left": "Orders", "right": "Customers",
                                "key": "Customer ID", "how": "inner"})
    assert preview.status_code == 200
    body = preview.json()
    assert body["cardinality"] == "many-to-one"
    assert body["estimated_rows"] == 300
    assert body["safe"] is True
    assert body["duplicated_columns"]


def test_a_join_produces_a_new_analysis_and_leaves_the_original_alone(client, auth_headers,
                                                                      two_sheet_workbook):
    session_id = upload(client, auth_headers, two_sheet_workbook, "biz.xlsx")
    original = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()

    response = client.post(f"/api/sessions/{session_id}/joins", headers=auth_headers,
                           json={"left": "Orders", "right": "Customers",
                                 "key": "Customer ID", "how": "inner"})
    assert response.status_code == 202, response.text
    joined_id = response.json()["id"]
    assert joined_id != session_id
    wait_for_analysis(client, auth_headers, joined_id)

    joined = client.get(f"/api/sessions/{joined_id}/analysis", headers=auth_headers).json()
    assert joined["scope"] == "join"
    assert "Segment" in joined["profile"]["roles"]["dimension"]
    assert joined["join"]["rows_result"] == 300

    unchanged = client.get(f"/api/sessions/{session_id}/analysis", headers=auth_headers).json()
    assert unchanged["profile"]["column_count"] == original["profile"]["column_count"]


def test_a_joined_attribute_is_never_summed_or_trended(client, auth_headers, two_sheet_workbook):
    """A credit limit repeated across orders totals to how often the customer ordered."""
    session_id = upload(client, auth_headers, two_sheet_workbook, "biz.xlsx")
    joined_id = client.post(f"/api/sessions/{session_id}/joins", headers=auth_headers,
                            json={"left": "Orders", "right": "Customers",
                                  "key": "Customer ID", "how": "inner"}).json()["id"]
    wait_for_analysis(client, auth_headers, joined_id)
    joined = client.get(f"/api/sessions/{joined_id}/analysis", headers=auth_headers).json()

    credit = next(c for c in joined["profile"]["columns"] if c["name"] == "Credit Limit")
    assert credit["aggregation"] == "mean"
    assert credit["additive"] is False
    assert "Credit Limit" not in [t["measure"] for t in joined["trends"]]


def test_a_join_that_would_multiply_rows_is_refused(client, auth_headers):
    frame_a = pd.DataFrame({"Key": ["x"] * 60 + ["y"] * 60, "Value": range(120)})
    frame_b = pd.DataFrame({"Key": ["x"] * 50 + ["y"] * 50, "Other": range(100)})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        frame_a.to_excel(writer, sheet_name="A", index=False)
        frame_b.to_excel(writer, sheet_name="B", index=False)
    session_id = upload(client, auth_headers, buffer.getvalue(), "fanout.xlsx")
    spec = {"left": "A", "right": "B", "key": "Key", "how": "inner"}

    # A preview explains the danger rather than hiding it...
    preview = client.post(f"/api/sessions/{session_id}/joins/preview", headers=auth_headers,
                          json=spec).json()
    assert preview["cardinality"] == "many-to-many"
    assert preview["safe"] is False
    assert any("inflated" in w for w in preview["warnings"])

    # ...but nothing will actually analyse the result.
    response = client.post(f"/api/sessions/{session_id}/joins", headers=auth_headers, json=spec)
    assert response.status_code == 422
    assert "overstated" in response.json()["detail"]


def test_joining_sheets_with_no_shared_values_is_refused(client, auth_headers):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        pd.DataFrame({"Key": [f"a{i}" for i in range(30)],
                      "V": range(30)}).to_excel(writer, sheet_name="A", index=False)
        pd.DataFrame({"Key": [f"b{i}" for i in range(30)],
                      "W": range(30)}).to_excel(writer, sheet_name="B", index=False)
    session_id = upload(client, auth_headers, buffer.getvalue(), "disjoint.xlsx")
    response = client.post(f"/api/sessions/{session_id}/joins/preview", headers=auth_headers,
                           json={"left": "A", "right": "B", "key": "Key", "how": "inner"})
    assert response.status_code == 422
    assert "share no" in response.json()["detail"]


# --- comparison -------------------------------------------------------------

def test_a_second_upload_is_offered_as_comparable(client, auth_headers, sales_workbook):
    first = upload(client, auth_headers, sales_workbook, "sales-march.xlsx")
    second = upload(client, auth_headers, sales_workbook, "sales-august.xlsx")

    response = client.get(f"/api/sessions/{second}/comparable", headers=auth_headers)
    assert response.status_code == 200
    comparable = response.json()["comparable"]
    assert any(row["id"] == first for row in comparable)
    match = next(row for row in comparable if row["id"] == first)
    assert match["identical_shape"] is True
    assert match["same_file"] is True


def test_comparing_two_analyses_reports_what_moved(client, auth_headers, sales_workbook,
                                                   messy_workbook):
    first = upload(client, auth_headers, sales_workbook, "sales-a.xlsx")
    second = upload(client, auth_headers, sales_workbook, "sales-b.xlsx")

    response = client.get(f"/api/sessions/{second}/compare/{first}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["comparable_pct"] == pytest.approx(100.0)
    assert body["headline"]
    assert body["coverage"]["rows_delta"] == 0
    assert body["insights"]["counts"]["new"] == 0


def test_an_unrelated_dataset_is_not_offered_for_comparison(client, auth_headers,
                                                            sales_workbook, messy_workbook):
    upload(client, auth_headers, messy_workbook, "messy.xlsx")
    sales = upload(client, auth_headers, sales_workbook, "sales.xlsx")
    comparable = client.get(f"/api/sessions/{sales}/comparable",
                            headers=auth_headers).json()["comparable"]
    assert all(row["comparable_pct"] >= 40 for row in comparable)


def test_an_analysis_cannot_be_compared_with_itself(client, auth_headers, analysed):
    response = client.get(f"/api/sessions/{analysed}/compare/{analysed}", headers=auth_headers)
    assert response.status_code == 400


def test_another_users_analysis_cannot_be_compared(client, auth_headers, analysed,
                                                   sales_workbook):
    other = client.post("/api/auth/register", json={
        "email": "intruder@example.com", "password": "An0therStr0ng!", "full_name": "Other",
    })
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    theirs = upload(client, other_headers, sales_workbook, "theirs.xlsx")

    response = client.get(f"/api/sessions/{theirs}/compare/{analysed}", headers=other_headers)
    assert response.status_code == 404


# --- feedback ---------------------------------------------------------------

def test_rating_a_finding_reorders_without_rewriting(client, auth_headers, analysed):
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    target = analysis["insights"][-1]

    response = client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                           json={"insight_id": target["id"], "vote": "useful"})
    assert response.status_code == 200
    ranked = {i["id"]: i for i in response.json()["insights"]}
    assert ranked[target["id"]]["headline"] == target["headline"]
    assert ranked[target["id"]]["priority"]["feedback_adjustment"] > 0

    served = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    moved = next(i for i in served["insights"] if i["id"] == target["id"])
    assert moved["your_vote"] == "useful"
    assert served["feedback"]["votes"]["useful"] == 1


def test_a_vote_can_be_cleared(client, auth_headers, analysed):
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    target = analysis["insights"][0]
    client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                json={"insight_id": target["id"], "vote": "not_useful"})
    client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                json={"insight_id": target["id"], "vote": "clear"})
    summary = client.get(f"/api/sessions/{analysed}/feedback", headers=auth_headers).json()
    assert summary["votes"]["total"] == 0


def test_rating_an_unknown_finding_is_rejected(client, auth_headers, analysed):
    response = client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                           json={"insight_id": "ins_999", "vote": "useful"})
    assert response.status_code == 404


def test_one_users_ratings_never_affect_another(client, auth_headers, analysed, sales_workbook):
    analysis = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    for insight in analysis["insights"][:4]:
        client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                    json={"insight_id": insight["id"], "vote": "not_useful"})

    other = client.post("/api/auth/register", json={
        "email": "second@example.com", "password": "An0therStr0ng!", "full_name": "Second",
    })
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    theirs = upload(client, other_headers, sales_workbook, "theirs.xlsx")
    their_analysis = client.get(f"/api/sessions/{theirs}/analysis",
                                headers=other_headers).json()
    assert their_analysis["feedback"]["active"] is False
    assert their_analysis["feedback"]["votes"]["total"] == 0


def test_feedback_never_changes_a_reported_number(client, auth_headers, analysed):
    before = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    originals = {i["id"]: (i["headline"], i["evidence"], i["confidence"])
                 for i in before["insights"]}
    for insight in before["insights"][:5]:
        client.post(f"/api/sessions/{analysed}/feedback", headers=auth_headers,
                    json={"insight_id": insight["id"], "vote": "useful"})
    after = client.get(f"/api/sessions/{analysed}/analysis", headers=auth_headers).json()
    for insight in after["insights"]:
        assert originals[insight["id"]] == (
            insight["headline"], insight["evidence"], insight["confidence"]
        )


# --- forecasts --------------------------------------------------------------

def test_the_forecast_endpoint_separates_what_it_can_and_cannot_project(client, auth_headers,
                                                                        analysed):
    response = client.get(f"/api/sessions/{analysed}/forecast", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["forecasts"]
    assert all(f["measure"] for f in body["forecasts"])
    assert all(item["reason"] for item in body["unavailable"])
    assert "not a measurement" in body["policy"]
    for forecast in body["available"]:
        assert forecast["disclaimer"]
        assert all(p["projected"] for p in forecast["points"])


# --- retention --------------------------------------------------------------

def test_a_session_reports_when_its_analysis_expires(client, auth_headers, analysed, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "result_retention_days", 30)
    summary = client.get(f"/api/sessions/{analysed}", headers=auth_headers).json()
    assert summary["result_expires_at"] is not None
    expires = datetime.fromisoformat(summary["result_expires_at"])
    assert expires > datetime.now(timezone.utc)


def test_results_are_kept_indefinitely_by_default(client, auth_headers, analysed):
    summary = client.get(f"/api/sessions/{analysed}", headers=auth_headers).json()
    assert summary["result_expires_at"] is None


def test_the_retention_sweep_purges_an_expired_analysis(client, auth_headers, analysed):
    from app.core.database import SessionLocal
    from app.models import AnalysisSession
    from app.services.analysis_service import purge_expired_results

    assert purge_expired_results(0) == 0

    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, analysed)
        session.updated_at = datetime.now(timezone.utc) - timedelta(days=400)
        db.commit()
    finally:
        db.close()

    assert purge_expired_results(365) == 1
    assert client.get(f"/api/sessions/{analysed}", headers=auth_headers).status_code == 404


def test_a_recent_analysis_survives_the_sweep(client, auth_headers, analysed):
    from app.services.analysis_service import purge_expired_results

    assert purge_expired_results(1) == 0
    assert client.get(f"/api/sessions/{analysed}", headers=auth_headers).status_code == 200


def test_the_retention_policy_is_advertised(client):
    config = client.get("/api/system/config").json()
    assert "result_retention_days" in config
    assert "file_retention_hours" in config
