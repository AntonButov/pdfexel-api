from __future__ import annotations

import os


def pdf_stand_url() -> str:
    return os.environ.get("PDF_STAND_URL", "http://127.0.0.1:8131/parse").rstrip("/")


def json_stand_url() -> str:
    return os.environ.get("JSON_STAND_URL", "http://127.0.0.1:8132/convert").rstrip("/")


TIMEOUT_S = float(os.environ.get("STAND_TIMEOUT_S", "120"))
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
