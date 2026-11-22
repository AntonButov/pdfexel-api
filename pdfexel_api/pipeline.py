from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass

import httpx

from pdfexel_api.settings import TIMEOUT_S, json_stand_url, pdf_stand_url

log = logging.getLogger("pdfexel_api.pipeline")


@dataclass
class ConvertOk:
    filename: str
    content: bytes


@dataclass
class ConvertFail:
    status_code: int
    detail: str
    code: str | None = None


async def convert_pdf_bytes(
    pdf_bytes: bytes,
    filename: str,
    *,
    request_id: str | None = None,
) -> ConvertOk | ConvertFail:
    rid = request_id or uuid.uuid4().hex[:12]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename or "result"
    t0 = time.perf_counter()
    pdf_url = pdf_stand_url()
    json_url = json_stand_url()

    log.info(
        "rid=%s step=start file=%r bytes=%d pdf_stand=%s json_stand=%s timeout_s=%s",
        rid,
        filename,
        len(pdf_bytes),
        pdf_url,
        json_url,
        TIMEOUT_S,
    )

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        log.info("rid=%s step=pdf_stand.request url=%s", rid, pdf_url)
        t_parse = time.perf_counter()
        try:
            parse_resp = await client.post(
                pdf_url,
                files={"file": (filename or "upload.pdf", pdf_bytes, "application/pdf")},
            )
        except httpx.TimeoutException as exc:
            log.error("rid=%s step=pdf_stand.timeout err=%s", rid, exc)
            return ConvertFail(504, "таймаут pdf-stand")
        except httpx.HTTPError as exc:
            log.error("rid=%s step=pdf_stand.http_error err=%s", rid, exc)
            return ConvertFail(502, f"pdf-stand недоступен: {exc}")

        parse_ms = int((time.perf_counter() - t_parse) * 1000)
        log.info(
            "rid=%s step=pdf_stand.response status=%s ms=%d body_bytes=%d",
            rid,
            parse_resp.status_code,
            parse_ms,
            len(parse_resp.content),
        )

        if parse_resp.status_code >= 400:
            detail = _detail(parse_resp, "pdf-stand error")
            log.warning("rid=%s step=pdf_stand.fail detail=%r", rid, detail)
            return ConvertFail(parse_resp.status_code, detail)

        try:
            parsed = parse_resp.json()
        except json.JSONDecodeError:
            log.error("rid=%s step=pdf_stand.non_json", rid)
            return ConvertFail(502, "pdf-stand returned non-JSON")

        if not parsed.get("ok"):
            errors = parsed.get("errors") or []
            err0 = errors[0] if errors else {}
            code = err0.get("code") if isinstance(err0, dict) else None
            msg = err0.get("message") if isinstance(err0, dict) else "не удалось разобрать PDF"
            if parsed.get("scanned") or code == "scanned_pdf":
                log.warning("rid=%s step=pdf_stand.scanned detail=%r", rid, msg)
                return ConvertFail(
                    422,
                    str(msg or "PDF выглядит как скан — нужен OCR"),
                    code="scanned_pdf",
                )
            log.warning("rid=%s step=pdf_stand.not_ok detail=%r", rid, msg)
            return ConvertFail(422, str(msg), code=str(code) if code else None)

        tables = parsed.get("tables") or []
        pages = parsed.get("page_count") or parsed.get("pages")
        log.info(
            "rid=%s step=pdf_stand.ok tables=%d pages=%s scanned=%s",
            rid,
            len(tables),
            pages,
            bool(parsed.get("scanned")),
        )
        if not tables:
            if parsed.get("scanned"):
                log.warning("rid=%s step=pdf_stand.scanned_no_tables", rid)
                return ConvertFail(
                    422,
                    "PDF выглядит как скан — нужен OCR",
                    code="scanned_pdf",
                )
            log.warning("rid=%s step=pdf_stand.no_tables", rid)
            return ConvertFail(422, "в PDF не найдено таблиц", code="no_tables")

        payload = {"tables": tables}
        if parsed.get("sheets"):
            payload["sheets"] = parsed["sheets"]
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        log.info(
            "rid=%s step=json_stand.request url=%s json_bytes=%d",
            rid,
            json_url,
            len(json_bytes),
        )

        t_xlsx = time.perf_counter()
        try:
            xlsx_resp = await client.post(
                json_url,
                files={"file": (f"{stem}.json", json_bytes, "application/json")},
            )
        except httpx.TimeoutException as exc:
            log.error("rid=%s step=json_stand.timeout err=%s", rid, exc)
            return ConvertFail(504, "таймаут json-stand")
        except httpx.HTTPError as exc:
            log.error("rid=%s step=json_stand.http_error err=%s", rid, exc)
            return ConvertFail(502, f"json-stand недоступен: {exc}")

        xlsx_ms = int((time.perf_counter() - t_xlsx) * 1000)
        log.info(
            "rid=%s step=json_stand.response status=%s ms=%d body_bytes=%d",
            rid,
            xlsx_resp.status_code,
            xlsx_ms,
            len(xlsx_resp.content),
        )

        if xlsx_resp.status_code >= 400:
            detail = _detail(xlsx_resp, "json-stand error")
            log.warning("rid=%s step=json_stand.fail detail=%r", rid, detail)
            return ConvertFail(xlsx_resp.status_code, detail)

        try:
            converted = xlsx_resp.json()
        except json.JSONDecodeError:
            log.error("rid=%s step=json_stand.non_json", rid)
            return ConvertFail(502, "json-stand returned non-JSON")

        if not converted.get("ok"):
            errors = converted.get("errors") or []
            msg = errors[0].get("message") if errors else "не удалось собрать Excel"
            log.warning("rid=%s step=json_stand.not_ok detail=%r", rid, msg)
            return ConvertFail(422, str(msg))

        b64 = converted.get("workbook_base64")
        if not b64:
            log.error("rid=%s step=json_stand.missing_workbook", rid)
            return ConvertFail(502, "json-stand did not return workbook")

        try:
            content = base64.b64decode(b64)
        except Exception as exc:  # noqa: BLE001
            log.error("rid=%s step=workbook.decode_fail err=%s", rid, exc)
            return ConvertFail(502, "invalid workbook_base64")

        if not content:
            log.error("rid=%s step=workbook.empty", rid)
            return ConvertFail(502, "empty workbook")

        total_ms = int((time.perf_counter() - t0) * 1000)
        out_name = f"{stem}.xlsx"
        log.info(
            "rid=%s step=done out=%r xlsx_bytes=%d total_ms=%d parse_ms=%d xlsx_ms=%d",
            rid,
            out_name,
            len(content),
            total_ms,
            parse_ms,
            xlsx_ms,
        )
        return ConvertOk(filename=out_name, content=content)


def _detail(resp: httpx.Response, fallback: str) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])
    except Exception:  # noqa: BLE001
        pass
    text = (resp.text or "").strip()
    return text[:300] if text else fallback
