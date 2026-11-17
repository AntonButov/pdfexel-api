from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdfexel_api import settings
from pdfexel_api.api import app
from pdfexel_api.auth_store import store
from pdfexel_api.pipeline import ConvertOk

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()
    client.cookies.clear()


def _login(email: str = "user@example.com") -> str:
    sid = store.create_session(email)
    client.cookies.set(settings.AUTH_COOKIE_NAME, sid)
    return sid


def test_request_code_sends_otp() -> None:
    with patch("pdfexel_api.api.send_otp") as send:
        r = client.post("/auth/request-code", json={"email": "User@Example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    send.assert_called_once()
    assert send.call_args.args[0] == "user@example.com"
    assert len(send.call_args.args[1]) == 6


def test_request_code_invalid_email() -> None:
    r = client.post("/auth/request-code", json={"email": "not-an-email"})
    assert r.status_code == 400


def test_verify_sets_cookie() -> None:
    code = store.issue_code("user@example.com")
    with patch.object(settings, "AUTH_COOKIE_SECURE", False):
        r = client.post(
            "/auth/verify",
            json={"email": "user@example.com", "code": code},
        )
    assert r.status_code == 200
    assert r.json()["email"] == "user@example.com"
    assert settings.AUTH_COOKIE_NAME in r.cookies


def test_verify_bad_code() -> None:
    store.issue_code("user@example.com")
    r = client.post(
        "/auth/verify",
        json={"email": "user@example.com", "code": "000000"},
    )
    assert r.status_code == 400


def test_convert_requires_auth() -> None:
    r = client.post("/convert", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 401
    assert r.json()["detail"] == "auth_required"


def test_convert_with_session_ok(tmp_path) -> None:
    _login()
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


def test_auth_me_and_logout() -> None:
    _login("a@b.co")
    assert client.get("/auth/me").json() == {"email": "a@b.co"}
    with patch.object(settings, "AUTH_COOKIE_SECURE", False):
        r = client.post("/auth/logout")
    assert r.status_code == 200
    assert client.get("/auth/me").status_code == 401
