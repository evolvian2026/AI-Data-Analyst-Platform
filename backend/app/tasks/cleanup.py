"""Retention job: remove uploaded workbooks past the retention window.

Run on a schedule (the compose stack runs it hourly). Only the uploaded file is
removed - the analysis result stays in the database so previously generated
reports remain readable.
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import init_db
from app.services.analysis_service import cleanup_expired_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup")


def main() -> int:
    init_db()
    removed = cleanup_expired_files()
    logger.info(
        "retention sweep complete: %s file(s) removed (retention %sh)",
        removed, settings.file_retention_hours,
    )
    return removed


if __name__ == "__main__":  # pragma: no cover
    main()
