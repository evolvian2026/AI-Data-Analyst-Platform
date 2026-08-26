"""Dataset upload, analysis sessions and interactive exploration."""
from __future__ import annotations

import base64
import binascii
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession, owned_session, require_completed
from app.core.config import settings
from app.engines import ask as ask_engine
from app.engines import cleaning as cleaning_engine
from app.engines import comparison as comparison_engine
from app.engines import feedback as feedback_engine
from app.engines import narrative
from app.engines import profiler as P
from app.engines.anomaly import investigate_anomaly
from app.engines.excel_export import build_workbook
from app.engines.excel_parser import WorkbookError
from app.engines.formatting import format_value, is_text_column, jsonify, safe_float
from app.engines.orchestrator import analyze_dataframe, apply_filters
from app.engines.pdf_report import STYLE_PRESETS, generate_pdf
from app.engines.relationships import JoinError, describe_join, ensure_joinable
from app.engines.sanitize import escape_for_spreadsheet, neutralize_text, safe_filename
from app.models import AnalysisSession, InsightFeedback, QueryLog, SharedReport
from app.samples.generate import SAMPLES, build_all
from app.schemas import (
    AnalyzeRequest,
    AskRequest,
    CleaningRequest,
    ColumnOverrideRequest,
    DataQuery,
    DrilldownRequest,
    ExcelExportRequest,
    FeedbackRequest,
    FilterRequest,
    JoinRequest,
    ReportRequest,
    SessionSummary,
    SessionUpdate,
    ShareRequest,
)
from app.services import analysis_service

router = APIRouter(tags=["analysis"])

ALLOWED_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
MAX_FILENAME = 200


def _summary(session: AnalysisSession) -> SessionSummary:
    """Serialise a session, including when its analysis will be purged."""
    summary = SessionSummary.model_validate(session)
    summary.result_expires_at = analysis_service.result_expires_at(session)
    return summary


def _validate_upload(filename: str, content: bytes) -> None:
    suffix = Path(safe_filename(filename)).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{suffix or 'unknown'}'. Upload an .xlsx or .xls file.",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
        )
    # Magic-byte check: an .xlsx is a zip, a legacy .xls is an OLE2 container.
    if suffix in {".xlsx", ".xlsm"} and not content.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="The file is not a valid .xlsx workbook.")
    if suffix == ".xls" and not content.startswith(b"\xd0\xcf\x11\xe0"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="The file is not a valid .xls workbook.")


@router.post("/datasets/upload", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
async def upload_dataset(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    sheet: str | None = Form(default=None),
) -> SessionSummary:
    """Upload a workbook and start the analysis pipeline in the background."""
    content = await file.read()
    _validate_upload(file.filename or "upload.xlsx", content)
    session = analysis_service.create_session(
        db, user.id, file.filename or "upload.xlsx", content,
        name=neutralize_text(name, MAX_FILENAME) if name else None,
    )
    analysis_service.schedule_analysis(session.id, sheet)
    return _summary(session)


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(user: CurrentUser, db: DbSession,
                  limit: int = Query(default=50, ge=1, le=200)) -> list[SessionSummary]:
    sessions = (
        db.query(AnalysisSession)
        .filter(AnalysisSession.user_id == user.id)
        .order_by(AnalysisSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_summary(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionSummary)
def get_session(session_id: str, user: CurrentUser, db: DbSession) -> SessionSummary:
    return _summary(owned_session(session_id, user, db))


@router.get("/sessions/{session_id}/status")
def get_status(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    session = owned_session(session_id, user, db)
    return {
        "id": session.id, "status": session.status, "error": session.error,
        "progress": session.progress or {},
        "sheets": (session.workbook_meta or {}).get("sheets", []),
    }


def _feedback_state(db: DbSession, user_id: str, session_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    """This user's ratings: bounded ranking adjustments, and their own votes.

    Ratings from *every* session this user has rated feed the adjustment, which
    is the point - a preference learned on last month's upload should apply to
    this month's. Only the current session's votes are echoed back for the UI.
    """
    rows = (
        db.query(InsightFeedback)
        .filter(InsightFeedback.user_id == user_id)
        .order_by(InsightFeedback.created_at.desc())
        .limit(2000)
        .all()
    )
    adjustments = feedback_engine.build_adjustments(
        [(r.signature, r.insight_type, r.vote) for r in rows]
    )
    voted = {r.insight_id: r.vote for r in rows if r.session_id == session_id}
    return adjustments, voted


@router.get("/sessions/{session_id}/analysis")
def get_analysis(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    session = require_completed(owned_session(session_id, user, db))
    result = dict(session.result)
    adjustments, voted = _feedback_state(db, user.id, session.id)
    if result.get("insights"):
        result["insights"] = feedback_engine.apply(result["insights"], adjustments, voted)
        result["top_insights"] = result["insights"][:5]
    result["feedback"] = feedback_engine.explain(adjustments)
    result["session"] = {
        "id": session.id, "name": session.name, "notes": session.notes or {},
        "bookmarks": session.bookmarks or [], "config": session.config or {},
        "file_deleted": session.file_deleted,
        "result_expires_at": analysis_service.result_expires_at(session),
    }
    return jsonify(result)


@router.post("/sessions/{session_id}/analyze", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
def reanalyze(session_id: str, payload: AnalyzeRequest, user: CurrentUser,
              db: DbSession) -> SessionSummary:
    """Re-run the pipeline against a different sheet or the whole workbook."""
    session = owned_session(session_id, user, db)
    if session.file_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The uploaded file has been removed by the retention policy. Upload it again.",
        )
    sheet = payload.sheet if payload.scope == "sheet" else None
    session.status = "pending"
    session.error = ""
    session.config = {**(session.config or {}), "sheet": sheet, "scope": payload.scope}
    db.commit()
    analysis_service.invalidate_cache(session.id)
    analysis_service.schedule_analysis(session.id, sheet)
    db.refresh(session)
    return _summary(session)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def update_session(session_id: str, payload: SessionUpdate, user: CurrentUser,
                   db: DbSession) -> SessionSummary:
    session = owned_session(session_id, user, db)
    if payload.name is not None:
        session.name = neutralize_text(payload.name, MAX_FILENAME) or session.name
    if payload.notes is not None:
        session.notes = {
            neutralize_text(k, 80): neutralize_text(v, 2000) for k, v in payload.notes.items()
        }
    if payload.bookmarks is not None:
        session.bookmarks = [neutralize_text(b, 80) for b in payload.bookmarks][:200]
    db.commit()
    db.refresh(session)
    return _summary(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, user: CurrentUser, db: DbSession) -> Response:
    session = owned_session(session_id, user, db)
    analysis_service.delete_session_file(session)
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- interactive analysis ---------------------------------------------------

def _filtered_frame(session: AnalysisSession, filters: list[Any]) -> pd.DataFrame:
    try:
        frame = analysis_service.load_dataframe(session)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except WorkbookError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    if filters:
        frame = apply_filters(frame, [f.to_engine() for f in filters])
    return frame


@router.post("/sessions/{session_id}/filter")
def filter_analysis(session_id: str, payload: FilterRequest, user: CurrentUser,
                    db: DbSession) -> dict[str, Any]:
    """Recalculate the whole analysis against a filtered subset."""
    session = require_completed(owned_session(session_id, user, db))
    frame = _filtered_frame(session, payload.filters)
    if frame.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No records match those filters.")
    result = analyze_dataframe(frame, session.workbook_meta or {})
    result = jsonify(result)
    result["filtered"] = True
    result["filter_summary"] = {
        "records": int(len(frame)),
        "total_records": session.result["profile"]["row_count"],
        "pct_of_total": round(
            len(frame) / max(session.result["profile"]["row_count"], 1) * 100, 2
        ),
        "filters": [f.to_engine() for f in payload.filters],
    }
    return result


@router.post("/sessions/{session_id}/drilldown")
def drilldown(session_id: str, payload: DrilldownRequest, user: CurrentUser,
              db: DbSession) -> dict[str, Any]:
    """Explain one value of one dimension, using only the columns that exist."""
    session = require_completed(owned_session(session_id, user, db))
    analysis = session.result
    profile = analysis["profile"]
    columns = {c["name"]: c for c in profile["columns"]}
    if payload.dimension not in columns:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Column '{payload.dimension}' is not in this dataset.")

    frame = _filtered_frame(session, payload.filters)
    subset = frame[frame[payload.dimension].astype(str) == str(payload.value)]
    if subset.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No records have {payload.dimension} = {payload.value}.",
        )

    currency = profile.get("currency_symbol", "")
    # Lead with the measure the KPI engine ranked most relevant, or the one the
    # caller asked for - not simply the leftmost numeric column.
    ranked = analysis.get("ranked_measures") or []
    measures = sorted(
        (c for c in profile["columns"] if c["role"] == P.MEASURE),
        key=lambda column: (
            0 if column["name"] == payload.measure
            else ranked.index(column["name"]) + 1 if column["name"] in ranked
            else len(ranked) + 1
        ),
    )
    time_column = analysis.get("time_column")
    other_dimensions = [
        c["name"] for c in profile["columns"]
        if c["role"] == P.DIMENSION and c["name"] != payload.dimension
    ][:4]
    identifiers = [c["name"] for c in profile["columns"] if c["role"] == P.IDENTIFIER_ROLE]

    metrics = []
    for column in measures[:8]:
        name = column["name"]
        aggregation = column.get("aggregation") or "sum"
        values = P.to_numeric_series(subset[name]).dropna()
        overall = P.to_numeric_series(frame[name]).dropna()
        if values.empty or overall.empty:
            continue
        value = float(values.sum()) if aggregation == "sum" else float(values.mean())
        total = float(overall.sum()) if aggregation == "sum" else float(overall.mean())
        metrics.append({
            "measure": name,
            "aggregation": aggregation,
            "value": safe_float(value),
            "formatted": format_value(value, column["semantic_type"], currency),
            "average": safe_float(values.mean()),
            "formatted_average": format_value(safe_float(values.mean()),
                                              column["semantic_type"], currency),
            "records": int(len(values)),
            "share_pct": (
                round(value / total * 100, 2)
                if aggregation == "sum" and total and column.get("non_negative", True) else None
            ),
            "vs_dataset_pct": (
                round((float(values.mean()) - float(overall.mean())) / abs(float(overall.mean())) * 100, 1)
                if float(overall.mean()) else None
            ),
        })

    breakdowns = []
    primary = metrics[0]["measure"] if metrics else None
    if primary:
        column = columns[primary]
        aggregation = column.get("aggregation") or "sum"
        for dimension in other_dimensions:
            values = P.to_numeric_series(subset[primary])
            grouped = pd.DataFrame(
                {"group": subset[dimension].astype("string"), "value": values}
            ).dropna().groupby("group")["value"]
            aggregated = grouped.sum() if aggregation == "sum" else grouped.mean()
            if aggregated.empty:
                continue
            aggregated = aggregated.sort_values(ascending=False).head(10)
            total = float(aggregated.sum())
            breakdowns.append({
                "dimension": dimension,
                "measure": primary,
                "rows": [
                    {"name": str(index), "value": safe_float(value),
                     "formatted": format_value(safe_float(value), column["semantic_type"], currency),
                     "share_pct": round(float(value) / total * 100, 2)
                     if aggregation == "sum" and total else None}
                    for index, value in aggregated.items()
                ],
            })

    trend_points = []
    if time_column and primary:
        from app.engines.trend import _label, build_series, choose_frequency

        freq, _unit = choose_frequency(P.to_datetime_series(subset[time_column]).dropna())
        series = build_series(subset, time_column, primary,
                              columns[primary].get("aggregation") or "sum", freq)
        trend_points = [
            {"name": _label(row.period, freq), "value": safe_float(row.value),
             "records": int(row.records)}
            for row in series.itertuples()
        ]

    top_records = []
    if identifiers and primary:
        key = identifiers[0]
        values = P.to_numeric_series(subset[primary])
        ordered = values.sort_values(ascending=False).head(10)
        top_records = [
            {"identifier": neutralize_text(subset.at[index, key], 60),
             "value": safe_float(value),
             "formatted": format_value(safe_float(value), columns[primary]["semantic_type"], currency)}
            for index, value in ordered.items()
        ]

    related_anomalies = [
        {"id": a["id"], "headline": a["headline"], "column": a["column"],
         "severity": a["severity"]}
        for a in analysis.get("anomalies", {}).get("items", [])
        if any(
            str(example.get(payload.dimension)) == str(payload.value)
            for example in (a.get("examples") or [])
        )
    ][:5]

    return jsonify({
        "dimension": payload.dimension,
        "value": str(payload.value),
        "records": int(len(subset)),
        "share_of_records_pct": round(len(subset) / max(len(frame), 1) * 100, 2),
        "metrics": metrics,
        "breakdowns": breakdowns,
        "trend": {"points": trend_points, "measure": primary} if trend_points else None,
        "top_records": top_records,
        "related_anomalies": related_anomalies,
        "available_analyses": {
            "measures": [m["measure"] for m in metrics],
            "dimensions": other_dimensions,
            "time": bool(trend_points),
            "identifiers": identifiers[:1],
        },
    })


@router.post("/sessions/{session_id}/ask")
def ask(session_id: str, payload: AskRequest, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    session = require_completed(owned_session(session_id, user, db))
    frame = _filtered_frame(session, payload.filters)
    result = ask_engine.answer_question(payload.question, frame, session.result,
                                        context=payload.context)
    result = jsonify(result)
    db.add(QueryLog(session_id=session.id, user_id=user.id,
                    question=result["question"][:1000], intent=result["intent"],
                    answer={"answer": result["answer"][:4000],
                            "calculation": result.get("calculation", "")[:1000],
                            "interpretation": result.get("interpretation", "")[:500],
                            "follow_up": result.get("follow_up", False),
                            "context": result.get("context", {})}))
    db.commit()
    return result


@router.get("/sessions/{session_id}/ask/suggestions")
def ask_suggestions(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    session = require_completed(owned_session(session_id, user, db))
    return {"questions": ask_engine.suggested_questions(session.result)}


@router.get("/sessions/{session_id}/ask/history")
def ask_history(session_id: str, user: CurrentUser, db: DbSession,
                limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
    session = owned_session(session_id, user, db)
    logs = (
        db.query(QueryLog)
        .filter(QueryLog.session_id == session.id)
        .order_by(QueryLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "history": [
            {"id": log.id, "question": log.question, "intent": log.intent,
             "answer": log.answer, "created_at": log.created_at}
            for log in logs
        ]
    }


@router.get("/sessions/{session_id}/anomalies/{anomaly_id}/investigate")
def investigate(session_id: str, anomaly_id: str, user: CurrentUser,
                db: DbSession) -> dict[str, Any]:
    session = require_completed(owned_session(session_id, user, db))
    analysis = session.result
    anomaly = next(
        (a for a in analysis.get("anomalies", {}).get("items", []) if a["id"] == anomaly_id), None
    )
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found.")
    cached = next((i for i in analysis.get("investigations", [])
                   if i.get("anomaly_id") == anomaly_id), None)
    if cached:
        return jsonify({**cached, "anomaly": anomaly})
    frame = _filtered_frame(session, [])
    investigation = investigate_anomaly(frame, analysis["profile"], anomaly,
                                        analysis.get("time_column"))
    return jsonify({**investigation, "anomaly": anomaly})


@router.get("/sessions/{session_id}/story")
def story(session_id: str, user: CurrentUser, db: DbSession,
          audience: str = Query(default="manager")) -> dict[str, Any]:
    """The Data Story, with narration depth tuned to the chosen audience."""
    session = require_completed(owned_session(session_id, user, db))
    analysis = session.result
    if audience not in narrative.AUDIENCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown audience. Choose one of: {', '.join(narrative.AUDIENCES)}.",
        )
    adjustments, voted = _feedback_state(db, user.id, session.id)
    ranked = feedback_engine.apply(analysis["insights"], adjustments, voted)
    adapted = [narrative.adapt_for_audience(i, audience) for i in ranked]
    return jsonify({
        **analysis["story"],
        "audience": audience,
        "audience_config": narrative.AUDIENCES[audience],
        "audiences": narrative.AUDIENCES,
        "adapted_insights": adapted,
        "story_score": analysis.get("story_score", {}),
    })


@router.get("/sessions/{session_id}/briefing")
def briefing(session_id: str, user: CurrentUser, db: DbSession,
             audience: str = Query(default="executive")) -> dict[str, Any]:
    session = require_completed(owned_session(session_id, user, db))
    analysis = session.result
    result = dict(analysis.get("briefing", {}))
    result["audience"] = audience
    if audience in narrative.AUDIENCES:
        result["audience_config"] = narrative.AUDIENCES[audience]
        result["narrated"] = [
            narrative.adapt_for_audience(i, audience) for i in analysis["insights"][:8]
        ]
    return jsonify(result)


@router.post("/sessions/{session_id}/data")
def explore_data(session_id: str, payload: DataQuery, user: CurrentUser,
                 db: DbSession) -> dict[str, Any]:
    """Paged, filtered access to the underlying rows for the Explore Data tab."""
    session = require_completed(owned_session(session_id, user, db))
    frame = _filtered_frame(session, payload.filters)

    if payload.search:
        needle = payload.search.lower()
        mask = pd.Series(False, index=frame.index)
        for column in frame.columns:
            mask |= frame[column].astype("string").str.lower().str.contains(needle, na=False)
        frame = frame.loc[mask]

    if payload.sort_by and payload.sort_by in frame.columns:
        frame = frame.sort_values(payload.sort_by, ascending=not payload.sort_desc,
                                  kind="stable", na_position="last")

    columns = [c for c in (payload.columns or list(frame.columns)) if c in frame.columns]
    total = int(len(frame))
    page = frame.iloc[payload.offset: payload.offset + payload.limit][columns]
    records = []
    for _, row in page.iterrows():
        record = {}
        for column in columns:
            value = row[column]
            if pd.isna(value):
                record[column] = None
            elif isinstance(value, (pd.Timestamp,)):
                record[column] = value.isoformat()
            elif isinstance(value, str):
                record[column] = neutralize_text(value, 300)
            else:
                record[column] = safe_float(value) if not isinstance(value, (int, bool)) else value
        records.append(record)

    return jsonify({
        "columns": [
            {"name": c, **{k: v for k, v in
                           next((col for col in session.result["profile"]["columns"]
                                 if col["name"] == c), {}).items()
                           if k in {"semantic_type", "role", "aggregation"}}}
            for c in columns
        ],
        "rows": records,
        "total": total,
        "offset": payload.offset,
        "limit": payload.limit,
    })


# --- column classification --------------------------------------------------

@router.get("/sessions/{session_id}/columns")
def get_columns(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """What the profiler decided about each column, and what it may be changed to."""
    session = require_completed(owned_session(session_id, user, db))
    analysis = session.result
    overrides = (session.config or {}).get("column_overrides") or {}
    options = {o["column"]: o for o in analysis.get("column_options", [])}
    columns = []
    for column in analysis["profile"]["columns"]:
        option = options.get(column["name"], {})
        columns.append({
            "name": column["name"],
            "semantic_type": column["semantic_type"],
            "role": column["role"],
            "aggregation": column.get("aggregation"),
            "confidence": column.get("confidence"),
            "notes": column.get("notes", []),
            "sample_values": column.get("sample_values", []),
            "missing_pct": column.get("missing_pct"),
            "unique": column.get("unique"),
            "overridden": column.get("overridden", []),
            "options": {
                "roles": option.get("roles", []),
                "semantic_types": option.get("semantic_types", []),
                "aggregations": option.get("aggregations", []),
                "blocked": option.get("blocked", []),
            },
        })
    return jsonify({
        "columns": columns,
        "overrides": overrides,
        "note": (
            "Profiling infers a column's meaning from its values, which is right most of the "
            "time and not all of the time. A correction re-runs the whole analysis with the "
            "column treated your way; clearing it returns to the inferred classification. "
            "Only classifications the data can actually support are offered."
        ),
    })


@router.post("/sessions/{session_id}/columns", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
def set_columns(session_id: str, payload: ColumnOverrideRequest, user: CurrentUser,
                db: DbSession) -> SessionSummary:
    """Correct how columns are classified, then re-run the analysis."""
    session = require_completed(owned_session(session_id, user, db))
    if session.file_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The uploaded file has been removed by the retention policy, so the analysis "
                   "cannot be re-run. Upload the workbook again.",
        )
    overrides = {
        name: {k: v for k, v in override.model_dump().items() if v is not None}
        for name, override in payload.overrides.items()
    }
    overrides = {name: o for name, o in overrides.items() if o}
    errors = P.validate_overrides(overrides, session.result["profile"])
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=" ".join(errors[:4]))

    session.config = {**(session.config or {}), "column_overrides": overrides}
    if payload.reanalyze:
        session.status = "pending"
        session.error = ""
    db.commit()
    if payload.reanalyze:
        analysis_service.invalidate_cache(session.id)
        analysis_service.schedule_analysis(session.id, (session.config or {}).get("sheet"))
    db.refresh(session)
    return _summary(session)


# --- data quality: propose and confirm --------------------------------------

@router.get("/sessions/{session_id}/quality/fixes")
def get_quality_fixes(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Corrections this dataset would benefit from - proposed, never applied."""
    session = require_completed(owned_session(session_id, user, db))
    applied = (session.config or {}).get("cleaning") or []
    applied_ids = {step.get("id") for step in applied}
    proposals = session.result.get("cleaning_proposals", [])
    return jsonify({
        "proposals": [{**p, "accepted": p["id"] in applied_ids} for p in proposals],
        "applied": applied,
        "audit": session.result.get("cleaning"),
        "policy": (
            "Nothing is corrected automatically and the uploaded file is never modified. An "
            "accepted fix is stored as a recipe and replayed onto a copy of the data every time "
            "it is read, so removing it restores the original analysis exactly."
        ),
    })


@router.post("/sessions/{session_id}/quality/fixes", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
def set_quality_fixes(session_id: str, payload: CleaningRequest, user: CurrentUser,
                      db: DbSession) -> SessionSummary:
    """Accept a set of proposed fixes and re-run the analysis on cleaned data."""
    session = require_completed(owned_session(session_id, user, db))
    if session.file_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The uploaded file has been removed by the retention policy, so cleaning "
                   "cannot be applied. Upload the workbook again.",
        )
    recipe = [fix.model_dump() for fix in payload.fixes]
    errors = cleaning_engine.validate_recipe(recipe)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=" ".join(errors[:4]))

    session.config = {**(session.config or {}), "cleaning": recipe}
    if payload.reanalyze:
        session.status = "pending"
        session.error = ""
    db.commit()
    if payload.reanalyze:
        analysis_service.invalidate_cache(session.id)
        analysis_service.schedule_analysis(session.id, (session.config or {}).get("sheet"))
    db.refresh(session)
    return _summary(session)


@router.post("/sessions/{session_id}/quality/fixes/preview")
def preview_quality_fixes(session_id: str, payload: CleaningRequest, user: CurrentUser,
                          db: DbSession) -> dict[str, Any]:
    """Show exactly what a set of fixes would change, without accepting them."""
    session = require_completed(owned_session(session_id, user, db))
    recipe = [fix.model_dump() for fix in payload.fixes]
    errors = cleaning_engine.validate_recipe(recipe)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=" ".join(errors[:4]))
    # Deliberately loaded without the stored recipe so the preview describes the
    # effect of exactly the fixes in this request.
    frames = analysis_service.load_raw_frame(session)
    rows_before = int(len(frames))
    cleaned, audit = cleaning_engine.apply_recipe(frames, recipe)
    return jsonify(cleaning_engine.summarize(audit, rows_before, int(len(cleaned))))


# --- cross-sheet joins ------------------------------------------------------

@router.get("/sessions/{session_id}/joins")
def get_joins(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Detected relationships between the sheets of this workbook."""
    session = require_completed(owned_session(session_id, user, db))
    return jsonify({
        "relationships": session.result.get("relationships", []),
        "sheets": session.result.get("analyzable_sheets", []),
        "current_join": (session.config or {}).get("join"),
        "note": (
            "Joining sheets creates a new analysis so the originals are untouched. A join whose "
            "key repeats on both sides multiplies rows and inflates every total, so it is "
            "refused rather than analysed."
        ),
    })


@router.post("/sessions/{session_id}/joins/preview")
def preview_join(session_id: str, payload: JoinRequest, user: CurrentUser,
                 db: DbSession) -> dict[str, Any]:
    """Cost and losses of a join, computed without performing it."""
    session = require_completed(owned_session(session_id, user, db))
    frames = analysis_service.load_sheets(session)
    try:
        return jsonify(describe_join(frames, payload.left, payload.right, payload.key, payload.how))
    except JoinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc


@router.post("/sessions/{session_id}/joins", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
def create_join(session_id: str, payload: JoinRequest, user: CurrentUser,
                db: DbSession) -> SessionSummary:
    """Analyse two joined sheets as a new dataset, leaving this one untouched."""
    session = require_completed(owned_session(session_id, user, db))
    frames = analysis_service.load_sheets(session)
    try:
        # Validated here rather than only in the worker, so an impossible join
        # is refused with an explanation instead of becoming a failed session.
        ensure_joinable(
            describe_join(frames, payload.left, payload.right, payload.key, payload.how),
            max_rows=settings.max_rows_analyzed,
        )
    except JoinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc

    path = Path(session.storage_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The uploaded file has been removed by the retention policy. Upload it again "
                   "to join its sheets.",
        )
    joined = analysis_service.create_session(
        db, user.id, session.original_filename, path.read_bytes(),
        name=neutralize_text(payload.name, MAX_FILENAME) if payload.name
        else f"{payload.left} + {payload.right}",
    )
    joined.config = {
        **(joined.config or {}),
        "join": {"left": payload.left, "right": payload.right, "key": payload.key,
                 "how": payload.how},
        "joined_from": session.id,
    }
    db.commit()
    analysis_service.schedule_analysis(joined.id, None)
    db.refresh(joined)
    return _summary(joined)


# --- comparison with an earlier analysis ------------------------------------

@router.get("/sessions/{session_id}/comparable")
def comparable_sessions(session_id: str, user: CurrentUser, db: DbSession,
                        limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    """Earlier analyses of this user's that describe the same kind of dataset."""
    session = require_completed(owned_session(session_id, user, db))
    signature = comparison_engine.dataset_signature(session.result)
    candidates = (
        db.query(AnalysisSession)
        .filter(AnalysisSession.user_id == user.id,
                AnalysisSession.status == "completed",
                AnalysisSession.id != session.id)
        .order_by(AnalysisSession.created_at.desc())
        .limit(200)
        .all()
    )
    rows = []
    for candidate in candidates:
        overlap = comparison_engine.signature_overlap(
            signature, comparison_engine.dataset_signature(candidate.result)
        )
        if overlap < 40:
            continue
        rows.append({
            "id": candidate.id,
            "name": candidate.name,
            "original_filename": candidate.original_filename,
            "created_at": candidate.created_at,
            "rows": candidate.result.get("profile", {}).get("row_count", 0),
            "comparable_pct": round(overlap, 1),
            "identical_shape": overlap >= 99.9,
            "same_file": bool(candidate.checksum and candidate.checksum == session.checksum),
        })
    rows.sort(key=lambda r: (-r["comparable_pct"], r["created_at"]), reverse=False)
    rows.sort(key=lambda r: -r["comparable_pct"])
    return jsonify({
        "comparable": rows[:limit],
        "note": (
            "Two analyses are comparable when they describe the same columns playing the same "
            "analytical roles - not merely when they came from the same filename."
        ),
    })


@router.get("/sessions/{session_id}/compare/{previous_id}")
def compare_sessions(session_id: str, previous_id: str, user: CurrentUser,
                     db: DbSession) -> dict[str, Any]:
    """What changed between an earlier analysis and this one."""
    current = require_completed(owned_session(session_id, user, db))
    previous = require_completed(owned_session(previous_id, user, db))
    if current.id == previous.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="An analysis cannot be compared with itself.")
    comparison = comparison_engine.compare_analyses(
        previous.result, current.result,
        previous_label=previous.name, current_label=current.name,
    )
    return jsonify({
        **comparison,
        "previous": {"id": previous.id, "name": previous.name,
                     "created_at": previous.created_at},
        "current": {"id": current.id, "name": current.name, "created_at": current.created_at},
    })


# --- insight feedback -------------------------------------------------------

@router.post("/sessions/{session_id}/feedback")
def rate_insight(session_id: str, payload: FeedbackRequest, user: CurrentUser,
                 db: DbSession) -> dict[str, Any]:
    """Mark a finding useful or not, which nudges the ordering of future ones."""
    session = require_completed(owned_session(session_id, user, db))
    insight = next(
        (i for i in session.result.get("insights", []) if i["id"] == payload.insight_id), None
    )
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found.")

    existing = (
        db.query(InsightFeedback)
        .filter(InsightFeedback.user_id == user.id,
                InsightFeedback.session_id == session.id,
                InsightFeedback.insight_id == payload.insight_id)
        .first()
    )
    if payload.vote == "clear":
        if existing:
            db.delete(existing)
            db.commit()
    else:
        if existing:
            existing.vote = payload.vote
            existing.comment = neutralize_text(payload.comment, 1000)
        else:
            db.add(InsightFeedback(
                session_id=session.id, user_id=user.id, insight_id=payload.insight_id,
                signature=feedback_engine.signature(insight)[:400],
                insight_type=insight.get("type", ""),
                headline=insight.get("headline", "")[:2000],
                vote=payload.vote, comment=neutralize_text(payload.comment, 1000),
            ))
        db.commit()

    adjustments, voted = _feedback_state(db, user.id, session.id)
    ranked = feedback_engine.apply(session.result.get("insights", []), adjustments, voted)
    return jsonify({
        "recorded": payload.vote,
        "insight_id": payload.insight_id,
        "feedback": feedback_engine.explain(adjustments),
        "insights": ranked,
    })


@router.get("/sessions/{session_id}/feedback")
def feedback_summary(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    session = owned_session(session_id, user, db)
    adjustments, voted = _feedback_state(db, user.id, session.id)
    rows = (
        db.query(InsightFeedback)
        .filter(InsightFeedback.user_id == user.id)
        .order_by(InsightFeedback.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify({
        **feedback_engine.explain(adjustments),
        "your_votes": voted,
        "history": [
            {"insight_id": r.insight_id, "session_id": r.session_id, "vote": r.vote,
             "headline": r.headline, "type": r.insight_type, "created_at": r.created_at}
            for r in rows
        ],
        "adjustments": {
            "by_subject": adjustments.get("signatures", {}),
            "by_type": adjustments.get("types", {}),
        },
    })


# --- forecasts --------------------------------------------------------------

@router.get("/sessions/{session_id}/forecast")
def get_forecast(session_id: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Projections for the leading measures, and the reason where there is none."""
    session = require_completed(owned_session(session_id, user, db))
    forecasts = session.result.get("forecasts", [])
    return jsonify({
        "forecasts": forecasts,
        "available": [f for f in forecasts if f.get("available")],
        "unavailable": [
            {"measure": f.get("measure"), "reason": f.get("reason")}
            for f in forecasts if not f.get("available")
        ],
        "time_column": session.result.get("time_column"),
        "policy": (
            "A projection is model output, not a measurement. Projected values are never "
            "included in any KPI, total or share, are labelled wherever they appear, and are "
            "withheld entirely when the fitted model does not justify one."
        ),
    })


# --- exports ----------------------------------------------------------------

def _report_analysis(session: AnalysisSession, filters: list[Any]) -> tuple[dict[str, Any], pd.DataFrame | None]:
    if not filters:
        return session.result, None
    frame = _filtered_frame(session, filters)
    if frame.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No records match those filters.")
    return jsonify(analyze_dataframe(frame, session.workbook_meta or {})), frame


@router.post("/sessions/{session_id}/report/pdf")
def report_pdf(session_id: str, payload: ReportRequest, user: CurrentUser,
               db: DbSession) -> Response:
    session = require_completed(owned_session(session_id, user, db))
    analysis, _ = _report_analysis(session, payload.filters)

    logo_bytes = None
    if payload.logo_base64:
        raw = payload.logo_base64.split(",")[-1]
        try:
            logo_bytes = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="The logo could not be decoded. Send a base64 PNG or JPEG.")
        if len(logo_bytes) > 3 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="The logo must be smaller than 3 MB.")

    pdf = generate_pdf(analysis, {
        "style": payload.style,
        "title": payload.title or f"{session.name} - Analytics Report",
        "organization": payload.organization or user.organization,
        "author": payload.author or user.full_name or user.email,
        "date_range": payload.date_range,
        "audience": payload.audience,
        "sections": payload.sections,
        "include_charts": payload.include_charts,
        "logo_bytes": logo_bytes,
        "dataset_name": session.original_filename,
    })
    filename = safe_filename(f"{session.name}-{payload.style}-report.pdf")
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/styles")
def report_styles() -> dict[str, Any]:
    return {
        "styles": [
            {"key": key, "label": preset["label"], "pages": preset["pages"],
             "sections": preset["sections"]}
            for key, preset in STYLE_PRESETS.items()
        ],
        "audiences": narrative.AUDIENCES,
    }


@router.post("/sessions/{session_id}/export/excel")
def export_excel(session_id: str, payload: ExcelExportRequest, user: CurrentUser,
                 db: DbSession) -> Response:
    session = require_completed(owned_session(session_id, user, db))
    analysis, filtered = _report_analysis(session, payload.filters)
    frame = filtered
    if payload.include_data and frame is None:
        frame = _filtered_frame(session, [])
    workbook = build_workbook(analysis, frame, {
        "include_data": payload.include_data, "data_row_limit": payload.data_row_limit,
    })
    filename = safe_filename(f"{session.name}-analysis.xlsx")
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/sessions/{session_id}/export/data")
def export_filtered_data(session_id: str, payload: ExcelExportRequest, user: CurrentUser,
                         db: DbSession) -> Response:
    """Download the filtered rows as CSV, with formula injection defused."""
    session = require_completed(owned_session(session_id, user, db))
    frame = _filtered_frame(session, payload.filters).head(payload.data_row_limit)
    safe = frame.copy()
    for column in safe.columns:
        if is_text_column(safe[column]):
            safe[column] = safe[column].map(escape_for_spreadsheet)
    csv = safe.to_csv(index=False)
    filename = safe_filename(f"{session.name}-data.csv")
    return Response(
        content=csv, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/sessions/{session_id}/share")
def share_report(session_id: str, payload: ShareRequest, user: CurrentUser,
                 db: DbSession) -> dict[str, Any]:
    """Create a read-only link to the findings (never the underlying rows)."""
    session = require_completed(owned_session(session_id, user, db))
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    db.add(SharedReport(session_id=session.id, user_id=user.id, token=token, expires_at=expires))
    db.commit()
    return {"token": token, "expires_at": expires,
            "path": f"{settings.api_prefix}/shared/{token}",
            "note": "The link exposes the report only - the uploaded rows are never included."}


@router.get("/shared/{token}")
def read_shared(token: str, db: DbSession) -> dict[str, Any]:
    shared = db.query(SharedReport).filter(SharedReport.token == token).first()
    if shared is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found.")
    expires = shared.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This link has expired.")
    session = db.get(AnalysisSession, shared.session_id)
    if session is None or session.status != "completed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report unavailable.")
    analysis = session.result
    return {
        "name": session.name,
        "summary": analysis.get("summary"),
        "kpis": analysis.get("kpis", {}).get("primary", []),
        "story": analysis.get("story"),
        "insights": analysis.get("insights", [])[:20],
        "charts": analysis.get("charts", []),
        "briefing": analysis.get("briefing"),
        "quality": analysis.get("quality"),
        "story_score": analysis.get("story_score"),
        "recommendations": analysis.get("recommendations", []),
        "shared": True,
    }


# --- samples ----------------------------------------------------------------

@router.get("/samples")
def list_samples() -> dict[str, Any]:
    return {
        "samples": [
            {"key": key, "title": meta["title"], "description": meta["description"],
             "highlights": meta["highlights"], "filename": meta["filename"]}
            for key, meta in SAMPLES.items()
        ]
    }


@router.post("/samples/{key}/load", response_model=SessionSummary,
             status_code=status.HTTP_202_ACCEPTED)
def load_sample(key: str, user: CurrentUser, db: DbSession) -> SessionSummary:
    if key not in SAMPLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Unknown sample. Available: {', '.join(SAMPLES)}.")
    paths = build_all()
    content = paths[key].read_bytes()
    session = analysis_service.create_session(
        db, user.id, SAMPLES[key]["filename"], content, name=SAMPLES[key]["title"],
    )
    session.config = {**(session.config or {}), "sample": key}
    db.commit()
    analysis_service.schedule_analysis(session.id, None)
    db.refresh(session)
    return _summary(session)
