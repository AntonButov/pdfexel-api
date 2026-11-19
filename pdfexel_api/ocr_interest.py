"""Append-only log of users who asked for paid OCR on scanned PDFs."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from pdfexel_api.settings import ocr_interest_log

log = logging.getLogger("pdfexel_api.ocr_interest")
_lock = threading.Lock()


def append_interest(row: dict[str, Any]) -> Path:
    path = ocr_interest_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": int(time.time()),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **row,
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    log.info(
        "ocr_interest email=%s filename=%r source=%s",
        payload.get("email") or "-",
        payload.get("filename") or "",
        payload.get("source") or "",
    )
    return path
