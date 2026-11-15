from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import httpx

from pdfexel_api.settings import TIMEOUT_S, json_stand_url, pdf_stand_url


@dataclass
class ConvertOk:
    filename: str
    content: bytes


@dataclass
class ConvertFail:
    status_code: int
    detail: str


async def convert_pdf_bytes(pdf_bytes: bytes, filename: str) -> ConvertOk | ConvertFail:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename or "result"
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        parse_resp = await client.post(
            pdf_stand_url(),
            files={"file": (filename or "upload.pdf", pdf_bytes, "application/pdf")},
        )
        if parse_resp.status_code >= 400:
            return ConvertFail(parse_resp.status_code, _detail(parse_resp, "pdf-stand error"))

        try:
            parsed = parse_resp.json()
        except json.JSONDecodeError:
            return ConvertFail(502, "pdf-stand returned non-JSON")

        if not parsed.get("ok"):
            errors = parsed.get("errors") or []
            msg = errors[0].get("message") if errors else "не удалось разобрать PDF"
            return ConvertFail(422, str(msg))

        tables = parsed.get("tables") or []
        if not tables:
            return ConvertFail(422, "в PDF не найдено таблиц")

        payload = {"tables": tables}
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        xlsx_resp = await client.post(
            json_stand_url(),
            files={"file": (f"{stem}.json", json_bytes, "application/json")},
        )
        if xlsx_resp.status_code >= 400:
            return ConvertFail(xlsx_resp.status_code, _detail(xlsx_resp, "json-stand error"))

        try:
            converted = xlsx_resp.json()
        except json.JSONDecodeError:
            return ConvertFail(502, "json-stand returned non-JSON")

        if not converted.get("ok"):
            errors = converted.get("errors") or []
            msg = errors[0].get("message") if errors else "не удалось собрать Excel"
            return ConvertFail(422, str(msg))

        b64 = converted.get("workbook_base64")
        if not b64:
            return ConvertFail(502, "json-stand did not return workbook")

        try:
            content = base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            return ConvertFail(502, "invalid workbook_base64")

        if not content:
            return ConvertFail(502, "empty workbook")

        return ConvertOk(filename=f"{stem}.xlsx", content=content)


def _detail(resp: httpx.Response, fallback: str) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])
    except Exception:  # noqa: BLE001
        pass
    text = (resp.text or "").strip()
    return text[:300] if text else fallback
