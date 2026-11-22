from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from pdfexel_api.api import app
from pdfexel_api.pipeline import ConvertFail, ConvertOk, convert_pdf_bytes


client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_convert_rejects_non_pdf() -> None:
    r = client.post("/convert", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]


def test_convert_rejects_empty() -> None:
    r = client.post("/convert", files={"file": ("x.pdf", b"", "application/pdf")})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_happy_path() -> None:
    parse_payload = {
        "ok": True,
        "tables": [{"name": "t1", "headers": ["a"], "rows": [["1"]]}],
    }
    xlsx_bytes = b"PK\x03\x04fake-xlsx"
    convert_payload = {
        "ok": True,
        "workbook_base64": base64.b64encode(xlsx_bytes).decode("ascii"),
    }

    parse_resp = httpx.Response(200, json=parse_payload)
    convert_resp = httpx.Response(200, json=convert_payload)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(side_effect=[parse_resp, convert_resp])

    with patch("pdfexel_api.pipeline.httpx.AsyncClient", return_value=mock_client):
        result = await convert_pdf_bytes(b"%PDF-1.4", "table.pdf")

    assert isinstance(result, ConvertOk)
    assert result.filename == "table.xlsx"
    assert result.content == xlsx_bytes
    assert mock_client.post.await_count == 2


@pytest.mark.asyncio
async def test_pipeline_no_tables() -> None:
    parse_resp = httpx.Response(200, json={"ok": True, "tables": []})
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=parse_resp)

    with patch("pdfexel_api.pipeline.httpx.AsyncClient", return_value=mock_client):
        result = await convert_pdf_bytes(b"%PDF", "empty.pdf")

    assert isinstance(result, ConvertFail)
    assert result.status_code == 422
    assert result.code == "no_tables"
    assert "таблиц" in result.detail


@pytest.mark.asyncio
async def test_pipeline_scanned_pdf() -> None:
    parse_resp = httpx.Response(
        200,
        json={
            "ok": False,
            "scanned": True,
            "tables": [],
            "errors": [{"code": "scanned_pdf", "message": "PDF выглядит как скан — нужен OCR"}],
        },
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=parse_resp)

    with patch("pdfexel_api.pipeline.httpx.AsyncClient", return_value=mock_client):
        result = await convert_pdf_bytes(b"%PDF", "scan.pdf")

    assert isinstance(result, ConvertFail)
    assert result.code == "scanned_pdf"
    assert "скан" in result.detail.lower() or "OCR" in result.detail


def test_convert_scanned_returns_offer(tmp_path) -> None:
    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertFail(422, "PDF выглядит как скан — нужен OCR", code="scanned_pdf")

    with (
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post("/convert", files={"file": ("scan.pdf", b"%PDF", "application/pdf")})

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "scanned_pdf"
    assert detail["offer"]["price_rub"] == 299
    assert detail["offer"]["period"] == "month"
    assert "мес" in detail["offer"]["cta"]


def test_convert_no_tables_returns_offer(tmp_path) -> None:
    """Vector PDF with no detected tables → paid offer (same funnel as scan)."""

    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertFail(422, "в PDF не найдено таблиц", code="no_tables")

    with (
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post(
            "/convert",
            files={"file": ("vector-table.pdf", b"%PDF", "application/pdf")},
        )

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "no_tables"
    assert detail["offer"]["price_rub"] == 299
    assert detail["offer"]["period"] == "month"
    assert "мес" in detail["offer"]["cta"]
    assert detail.get("message")


def test_ocr_interest_appends(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "ocr-interest.jsonl"
    monkeypatch.setenv("OCR_INTEREST_LOG", str(log_path))
    # reload path helper picks env at call time via ocr_interest_log()
    r = client.post(
        "/ocr-interest",
        json={
            "filename": "УПД 12.pdf",
            "source": "scan_offer_pay",
            "offer": "subscription_299",
            "price_rub": 299,
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    import json

    row = json.loads(line)
    assert row["filename"] == "УПД 12.pdf"
    assert row["source"] == "scan_offer_pay"
    assert row["offer"] == "subscription_299"
    assert row["price_rub"] == 299


def test_convert_endpoint_streams_xlsx(tmp_path) -> None:
    xlsx = b"PK\x03\x04workbook"

    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertOk(filename="demo.xlsx", content=xlsx)

    with (
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post("/convert", files={"file": ("demo.pdf", b"%PDF", "application/pdf")})

    assert r.status_code == 200
    assert r.content == xlsx
    assert "spreadsheetml" in r.headers["content-type"]
    assert "demo.xlsx" in r.headers["content-disposition"]


def test_convert_cyrillic_filename_does_not_500(tmp_path) -> None:
    xlsx = b"PK\x03\x04workbook"
    out_name = "счет Резиденция детства.xlsx"

    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertOk(filename=out_name, content=xlsx)

    with (
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post(
            "/convert",
            files={"file": ("счет Резиденция детства.pdf", b"%PDF", "application/pdf")},
        )

    assert r.status_code == 200
    assert r.content == xlsx
    cd = r.headers["content-disposition"]
    assert "filename=" in cd
    assert "filename*=UTF-8''" in cd
    assert "%D1%81%D1%87%D0%B5%D1%82" in cd
    cd.encode("latin-1")
