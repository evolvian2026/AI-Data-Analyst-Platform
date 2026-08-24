"""Application configuration.

All settings are environment driven so the same image can be promoted from a
developer laptop to production without code changes.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- General -----------------------------------------------------------
    app_name: str = "AI Data Analyst"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    api_prefix: str = "/api"

    # --- Security ----------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: os.getenv("SECRET_KEY") or secrets.token_urlsafe(48))
    access_token_expire_minutes: int = 60 * 12
    algorithm: str = "HS256"
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])
    allow_registration: bool = True

    # --- Storage -----------------------------------------------------------
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
    storage_dir: Path = Field(default=BASE_DIR / "data" / "uploads")
    max_upload_mb: int = 100
    # Uploaded workbooks are transient processing artefacts: they are removed
    # this many hours after the last time their session was touched.
    file_retention_hours: int = 72

    # Background processing. Analysis runs in an in-process worker pool by
    # default; set this to move the queue to Celery/Redis for horizontal scale.
    redis_url: str = Field(default="")

    # --- Analytics limits --------------------------------------------------
    max_rows_analyzed: int = 1_000_000
    sample_rows_for_profiling: int = 50_000
    max_charts: int = 14
    max_primary_kpis: int = 8

    # --- AI provider -------------------------------------------------------
    # "deterministic" is the default: narratives are composed from the values
    # produced by the analytics engine, so nothing can ever be fabricated.
    ai_provider: str = Field(default="deterministic")
    ai_api_key: str = Field(default="")
    ai_model: str = Field(default="claude-sonnet-4-5")
    ai_base_url: str = Field(default="https://api.anthropic.com")
    ai_timeout_seconds: int = 60
    ai_max_output_tokens: int = 2000
    # Hard privacy switch: when False the raw dataset never leaves the server,
    # only aggregated metrics / profiles are shared with the model.
    ai_allow_raw_rows: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("storage_dir", mode="before")
    @classmethod
    def _as_path(cls, v):
        return Path(v)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
