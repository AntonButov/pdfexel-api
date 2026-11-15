from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pdfexel_api.settings import jobs_dir

log = logging.getLogger("pdfexel_api.jobs")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str, fallback: str) -> str:
    base = Path(name or fallback).name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or fallback
    return cleaned[:180]


def job_dir(request_id: str, *, when: datetime | None = None) -> Path:
    ts = when or datetime.now(timezone.utc)
    day = ts.strftime("%Y-%m-%d")
    path = jobs_dir() / day / request_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_input_pdf(request_id: str, pdf_bytes: bytes, filename: str) -> Path:
    folder = job_dir(request_id)
    # Keep original name beside canonical input.pdf
    original = folder / _safe_filename(filename, "upload.pdf")
    if original.name.lower() != "input.pdf":
        original.write_bytes(pdf_bytes)
    input_path = folder / "input.pdf"
    input_path.write_bytes(pdf_bytes)
    log.info(
        "rid=%s step=jobs.save_input path=%s bytes=%d original=%s",
        request_id,
        input_path,
        len(pdf_bytes),
        original.name,
    )
    return input_path


def save_result_xlsx(request_id: str, xlsx_bytes: bytes, filename: str) -> Path:
    folder = job_dir(request_id)
    out_name = _safe_filename(filename, "result.xlsx")
    if not out_name.lower().endswith(".xlsx"):
        out_name += ".xlsx"
    named = folder / out_name
    named.write_bytes(xlsx_bytes)
    canonical = folder / "result.xlsx"
    if named.resolve() != canonical.resolve():
        canonical.write_bytes(xlsx_bytes)
    log.info(
        "rid=%s step=jobs.save_result path=%s bytes=%d named=%s",
        request_id,
        canonical,
        len(xlsx_bytes),
        named.name,
    )
    return canonical


def write_meta(request_id: str, payload: dict[str, Any]) -> Path:
    folder = job_dir(request_id)
    meta = {
        "request_id": request_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path = folder / "meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("rid=%s step=jobs.save_meta path=%s status=%s", request_id, path, meta.get("status"))
    return path
