from __future__ import annotations

import logging
import re
import time
import uuid
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from pdfexel_api.jobs import save_input_pdf, save_result_xlsx, write_meta
from pdfexel_api.logging_setup import configure_logging
from pdfexel_api.pipeline import ConvertFail, ConvertOk, convert_pdf_bytes
from pdfexel_api.settings import MAX_BYTES

configure_logging()
log = logging.getLogger("pdfexel_api.api")

app = FastAPI(title="pdfexel-api", version="0.1.0")

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def content_disposition_attachment(filename: str) -> str:
    """RFC 6266 / 5987: ASCII fallback + UTF-8 filename* (Starlette is latin-1)."""
    ascii_name = _SAFE_FILENAME.sub("_", filename).strip("._") or "download.xlsx"
    if not ascii_name.lower().endswith(".xlsx"):
        ascii_name = f"{ascii_name}.xlsx"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


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


@app.post("/convert")
async def convert(request: Request, file: UploadFile = File(...)) -> Response:
    rid = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    client = request.client.host if request.client else None
    name = file.filename or "upload.pdf"
    log.info("rid=%s step=convert.accept filename=%r content_type=%r", rid, name, file.content_type)

    if not name.lower().endswith(".pdf"):
        log.warning("rid=%s step=convert.reject reason=not_pdf filename=%r", rid, name)
        raise HTTPException(status_code=400, detail="ожидается файл PDF")

    raw = await file.read()
    log.info("rid=%s step=convert.read bytes=%d", rid, len(raw))
    if not raw:
        log.warning("rid=%s step=convert.reject reason=empty", rid)
        raise HTTPException(status_code=400, detail="пустой файл")
    if len(raw) > MAX_BYTES:
        log.warning("rid=%s step=convert.reject reason=too_large bytes=%d max=%d", rid, len(raw), MAX_BYTES)
        raise HTTPException(status_code=400, detail=f"файл слишком большой (макс. {MAX_BYTES} байт)")

    input_path = save_input_pdf(rid, raw, name)
    write_meta(
        rid,
        {
            "status": "accepted",
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
        "rid=%s step=convert.ok out=%r xlsx_bytes=%d job=%s",
        rid,
        result.filename,
        len(result.content),
        result_path.parent,
    )
    headers = {
        "Content-Disposition": content_disposition_attachment(result.filename),
        "X-Request-Id": rid,
    }
    return Response(content=result.content, media_type=XLSX_TYPE, headers=headers)
