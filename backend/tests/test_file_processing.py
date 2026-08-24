"""File processing: upload, multiple sheets, large files, invalid files."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from app.engines.excel_parser import WorkbookError, combine_sheets, read_workbook
from tests.conftest import write_workbook


def test_reads_a_simple_workbook(sales_workbook):
    frames, infos, meta = read_workbook(sales_workbook, "sales.xlsx")
    assert list(frames) == ["Sales"]
    assert meta["sheet_count"] == 1
    assert meta["total_rows"] == len(frames["Sales"])
    assert infos[0].is_analyzable
    assert meta["file_size"] == len(sales_workbook)


def test_reads_multiple_sheets():
    content = write_workbook({
        "Orders": pd.DataFrame({"Customer ID": ["C1", "C2"], "Amount": [10, 20]}),
        "Customers": pd.DataFrame({"Customer ID": ["C1", "C2"], "Region": ["N", "S"]}),
        "Empty": pd.DataFrame(),
    })
    frames, infos, meta = read_workbook(content, "multi.xlsx")
    assert set(frames) == {"Orders", "Customers"}
    assert meta["sheet_count"] == 3
    assert any(not info.is_analyzable for info in infos)


def test_detects_header_row_below_title_rows():
    raw = pd.DataFrame([
        ["Quarterly report", None, None],
        [None, None, None],
        ["Region", "Units", "Revenue"],
        ["North", 10, 1000],
        ["South", 12, 1200],
        ["East", 8, 800],
    ])
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        raw.to_excel(writer, sheet_name="Report", index=False, header=False)
    frames, infos, _ = read_workbook(buffer.getvalue(), "report.xlsx")
    frame = frames["Report"]
    assert list(frame.columns) == ["Region", "Units", "Revenue"]
    assert len(frame) == 3
    assert infos[0].header_row == 2


def test_handles_duplicate_and_missing_headers():
    raw = pd.DataFrame([
        ["Region", "Amount", "Amount", None],
        ["North", 1, 2, 3],
        ["South", 4, 5, 6],
        ["East", 7, 8, 9],
    ])
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        raw.to_excel(writer, sheet_name="Data", index=False, header=False)
    frames, infos, _ = read_workbook(buffer.getvalue(), "dupes.xlsx")
    columns = list(frames["Data"].columns)
    assert len(columns) == len(set(columns)), "duplicate headers must be made unique"
    assert "Amount" in columns and "Amount (1)" in columns
    assert infos[0].duplicate_headers_renamed == ["Amount"]
    assert infos[0].unnamed_headers == 1


def test_drops_empty_rows_and_columns():
    frame = pd.DataFrame({
        "A": [1, None, 3, None], "AllEmpty": [None] * 4, "B": ["x", None, "z", None],
    })
    frames, infos, _ = read_workbook(write_workbook({"S": frame}), "sparse.xlsx")
    assert "AllEmpty" not in frames["S"].columns
    assert infos[0].empty_columns_removed >= 1
    assert infos[0].empty_rows_removed >= 1


def test_rejects_unsupported_extension(sales_workbook):
    with pytest.raises(WorkbookError, match="Unsupported file type"):
        read_workbook(sales_workbook, "data.csv")


def test_rejects_corrupt_file():
    with pytest.raises(WorkbookError):
        read_workbook(b"PK\x03\x04 this is not really a workbook", "broken.xlsx")


def test_rejects_workbook_with_no_analyzable_table():
    with pytest.raises(WorkbookError, match="No analyzable table"):
        read_workbook(write_workbook({"S": pd.DataFrame({"A": [1]})}), "tiny.xlsx")


def test_large_workbook_is_read_within_row_cap():
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({
        "ID": np.arange(30_000),
        "Category": rng.choice(["A", "B", "C"], 30_000),
        "Value": rng.normal(100, 20, 30_000).round(2),
    })
    content = write_workbook({"Big": frame})
    frames, _, meta = read_workbook(content, "big.xlsx", max_rows=10_000)
    assert len(frames["Big"]) == 10_000
    assert meta["total_cells"] > 0


def test_combine_sheets_unions_matching_schemas():
    frames = {
        "Q1": pd.DataFrame({"Region": ["N"] * 3, "Revenue": [1, 2, 3]}),
        "Q2": pd.DataFrame({"Region": ["S"] * 3, "Revenue": [4, 5, 6]}),
    }
    combined = combine_sheets(frames)
    assert len(combined) == 6
    assert "__sheet__" in combined.columns


def test_combine_sheets_keeps_largest_when_schemas_differ():
    frames = {
        "Small": pd.DataFrame({"A": [1, 2]}),
        "Large": pd.DataFrame({"B": range(50), "C": range(50)}),
    }
    combined = combine_sheets(frames)
    assert list(combined.columns) == ["B", "C"]
