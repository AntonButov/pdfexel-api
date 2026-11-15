from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

CORPUS = Path(__file__).resolve().parent / "corpus"
PASS_DIR = CORPUS / "pass"
EXPECTED_DIR = CORPUS / "expected"
GOLDEN_DIR = CORPUS / "golden"


def pass_pdfs() -> list[Path]:
    return sorted(PASS_DIR.glob("*.pdf"))


def expected_path(stem: str) -> Path:
    return EXPECTED_DIR / f"{stem}.json"


def load_expected(stem: str) -> dict[str, Any]:
    return json.loads(expected_path(stem).read_text(encoding="utf-8"))


def parse_payload_from_expected(expected: dict[str, Any]) -> dict[str, Any]:
    tables = expected["tables"]
    pages = max((int(t.get("page", 1)) for t in tables), default=1)
    return {
        "ok": True,
        "pages": pages,
        "tables": tables,
        "errors": [],
        "engine": {"name": "fixture"},
    }


def build_xlsx_bytes(tables: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    default = wb.active
    for index, table in enumerate(tables, start=1):
        name = f"Table{index}"
        ws = default if index == 1 else wb.create_sheet(title=name)
        if index == 1:
            ws.title = name
        for r_i, row in enumerate(table["rows"], start=1):
            for c_i, cell in enumerate(row, start=1):
                ws.cell(row=r_i, column=c_i, value="" if cell is None else cell)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def workbook_base64_response(tables: list[dict[str, Any]]) -> dict[str, Any]:
    raw = build_xlsx_bytes(tables)
    return {
        "ok": True,
        "sheets": [f"Table{i}" for i in range(1, len(tables) + 1)],
        "workbook_base64": base64.b64encode(raw).decode("ascii"),
        "errors": [],
    }


def sheet_matrix(xlsx_bytes: bytes) -> list[list[list[str]]]:
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    out: list[list[list[str]]] = []
    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            rows.append(["" if c is None else str(c) for c in row])
        out.append(rows)
    return out


def expected_matrices(expected: dict[str, Any]) -> list[list[list[str]]]:
    matrices: list[list[list[str]]] = []
    for table in expected["tables"]:
        matrices.append([["" if c is None else str(c) for c in row] for row in table["rows"]])
    return matrices
