"""Session lifecycle: storage, background analysis and cached dataframes."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import file_fingerprint
from app.engines.excel_parser import WorkbookError, combine_sheets, read_workbook
from app.engines.orchestrator import Progress, analyze_workbook
from app.engines.sanitize import safe_filename
from app.models import AnalysisSession

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis")
_frame_cache: dict[str, tuple[pd.DataFrame, float]] = {}
_cache_lock = threading.Lock()
CACHE_LIMIT = 8


def storage_path_for(user_id: str, session_id: str, filename: str) -> Path:
    directory = settings.storage_dir / user_id
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(safe_filename(filename)).suffix.lower() or ".xlsx"
    return directory / f"{session_id}{suffix}"


def create_session(db: Session, user_id: str, filename: str, content: bytes,
                   name: str | None = None) -> AnalysisSession:
    session = AnalysisSession(
        user_id=user_id,
        name=name or Path(safe_filename(filename)).stem[:120] or "Untitled analysis",
        original_filename=safe_filename(filename),
        file_size=len(content),
        checksum=file_fingerprint(content),
        status="pending",
        progress={"stages": [], "completed": 0, "total": 12, "percent": 0},
    )
    db.add(session)
    db.flush()
    path = storage_path_for(user_id, session.id, filename)
    path.write_bytes(content)
    path.chmod(0o600)
    session.storage_path = str(path)
    db.commit()
    db.refresh(session)
    return session


def _set_progress(session_id: str, snapshot: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, session_id)
        if session:
            session.progress = snapshot
            db.commit()
    except Exception:  # noqa: BLE001 - progress must never fail the analysis
        db.rollback()
    finally:
        db.close()


def run_analysis(session_id: str, sheet: str | None = None) -> None:
    """Execute the pipeline for a session, persisting progress and the result."""
    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, session_id)
        if session is None:
            return
        session.status = "processing"
        session.error = ""
        db.commit()

        path = Path(session.storage_path)
        if not path.exists():
            session.status = "failed"
            session.error = (
                "The uploaded file is no longer available. Uploads are removed automatically "
                f"after {settings.file_retention_hours} hours; please upload it again."
            )
            session.file_deleted = True
            db.commit()
            return

        content = path.read_bytes()
        progress = Progress(callback=lambda snapshot: _set_progress(session_id, snapshot))
        result = analyze_workbook(content, session.original_filename, sheet=sheet,
                                  progress=progress)

        session.result = result
        session.workbook_meta = result.get("meta", {})
        session.config = {**(session.config or {}), "sheet": sheet,
                          "scope": result.get("scope", "workbook")}
        session.progress = result.get("progress", session.progress)
        session.status = "completed"
        session.error = ""
        db.commit()
        logger.info("analysis completed session=%s rows=%s", session_id,
                    result["profile"]["row_count"])
    except WorkbookError as exc:
        _fail(db, session_id, str(exc))
    except MemoryError:
        _fail(db, session_id,
              "The workbook is too large to analyse in the available memory. Try analysing a "
              "single sheet, or reduce the number of rows.")
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a failed session
        logger.exception("analysis failed session=%s", session_id)
        _fail(db, session_id, f"Analysis failed: {exc}")
    finally:
        db.close()


def _fail(db: Session, session_id: str, message: str) -> None:
    try:
        session = db.get(AnalysisSession, session_id)
        if session:
            session.status = "failed"
            session.error = message[:2000]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def schedule_analysis(session_id: str, sheet: str | None = None) -> None:
    _executor.submit(run_analysis, session_id, sheet)


def load_dataframe(session: AnalysisSession) -> pd.DataFrame:
    """Return the analysed table, using a small in-process cache."""
    with _cache_lock:
        cached = _frame_cache.get(session.id)
        if cached is not None:
            return cached[0]

    path = Path(session.storage_path)
    if not path.exists():
        raise FileNotFoundError(
            "The uploaded file has been removed by the retention policy. Upload it again to "
            "continue exploring this dataset."
        )
    frames, _, _ = read_workbook(path.read_bytes(), session.original_filename,
                                 max_rows=settings.max_rows_analyzed)
    configured_sheet = (session.config or {}).get("sheet")
    if configured_sheet and configured_sheet in frames:
        frame = frames[configured_sheet]
    else:
        frame = combine_sheets(frames)

    with _cache_lock:
        if len(_frame_cache) >= CACHE_LIMIT:
            oldest = min(_frame_cache, key=lambda key: _frame_cache[key][1])
            _frame_cache.pop(oldest, None)
        _frame_cache[session.id] = (frame, datetime.now(timezone.utc).timestamp())
    return frame


def invalidate_cache(session_id: str) -> None:
    with _cache_lock:
        _frame_cache.pop(session_id, None)


def delete_session_file(session: AnalysisSession) -> None:
    try:
        path = Path(session.storage_path)
        if path.exists():
            path.unlink()
    except OSError:  # noqa: PERF203 - best effort cleanup
        logger.warning("could not delete file for session %s", session.id)
    invalidate_cache(session.id)


def cleanup_expired_files(retention_hours: int | None = None) -> int:
    """Delete uploaded workbooks past the retention window.

    The analysis result stays in the database - only the raw uploaded file, the
    most sensitive artefact, is removed.
    """
    retention = retention_hours if retention_hours is not None else settings.file_retention_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention)
    removed = 0
    db = SessionLocal()
    try:
        sessions = db.query(AnalysisSession).filter(
            AnalysisSession.file_deleted.is_(False)
        ).all()
        for session in sessions:
            updated = session.updated_at
            if updated is None:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated > cutoff:
                continue
            delete_session_file(session)
            session.file_deleted = True
            removed += 1
        db.commit()
    finally:
        db.close()
    return removed
