# Email OTP Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate `POST /convert` behind email OTP + HttpOnly cookie session; without session return 401 and skip the pipeline.

**Architecture:** In-memory pending codes + sessions in `pdfexel-api` on VPS 33; SMTP via `mail.antonbutov.com`; landing on 206 shows OTP modal and sends cookies with `credentials: "include"`.

**Tech Stack:** FastAPI, stdlib `smtplib`/`email`, httpx TestClient, vanilla JS on landing.

**Spec:** `docs/superpowers/specs/2026-11-17-email-otp-auth-design.md`

## Global Constraints

- Cookie name: `pdfexel_session` — HttpOnly, Secure (prod), SameSite=Lax, Path=/, Max-Age 7 days
- OTP: 6 digits, TTL 600s, max 5 verify attempts, rate limit 5 / 15 min per IP and per email
- `request-code` always returns `{ok:true}` (no email enumeration)
- Convert without session → 401 `auth_required`, no stand calls
- Deploy host stays `80.87.196.33`; no commit unless user asks

## File map

| File | Role |
|------|------|
| `pdfexel_api/settings.py` | SMTP + auth env |
| `pdfexel_api/auth_store.py` | In-memory codes/sessions/rate limits |
| `pdfexel_api/mailer.py` | Send OTP email |
| `pdfexel_api/api.py` | `/auth/*` + gate `/convert` |
| `tests/test_auth.py` | Auth + gated convert tests |
| `tests/test_api.py` | Existing convert tests get session cookie |
| `docker-compose.yml` | Pass SMTP env |
| `README.md` | Auth + env docs |
| `pdf-to-excel-landing/js/cta.js` | credentials + 401 → modal |
| `pdf-to-excel-landing/js/auth.js` | Modal OTP UI |
| `pdf-to-excel-landing/css/main.css` | Modal styles |
| `pdf-to-excel-landing/index.html`, `a/index.html` | Include auth.js |

---

### Task 1: Auth store + settings + mailer

**Files:** Create `pdfexel_api/auth_store.py`, `pdfexel_api/mailer.py`; Modify `pdfexel_api/settings.py`

- [ ] AuthStore: issue/verify codes (hashed), sessions, rate limits
- [ ] settings: SMTP_*, AUTH_*
- [ ] mailer.send_otp(email, code) via smtplib
- [ ] Unit tests in `tests/test_auth.py` for store (no SMTP)

### Task 2: API endpoints + convert gate

**Files:** Modify `pdfexel_api/api.py`, `tests/test_api.py`, `tests/test_auth.py`

- [ ] `POST /auth/request-code`, `/auth/verify`, `/auth/me`, `/auth/logout`
- [ ] Convert requires session before pipeline
- [ ] Fix existing convert tests with session helper
- [ ] `pytest -q` (unit; corpus still runs)

### Task 3: Docker/README

**Files:** `docker-compose.yml`, `README.md`

- [ ] env for SMTP from host `.env`
- [ ] Document secrets on 33

### Task 4: Landing OTP UI

**Files:** landing `js/auth.js`, `js/cta.js`, `css/main.css`, both HTML

- [ ] Modal email → code → verify
- [ ] convert with credentials; on 401 open modal and retry

### Task 5: Verify

- [ ] `pytest -q` in pdfexel-api
- [ ] Note: push + SMTP `.env` on 33 for live OTP
