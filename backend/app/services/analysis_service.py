"""Session lifecycle: storage, background analysis and cached dataframes."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import file_fingerprint
from app.engines.excel_parser import WorkbookError, read_workbook
from app.engines.relationships import JoinError
from app.engines.orchestrator import Progress, analyze_workbook, prepare_frame
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
    except (StaleDataError, Exception):  # noqa: BLE001 - progress must never fail the analysis
        db.rollback()
    finally:
        db.close()


def run_analysis(session_id: str, sheet: str | None = None) -> None:
    """Execute the pipeline for a session, persisting progress and the result.

    The database session is deliberately released before the analysis starts.
    Holding one across the CPU work would pin a connection *idle in transaction*
    for the whole run, which on PostgreSQL blocks DDL (a migration during an
    analysis simply hangs), stops autovacuum reclaiming dead tuples, and burns a
    pool slot per concurrent analysis. SQLite hides all of this.
    """
    # --- 1. claim the job, taking a copy of everything the run needs ---------
    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, session_id)
        if session is None:
            return
        # Read before committing: commit expires the instance, so a later
        # attribute access would issue a fresh SELECT and reopen a transaction.
        storage_path = session.storage_path
        original_filename = session.original_filename
        existing_config = dict(session.config or {})
        session.status = "processing"
        session.error = ""
        db.commit()
    except StaleDataError:
        db.rollback()
        return
    finally:
        db.close()

    # --- 2. the long work, holding no database session -----------------------
    try:
        path = Path(storage_path)
        if not path.exists():
            _fail(
                session_id,
                "The uploaded file is no longer available. Uploads are removed automatically "
                f"after {settings.file_retention_hours} hours; please upload it again.",
                file_deleted=True,
            )
            return

        content = path.read_bytes()
        progress = Progress(callback=lambda snapshot: _set_progress(session_id, snapshot))
        result = analyze_workbook(content, original_filename, sheet=sheet, progress=progress,
                                  config=existing_config)
    except (WorkbookError, JoinError, ValueError) as exc:
        _fail(session_id, str(exc))
        return
    except MemoryError:
        _fail(session_id,
              "The workbook is too large to analyse in the available memory. Try analysing a "
              "single sheet, or reduce the number of rows.")
        return
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a failed session
        logger.exception("analysis failed session=%s", session_id)
        _fail(session_id, f"Analysis failed: {exc}")
        return

    # --- 3. persist the result in a second short transaction -----------------
    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, session_id)
        if session is None:
            logger.info("analysis discarded, session removed: %s", session_id)
            return
        session.result = result
        session.workbook_meta = result.get("meta", {})
        session.config = {**existing_config, "sheet": sheet,
                          "scope": result.get("scope", "workbook")}
        session.progress = result.get("progress", session.progress)
        session.status = "completed"
        session.error = ""
        db.commit()
        logger.info("analysis completed session=%s rows=%s", session_id,
                    result["profile"]["row_count"])
    except StaleDataError:
        # The session was deleted while its analysis was still running.
        db.rollback()
        logger.info("analysis discarded, session removed: %s", session_id)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("could not persist analysis session=%s", session_id)
        _fail(session_id, "The analysis finished but its result could not be saved.")
    finally:
        db.close()


def _fail(session_id: str, message: str, file_deleted: bool = False) -> None:
    """Record a failure in its own short-lived session."""
    db = SessionLocal()
    try:
        session = db.get(AnalysisSession, session_id)
        if session is None:
            return
        session.status = "failed"
        session.error = message[:2000]
        if file_deleted:
            session.file_deleted = True
        db.commit()
    except Exception:  # noqa: BLE001 - a failure to record a failure is not fatal
        db.rollback()
        logger.exception("could not record failure for session=%s", session_id)
    finally:
        db.close()


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
    config = session.config or {}
    # The same join and cleaning steps the analysis ran, so exploring rows and
    # filtering can never operate on a different table from the reported numbers.
    frame, _ = prepare_frame(frames, config.get("sheet"), config)

    with _cache_lock:
        if len(_frame_cache) >= CACHE_LIMIT:
            oldest = min(_frame_cache, key=lambda key: _frame_cache[key][1])
            _frame_cache.pop(oldest, None)
        _frame_cache[session.id] = (frame, datetime.now(timezone.utc).timestamp())
    return frame


def load_sheets(session: AnalysisSession) -> dict[str, pd.DataFrame]:
    """Every analysable sheet of the workbook, unmodified.

    Used by the join endpoints, which need the sheets separately rather than the
    single prepared table the analysis works on.
    """
    path = Path(session.storage_path)
    if not path.exists():
        raise FileNotFoundError(
            "The uploaded file has been removed by the retention policy. Upload it again to "
            "continue exploring this dataset."
        )
    frames, _, _ = read_workbook(path.read_bytes(), session.original_filename,
                                 max_rows=settings.max_rows_analyzed)
    return frames


def load_raw_frame(session: AnalysisSession) -> pd.DataFrame:
    """The analysed table *before* any accepted cleaning recipe.

    Previewing a fix has to run against uncleaned data, otherwise a fix that is
    already applied looks like it would change nothing.
    """
    config = dict(session.config or {})
    config.pop("cleaning", None)
    frame, _ = prepare_frame(load_sheets(session), config.get("sheet"), config)
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


def result_expires_at(session: AnalysisSession, retention_days: int | None = None) -> datetime | None:
    """When this analysis will be purged, or None if results are kept forever."""
    retention = (
        retention_days if retention_days is not None else settings.result_retention_days
    )
    if retention <= 0:
        return None
    updated = session.updated_at
    if updated is None:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated + timedelta(days=retention)


def purge_expired_results(retention_days: int | None = None) -> int:
    """Delete analyses past the result-retention window.

    The file sweep removes the upload but leaves the analysis, which holds
    aggregates, column names and sample values taken from it. A deployment with
    a data-handling policy needs a bound on that too, so this deletes the whole
    session row - result, notes, query log and share links cascade with it.

    A retention of 0 disables the sweep, which is the default: deleting a user's
    analyses is not something an upgrade should start doing unasked.
    """
    retention = (
        retention_days if retention_days is not None else settings.result_retention_days
    )
    if retention <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    removed = 0
    db = SessionLocal()
    try:
        for session in db.query(AnalysisSession).all():
            updated = session.updated_at
            if updated is None:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated > cutoff:
                continue
            delete_session_file(session)
            db.delete(session)
            removed += 1
        db.commit()
    finally:
        db.close()
    if removed:
        logger.info("result retention sweep removed %s analysis session(s)", removed)
    return removed


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
