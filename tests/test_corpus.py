from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pdfexel_api.pipeline import ConvertFail, ConvertOk, convert_pdf_bytes
from corpus_util import (
    GOLDEN_DIR,
    expected_matrices,
    expected_path,
    load_expected,
    parse_payload_from_expected,
    pass_pdfs,
    sheet_matrix,
    workbook_base64_response,
)


def _cases() -> list[pytest.ParameterSet]:
    cases = []
    for pdf in pass_pdfs():
        stem = pdf.stem
        if not expected_path(stem).exists():
            continue
        cases.append(pytest.param(stem, pdf, id=stem))
    return cases


@pytest.mark.parametrize("stem,pdf_path", _cases())
@pytest.mark.asyncio
async def test_corpus_convert_sequence(stem: str, pdf_path) -> None:
    """Full orchestrator path for every corpus PDF: pdf-stand → json-stand → xlsx cells."""
    expected = load_expected(stem)
    parse_payload = parse_payload_from_expected(expected)
    pdf_bytes = pdf_path.read_bytes()

    async def fake_post(url: str, files=None, **kwargs):
        url_s = str(url)
        if url_s.rstrip("/").endswith("/parse") or "8131" in url_s:
            return httpx.Response(200, json=parse_payload)
        if url_s.rstrip("/").endswith("/convert") or "8132" in url_s:
            assert files and "file" in files
            name, raw, *_rest = files["file"]
            assert str(name).endswith(".json")
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
            assert "tables" in payload
            assert len(payload["tables"]) == len(expected["tables"])
            return httpx.Response(200, json=workbook_base64_response(payload["tables"]))
        raise AssertionError(f"unexpected url: {url_s}")

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("pdfexel_api.pipeline.httpx.AsyncClient", return_value=mock_client):
        result = await convert_pdf_bytes(pdf_bytes, pdf_path.name, request_id=f"corpus-{stem}")

    assert isinstance(result, ConvertOk), getattr(result, "detail", result)
    assert result.filename == f"{stem}.xlsx"
    assert result.content[:2] == b"PK"
    assert mock_client.post.await_count == 2

    got = sheet_matrix(result.content)
    want = expected_matrices(expected)
    assert len(got) == len(want), f"{stem}: sheet count {len(got)} != {len(want)}"
    for i, (g, w) in enumerate(zip(got, want, strict=True), start=1):
        assert g == w, f"{stem} Table{i} cells mismatch\n got={g}\n want={w}"

    golden = GOLDEN_DIR / f"{stem}.xlsx"
    assert golden.exists(), f"missing golden xlsx for {stem}"
    # golden from live stands must open and have same sheet count / non-empty grid
    golden_sheets = sheet_matrix(golden.read_bytes())
    assert len(golden_sheets) == len(want)
    assert all(any(cell for row in sheet for cell in row) for sheet in golden_sheets)


def test_corpus_manifest_complete() -> None:
    pdfs = pass_pdfs()
    assert len(pdfs) >= 20, f"expected ≥20 pass PDFs, got {len(pdfs)}"
    missing_exp = [p.stem for p in pdfs if not expected_path(p.stem).exists()]
    missing_gold = [p.stem for p in pdfs if not (GOLDEN_DIR / f"{p.stem}.xlsx").exists()]
    assert not missing_exp, f"missing expected JSON: {missing_exp}"
    assert not missing_gold, f"missing golden xlsx: {missing_gold}"


@pytest.mark.asyncio
async def test_corpus_rejects_when_stand_returns_no_tables() -> None:
    pdf = pass_pdfs()[0]
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(
        return_value=httpx.Response(200, json={"ok": True, "tables": [], "pages": 1, "errors": []})
    )
    with patch("pdfexel_api.pipeline.httpx.AsyncClient", return_value=mock_client):
        result = await convert_pdf_bytes(pdf.read_bytes(), pdf.name)
    assert isinstance(result, ConvertFail)
    assert result.status_code == 422
