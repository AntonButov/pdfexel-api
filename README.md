# pdfexel-api

Оркестратор **PDF → Excel** для [pdfexel.ru](https://pdfexel.ru):

Email OTP → cookie session → `POST /convert` (multipart PDF) → `pdf-stand` → `json-stand` → `.xlsx`.

Без сессии `POST /convert` отвечает **401** и не запускает пайплайн.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | `{"status":"ok"}` |
| POST | `/auth/request-code` | `{email}` → OTP на почту |
| POST | `/auth/verify` | `{email,code}` → Set-Cookie `pdfexel_session` |
| GET | `/auth/me` | текущий email или 401 |
| POST | `/auth/logout` | сброс сессии |
| POST | `/convert` | multipart `file` (PDF) → XLSX (**нужна сессия**) |

Env:

- `PDF_STAND_URL` (default `http://127.0.0.1:8131/parse`)
- `JSON_STAND_URL` (default `http://127.0.0.1:8132/convert`)
- `STAND_TIMEOUT_S` (default `120`)
- `MAX_UPLOAD_BYTES` (default 25 MB)
- `JOBS_DIR` (default `/data/jobs`) — на VPS: `/var/lib/pdfexel/jobs`
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` — OTP (как gosphoto: `mail.antonbutov.com`)
- `AUTH_SECRET` — HMAC для хеша кода
- `AUTH_COOKIE_SECURE` — `1` в проде, `0` для локального http

## Local

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export AUTH_COOKIE_SECURE=0 SMTP_PASSWORD=…   # для живой почты
pytest -q
uvicorn pdfexel_api.api:app --port 8133
```

Corpus: `tests/corpus/pass/*.pdf` + `expected/*.json` + `golden/*.xlsx` — see `tests/test_corpus.py`.

## Deploy

Docker Compose publishes **8133→8080** on `80.87.196.33` (`/opt/pdfexel-api`).  
CI: push `main` → test → rsync + `docker compose up -d --build`.

На сервере в `/opt/pdfexel-api/.env` (не в git):

```
SMTP_PASSWORD=…
AUTH_SECRET=…
```

Secrets CI: `DEPLOY_SSH_PRIVATE_KEY`, `DEPLOY_USER`.
