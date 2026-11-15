# pdfexel-api

Оркестратор **PDF → Excel** для [pdfexel.ru](https://pdfexel.ru):

`POST /convert` (multipart PDF) → `pdf-stand` → `json-stand` → `.xlsx` attachment.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | `{"status":"ok"}` |
| POST | `/convert` | multipart `file` (PDF) → XLSX download |

Env:

- `PDF_STAND_URL` (default `http://127.0.0.1:8131/parse`)
- `JSON_STAND_URL` (default `http://127.0.0.1:8132/convert`)
- `STAND_TIMEOUT_S` (default `120`)
- `MAX_UPLOAD_BYTES` (default 25 MB)

## Local

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q   # unit + 20-PDF corpus gate (required on every converter change / CI)
uvicorn pdfexel_api.api:app --port 8133
```

Corpus: `tests/corpus/pass/*.pdf` + `expected/*.json` + `golden/*.xlsx` — see `tests/test_corpus.py`.

## Deploy

Docker Compose publishes **8133→8080** on `80.87.196.33` (`/opt/pdfexel-api`).  
CI: push `main` → test → rsync + `docker compose up -d --build`.

Secrets: `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_USER` (same as other stands).
