"""Workbook reader.

Handles the messy real-world cases the spec calls out: multiple sheets, empty
rows/columns, missing headers, duplicate headers, mixed types and large files.
Reading is done server side and chunk-aware so the browser never receives the
raw workbook.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.engines.formatting import is_text_column
from app.engines.sanitize import (
    looks_like_injection,
    neutralize_text,
    safe_filename,
    sanitize_value,
)

MAX_HEADER_SCAN_ROWS = 12


class WorkbookError(ValueError):
    """Raised when a file cannot be interpreted as a supported workbook."""


@dataclass
class SheetInfo:
    name: str
    rows: int
    columns: int
    cells: int
    header_row: int
    empty_columns_removed: int
    empty_rows_removed: int
    duplicate_headers_renamed: list[str] = field(default_factory=list)
    unnamed_headers: int = 0
    is_analyzable: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rows": self.rows,
            "columns": self.columns,
            "cells": self.cells,
            "header_row": self.header_row,
            "empty_columns_removed": self.empty_columns_removed,
            "empty_rows_removed": self.empty_rows_removed,
            "duplicate_headers_renamed": self.duplicate_headers_renamed,
            "unnamed_headers": self.unnamed_headers,
            "is_analyzable": self.is_analyzable,
            "reason": self.reason,
        }


def _engine_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xls":
        return "xlrd"
    if suffix in {".xlsx", ".xlsm", ".xltx"}:
        return "openpyxl"
    raise WorkbookError(
        f"Unsupported file type '{suffix or 'unknown'}'. Upload an .xlsx or .xls workbook."
    )


def _detect_header_row(raw: pd.DataFrame) -> int:
    """Find the most plausible header row in the first few rows.

    A header row is mostly non-empty, mostly text, and its values are distinct.
    """
    best_row, best_score = 0, -math.inf
    limit = min(MAX_HEADER_SCAN_ROWS, len(raw))
    for idx in range(limit):
        values = raw.iloc[idx].tolist()
        non_empty = [v for v in values if not _is_blank(v)]
        if len(non_empty) < 2:
            continue
        fill_ratio = len(non_empty) / max(len(values), 1)
        text_ratio = sum(1 for v in non_empty if isinstance(v, str)) / len(non_empty)
        distinct_ratio = len({str(v).strip().lower() for v in non_empty}) / len(non_empty)
        numeric_penalty = sum(1 for v in non_empty if isinstance(v, (int, float, np.number))) / len(non_empty)
        # rows further down are less likely to be the header
        score = (fill_ratio * 2) + (text_ratio * 3) + distinct_ratio - numeric_penalty * 2 - idx * 0.35
        if score > best_score:
            best_score, best_row = score, idx
    return best_row if best_score > 0 else 0


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return value is pd.NaT


def _clean_headers(values: list[Any]) -> tuple[list[str], list[str], int]:
    """Return (headers, renamed_duplicates, unnamed_count)."""
    seen: dict[str, int] = {}
    headers: list[str] = []
    renamed: list[str] = []
    unnamed = 0
    for position, value in enumerate(values):
        if _is_blank(value) or str(value).lower().startswith("unnamed:"):
            name = f"Column_{position + 1}"
            unnamed += 1
        else:
            name = neutralize_text(value, 120) or f"Column_{position + 1}"
        base = name
        if base in seen:
            seen[base] += 1
            name = f"{base} ({seen[base]})"
            renamed.append(base)
        else:
            seen[base] = 0
        headers.append(name)
    return headers, sorted(set(renamed)), unnamed


def _drop_empty(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    before_cols = df.shape[1]
    df = df.dropna(axis=1, how="all")
    empty_cols = before_cols - df.shape[1]
    before_rows = df.shape[0]
    df = df.dropna(axis=0, how="all")
    empty_rows = before_rows - df.shape[0]
    return df, empty_cols, empty_rows


def _coerce_text_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Trim text, blank -> NaN, and neutralise instruction-like cells.

    Neutralising here rather than at each output boundary means a hostile cell
    cannot reach a chart label, an insight headline, an export or an AI prompt
    by any route - there is one place to get right instead of a dozen.
    """
    findings: list[dict[str, Any]] = []
    for column in df.columns:
        if not is_text_column(df[column]):
            continue
        series = df[column]
        stripped = series.map(lambda v: v.strip() if isinstance(v, str) else v)
        stripped = stripped.map(lambda v: np.nan if isinstance(v, str) and v == "" else v)

        suspicious = stripped.map(lambda v: looks_like_injection(v) if isinstance(v, str) else False)
        flagged = int(suspicious.sum()) if len(suspicious) else 0
        if flagged:
            example = stripped[suspicious].iloc[0]
            findings.append({
                "column": str(column),
                "occurrences": flagged,
                "excerpt": neutralize_text(example, 160),
                "reason": "Cell content resembles an instruction to an AI system.",
            })
            stripped = stripped.map(sanitize_value)
        df[column] = stripped
    return df, findings


def read_workbook(
    content: bytes,
    filename: str,
    max_rows: int | None = None,
) -> tuple[dict[str, pd.DataFrame], list[SheetInfo], dict[str, Any]]:
    """Read every sheet of a workbook into cleaned dataframes."""
    filename = safe_filename(filename)
    engine = _engine_for(filename)
    buffer = io.BytesIO(content)
    try:
        excel = pd.ExcelFile(buffer, engine=engine)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        raise WorkbookError(f"The file could not be opened as a workbook: {exc}") from exc

    frames: dict[str, pd.DataFrame] = {}
    infos: list[SheetInfo] = []
    injection_findings: list[dict[str, Any]] = []
    total_cells = 0

    for sheet_name in excel.sheet_names:
        try:
            raw = excel.parse(sheet_name, header=None, dtype=object)
        except Exception as exc:  # noqa: BLE001
            infos.append(
                SheetInfo(
                    name=neutralize_text(sheet_name, 80),
                    rows=0, columns=0, cells=0, header_row=0,
                    empty_columns_removed=0, empty_rows_removed=0,
                    is_analyzable=False, reason=f"Sheet could not be parsed: {exc}",
                )
            )
            continue

        safe_name = neutralize_text(sheet_name, 80) or f"Sheet{len(infos) + 1}"
        total_cells += int(raw.shape[0] * raw.shape[1])

        if raw.empty:
            infos.append(
                SheetInfo(safe_name, 0, 0, 0, 0, 0, 0, is_analyzable=False, reason="Sheet is empty.")
            )
            continue

        raw, empty_cols, empty_rows = _drop_empty(raw)
        if raw.empty:
            infos.append(
                SheetInfo(safe_name, 0, 0, 0, 0, empty_cols, empty_rows,
                          is_analyzable=False, reason="Sheet contains no data.")
            )
            continue

        header_row = _detect_header_row(raw)
        # Report the row number as it appears in the sheet, not after empty
        # rows were dropped, so it matches what the user sees in Excel.
        source_header_row = int(raw.index[header_row])
        headers, renamed, unnamed = _clean_headers(raw.iloc[header_row].tolist())
        body = raw.iloc[header_row + 1:].copy()
        body.columns = headers
        body = body.reset_index(drop=True)
        body, extra_cols, extra_rows = _drop_empty(body)
        body, sheet_findings = _coerce_text_columns(body)
        for finding in sheet_findings:
            finding["sheet"] = safe_name
        injection_findings.extend(sheet_findings)

        if max_rows and len(body) > max_rows:
            body = body.head(max_rows)

        analyzable = body.shape[0] >= 2 and body.shape[1] >= 1
        info = SheetInfo(
            name=safe_name,
            rows=int(body.shape[0]),
            columns=int(body.shape[1]),
            cells=int(body.shape[0] * body.shape[1]),
            header_row=source_header_row,
            empty_columns_removed=int(empty_cols + extra_cols),
            empty_rows_removed=int(empty_rows + extra_rows),
            duplicate_headers_renamed=renamed,
            unnamed_headers=unnamed,
            is_analyzable=analyzable,
            reason="" if analyzable else "Not enough rows or columns to analyze.",
        )
        infos.append(info)
        if analyzable:
            frames[safe_name] = body

    if not frames:
        raise WorkbookError(
            "No analyzable table was found in this workbook. "
            "Each sheet needs a header row and at least two data rows."
        )

    meta = {
        "filename": filename,
        "file_size": len(content),
        "sheet_count": len(excel.sheet_names),
        "analyzable_sheet_count": len(frames),
        "sheet_names": [i.name for i in infos],
        "total_rows": int(sum(i.rows for i in infos)),
        "total_columns": int(max((i.columns for i in infos), default=0)),
        "total_cells": int(total_cells),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "sheets": [i.to_dict() for i in infos],
        "injection_findings": injection_findings[:20],
    }
    return frames, infos, meta


def combine_sheets(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Union sheets that share a schema, used by 'Analyze entire workbook'.

    Sheets with identical (or near identical) column sets are stacked with a
    ``__sheet__`` provenance column.  When schemas differ the largest sheet is
    returned unchanged - stacking unrelated tables would produce nonsense.
    """
    if len(frames) == 1:
        return next(iter(frames.values()))

    signatures: dict[frozenset, list[str]] = {}
    for name, df in frames.items():
        signatures.setdefault(frozenset(df.columns), []).append(name)

    best_signature = max(
        signatures,
        key=lambda sig: sum(len(frames[n]) for n in signatures[sig]),
    )
    names = signatures[best_signature]
    if len(names) == 1:
        return frames[names[0]]

    parts = []
    for name in names:
        part = frames[name].copy()
        part["__sheet__"] = name
        parts.append(part)
    return pd.concat(parts, ignore_index=True)
