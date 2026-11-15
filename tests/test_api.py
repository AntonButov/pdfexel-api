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
    assert "таблиц" in result.detail


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
