"""Retention job: enforce both retention windows.

Run on a schedule (the compose stack runs it hourly).

Two separate windows, because the two artefacts carry different risk:

* ``FILE_RETENTION_HOURS`` removes the uploaded workbook - the raw rows, the
  most sensitive thing the platform holds. The analysis survives, so previously
  generated reports stay readable.
* ``RESULT_RETENTION_DAYS`` removes the analysis itself, which still contains
  aggregates, column names and sample values drawn from the upload. It is 0 -
  keep indefinitely - unless a deployment sets a policy, because deleting a
  user's analyses is not something an upgrade should start doing unasked.
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import init_db
from app.services.analysis_service import cleanup_expired_files, purge_expired_results

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup")


def main() -> int:
    init_db()
    files = cleanup_expired_files()
    results = purge_expired_results()
    logger.info(
        "retention sweep complete: %s file(s) removed (retention %sh); "
        "%s analysis result(s) purged (retention %s)",
        files, settings.file_retention_hours, results,
        f"{settings.result_retention_days}d" if settings.result_retention_days > 0
        else "disabled",
    )
    return files + results


if __name__ == "__main__":  # pragma: no cover
    main()
