from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.config import settings
from app.engines.ai_provider import provider_status
from app.engines.narrative import AUDIENCES
from app.engines.orchestrator import STAGES

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "environment": settings.environment}


@router.get("/config")
def config() -> dict[str, Any]:
    """Client-visible limits and capabilities - never secrets."""
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "max_upload_mb": settings.max_upload_mb,
        "max_rows_analyzed": settings.max_rows_analyzed,
        "max_charts": settings.max_charts,
        "max_primary_kpis": settings.max_primary_kpis,
        "file_retention_hours": settings.file_retention_hours,
        "result_retention_days": settings.result_retention_days,
        "allow_registration": settings.allow_registration,
        "accepted_formats": [".xlsx", ".xls"],
        "pipeline_stages": [{"key": key, "label": label} for key, label in STAGES],
        "audiences": AUDIENCES,
        "ai": provider_status(),
    }
