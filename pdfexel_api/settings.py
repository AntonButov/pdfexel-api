from __future__ import annotations

import os
from pathlib import Path


def pdf_stand_url() -> str:
    return os.environ.get("PDF_STAND_URL", "http://127.0.0.1:8131/parse").rstrip("/")


def json_stand_url() -> str:
    return os.environ.get("JSON_STAND_URL", "http://127.0.0.1:8132/convert").rstrip("/")


def jobs_dir() -> Path:
    return Path(os.environ.get("JOBS_DIR", "/data/jobs"))


TIMEOUT_S = float(os.environ.get("STAND_TIMEOUT_S", "120"))
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))

SMTP_HOST = os.environ.get("SMTP_HOST", "mail.antonbutov.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "mail@antonbutov.com").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", "mail@antonbutov.com").strip()
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip() not in ("0", "false", "False")

AUTH_SESSION_DAYS = int(os.environ.get("AUTH_SESSION_DAYS", "7"))
AUTH_CODE_TTL_SEC = int(os.environ.get("AUTH_CODE_TTL_SEC", "600"))
AUTH_CODE_MAX_ATTEMPTS = int(os.environ.get("AUTH_CODE_MAX_ATTEMPTS", "5"))
AUTH_RATE_LIMIT = int(os.environ.get("AUTH_RATE_LIMIT", "5"))
AUTH_RATE_WINDOW_SEC = float(os.environ.get("AUTH_RATE_WINDOW_SEC", str(15 * 60)))
AUTH_COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "pdfexel_session").strip() or "pdfexel_session"
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "1").strip() not in ("0", "false", "False")
AUTH_SECRET = os.environ.get("AUTH_SECRET", "").strip() or "pdfexel-dev-secret-change-me"
