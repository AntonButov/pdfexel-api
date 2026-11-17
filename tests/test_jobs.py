from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdfexel_api import settings
from pdfexel_api.api import app
from pdfexel_api.auth_store import store
from pdfexel_api.pipeline import ConvertOk


client = TestClient(app)


@pytest.fixture(autouse=True)
def _auth_session():
    store.clear()
    sid = store.create_session("test@pdfexel.ru")
    client.cookies.set(settings.AUTH_COOKIE_NAME, sid)
    yield
    store.clear()
    client.cookies.clear()


def test_convert_persists_input_and_result(tmp_path: Path) -> None:
    xlsx = b"PK\x03\x04workbook-bytes"

    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertOk(filename="demo.xlsx", content=xlsx)

    with (
        patch("pdfexel_api.settings.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post(
            "/convert",
            files={"file": ("demo.pdf", b"%PDF-1.4 demo", "application/pdf")},
        )

    assert r.status_code == 200
    rid = r.headers["x-request-id"]
    day_dirs = list(tmp_path.iterdir())
    assert len(day_dirs) == 1
    job = day_dirs[0] / rid
    assert (job / "input.pdf").read_bytes() == b"%PDF-1.4 demo"
    assert (job / "result.xlsx").read_bytes() == xlsx
    assert (job / "demo.pdf").exists()
    assert (job / "demo.xlsx").exists()
    meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "ok"
    assert meta["request_id"] == rid
    assert meta["input_bytes"] == len(b"%PDF-1.4 demo")
    assert meta["result_bytes"] == len(xlsx)


def test_convert_fail_still_keeps_input(tmp_path: Path) -> None:
    from pdfexel_api.pipeline import ConvertFail

    async def fake_convert(pdf_bytes: bytes, filename: str, **kwargs):
        return ConvertFail(422, "в PDF не найдено таблиц")

    with (
        patch("pdfexel_api.settings.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.jobs.jobs_dir", return_value=tmp_path),
        patch("pdfexel_api.api.convert_pdf_bytes", side_effect=fake_convert),
    ):
        r = client.post(
            "/convert",
            files={"file": ("empty.pdf", b"%PDF empty", "application/pdf")},
        )

    assert r.status_code == 422
    rid = r.headers.get("x-request-id") or r.headers.get("X-Request-Id")
    # middleware always sets header on response
    assert rid
    job = next(tmp_path.iterdir()) / rid
    assert (job / "input.pdf").read_bytes() == b"%PDF empty"
    meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "fail"
    assert meta["error_detail"] == "в PDF не найдено таблиц"
    assert not (job / "result.xlsx").exists()
