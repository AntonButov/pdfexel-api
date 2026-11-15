from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

from pdfexel_api.pipeline import ConvertFail, ConvertOk, convert_pdf_bytes
from pdfexel_api.settings import MAX_BYTES

app = FastAPI(title="pdfexel-api", version="0.1.0")

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/convert")
async def convert(file: UploadFile = File(...)) -> Response:
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="ожидается файл PDF")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="пустой файл")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"файл слишком большой (макс. {MAX_BYTES} байт)")

    result = await convert_pdf_bytes(raw, name)
    if isinstance(result, ConvertFail):
        raise HTTPException(status_code=result.status_code, detail=result.detail)

    assert isinstance(result, ConvertOk)
    headers = {"Content-Disposition": f'attachment; filename="{result.filename}"'}
    return Response(content=result.content, media_type=XLSX_TYPE, headers=headers)
