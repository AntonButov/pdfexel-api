from __future__ import annotations

import logging
import re
import time
import uuid
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from pdfexel_api import settings
from pdfexel_api.auth_store import store
from pdfexel_api.jobs import save_input_pdf, save_result_xlsx, write_meta
from pdfexel_api.logging_setup import configure_logging
from pdfexel_api.mailer import MailerConfigError, MailerSmtpError, send_otp
from pdfexel_api.pipeline import ConvertFail, ConvertOk, convert_pdf_bytes

configure_logging()
log = logging.getLogger("pdfexel_api.api")

app = FastAPI(title="pdfexel-api", version="0.1.0")

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class VerifyBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., min_length=4, max_length=12)


def content_disposition_attachment(filename: str) -> str:
    """RFC 6266 / 5987: ASCII fallback + UTF-8 filename* (Starlette is latin-1)."""
    ascii_name = _SAFE_FILENAME.sub("_", filename).strip("._") or "download.xlsx"
    if not ascii_name.lower().endswith(".xlsx"):
        ascii_name = f"{ascii_name}.xlsx"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="некорректный email")
    return email


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def require_email(request: Request) -> str:
    sid = request.cookies.get(settings.AUTH_COOKIE_NAME)
    email = store.get_email(sid)
    if not email:
        raise HTTPException(status_code=401, detail="auth_required")
    return email


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=session_id,
        max_age=settings.AUTH_SESSION_DAYS * 86400,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    t0 = time.perf_counter()
    client = request.client.host if request.client else "-"
    log.info(
        "rid=%s step=http.in method=%s path=%s client=%s",
        rid,
        request.method,
        request.url.path,
        client,
    )
    try:
        response = await call_next(request)
    except Exception:
        ms = int((time.perf_counter() - t0) * 1000)
        log.exception(
            "rid=%s step=http.exception method=%s path=%s ms=%d",
            rid,
            request.method,
            request.url.path,
            ms,
        )
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "rid=%s step=http.out method=%s path=%s status=%s ms=%d",
        rid,
        request.method,
        request.url.path,
        response.status_code,
        ms,
    )
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/request-code")
def auth_request_code(body: EmailBody, request: Request) -> dict[str, bool]:
    rid = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    email = normalize_email(body.email)
    ip = client_ip(request)

    if not store.check_rate_limit(f"ip:{ip}") or not store.check_rate_limit(f"email:{email}"):
        log.warning("rid=%s step=auth.request_code.rate_limited email=%s ip=%s", rid, email, ip)
        raise HTTPException(status_code=429, detail="слишком много запросов, попробуйте позже")

    code = store.issue_code(email)
    try:
        send_otp(email, code)
    except MailerConfigError:
        log.error("rid=%s step=auth.request_code.smtp_unconfigured", rid)
        raise HTTPException(status_code=503, detail="почта временно недоступна") from None
    except MailerSmtpError:
        log.error("rid=%s step=auth.request_code.smtp_fail email=%s", rid, email)
        raise HTTPException(status_code=503, detail="не удалось отправить код") from None

    log.info("rid=%s step=auth.request_code.ok email=%s", rid, email)
    return {"ok": True}


@app.post("/auth/verify")
def auth_verify(body: VerifyBody, request: Request) -> JSONResponse:
    rid = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    email = normalize_email(body.email)
    if not store.verify_code(email, body.code):
        log.warning("rid=%s step=auth.verify.fail email=%s", rid, email)
        raise HTTPException(status_code=400, detail="неверный или просроченный код")

    sid = store.create_session(email)
    resp = JSONResponse({"ok": True, "email": email})
    set_session_cookie(resp, sid)
    log.info("rid=%s step=auth.verify.ok email=%s", rid, email)
    return resp


@app.get("/auth/me")
def auth_me(request: Request) -> dict[str, str]:
    email = require_email(request)
    return {"email": email}


@app.post("/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    sid = request.cookies.get(settings.AUTH_COOKIE_NAME)
    store.revoke(sid)
    resp = JSONResponse({"ok": True})
    clear_session_cookie(resp)
    return resp


@app.post("/convert")
async def convert(request: Request, file: UploadFile = File(...)) -> Response:
    rid = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    email = require_email(request)
    client = request.client.host if request.client else None
    name = file.filename or "upload.pdf"
    log.info(
        "rid=%s step=convert.accept email=%s filename=%r content_type=%r",
        rid,
        email,
        name,
        file.content_type,
    )

    if not name.lower().endswith(".pdf"):
        log.warning("rid=%s step=convert.reject reason=not_pdf filename=%r", rid, name)
        raise HTTPException(status_code=400, detail="ожидается файл PDF")

    raw = await file.read()
    log.info("rid=%s step=convert.read bytes=%d", rid, len(raw))
    if not raw:
        log.warning("rid=%s step=convert.reject reason=empty", rid)
        raise HTTPException(status_code=400, detail="пустой файл")
    if len(raw) > settings.MAX_BYTES:
        log.warning(
            "rid=%s step=convert.reject reason=too_large bytes=%d max=%d",
            rid,
            len(raw),
            settings.MAX_BYTES,
        )
        raise HTTPException(status_code=400, detail=f"файл слишком большой (макс. {settings.MAX_BYTES} байт)")

    input_path = save_input_pdf(rid, raw, name)
    write_meta(
        rid,
        {
            "status": "accepted",
            "email": email,
            "filename": name,
            "client": client,
            "input_bytes": len(raw),
            "input_path": str(input_path),
        },
    )

    result = await convert_pdf_bytes(raw, name, request_id=rid)
    if isinstance(result, ConvertFail):
        write_meta(
            rid,
            {
                "status": "fail",
                "email": email,
                "filename": name,
                "client": client,
                "input_bytes": len(raw),
                "input_path": str(input_path),
                "error_status": result.status_code,
                "error_detail": result.detail,
            },
        )
        log.warning(
            "rid=%s step=convert.fail status=%s detail=%r",
            rid,
            result.status_code,
            result.detail,
        )
        raise HTTPException(status_code=result.status_code, detail=result.detail)

    assert isinstance(result, ConvertOk)
    result_path = save_result_xlsx(rid, result.content, result.filename)
    write_meta(
        rid,
        {
            "status": "ok",
            "email": email,
            "filename": name,
            "client": client,
            "input_bytes": len(raw),
            "input_path": str(input_path),
            "result_filename": result.filename,
            "result_bytes": len(result.content),
            "result_path": str(result_path),
        },
    )
    log.info(
        "rid=%s step=convert.ok email=%s out=%r xlsx_bytes=%d job=%s",
        rid,
        email,
        result.filename,
        len(result.content),
        result_path.parent,
    )
    headers = {
        "Content-Disposition": content_disposition_attachment(result.filename),
        "X-Request-Id": rid,
    }
    return Response(content=result.content, media_type=XLSX_TYPE, headers=headers)
