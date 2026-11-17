# Email OTP auth — design

**Date:** 2026-11-17  
**Status:** approved  
**Repos:** pdfexel-api + pdf-to-excel-landing  
**Approved approach:** in-memory store + HttpOnly cookie session (option 1)

## Goal

Require email login before any PDF→Excel processing. Without a valid session, `POST /convert` returns 401 and does not run the pipeline.

## Non-goals

- Passwords, OAuth, magic links
- Billing / convert quotas (later)
- Persistent DB (SQLite/Postgres) — sessions reset on process restart
- Separate auth microservice

## Actors and deploy

| Piece | Host | Role |
|-------|------|------|
| Landing | `206.223.250.251` → `/var/www/pdfexel.ru` | UI, OTP modal, cookie with convert |
| API | `80.87.196.33` → `/opt/pdfexel-api` port **8133** | OTP, sessions, gated convert |
| Nginx | landing host | `location /api/` → `http://80.87.196.33:8133/` |

SMTP: same pattern as gosphoto — `mail.antonbutov.com`, from `mail@antonbutov.com` (or dedicated `noreply@…` if configured). Secrets via env / GitHub Actions deploy secrets on 33.

## User flow

1. User picks PDF and clicks convert (or drop).
2. If no session (or convert returns 401): show modal — email → «Получить код».
3. `POST /api/auth/request-code` with `{ "email": "…" }`.
4. User receives 6-digit code (TTL 10 minutes).
5. User enters code → `POST /api/auth/verify` → Set-Cookie `pdfexel_session`.
6. Retry convert with `credentials: "include"`.
7. Without cookie / invalid session → 401, no pipeline work.

## API

All under existing `/api/` proxy (backend paths without `/api` prefix, same as today).

### `POST /auth/request-code`

**Body:** `{ "email": string }`  
**Behavior:**

- Normalize email (trim, lower).
- Validate format; reject invalid with 400.
- Rate-limit: per IP and per email (e.g. 5 / 15 min each).
- Generate cryptographically random 6-digit code; store hashed (or raw with short TTL in memory — prefer hash).
- Send email via SMTP; always return **200** with generic `{ "ok": true }` (no email enumeration).
- Do not start convert.

### `POST /auth/verify`

**Body:** `{ "email": string, "code": string }`  
**Behavior:**

- Check code against store; max attempts (e.g. 5) then invalidate.
- On success: create session id (random 32+ bytes), store `{ session_id → email, expires_at }`.
- Set cookie:
  - Name: `pdfexel_session`
  - HttpOnly, Secure, SameSite=Lax
  - Path=/
  - Max-Age: 7 days
  - Domain: omit (host-only on `pdfexel.ru` via proxy — cookie set by API response through same-origin `/api/`; **must** set cookie on response that browser associates with `pdfexel.ru`. Prefer setting cookie from API with no Domain, Path=/ so it applies to apex when proxied.)

**Cookie via reverse proxy:** responses from `/api/auth/verify` go through nginx on pdfexel.ru, so `Set-Cookie` without Domain applies to `pdfexel.ru`. Good.

### `POST /convert` (change)

- Require valid `pdfexel_session` cookie.
- Missing/invalid → **401** `{ "detail": "auth_required" }` — **no** pdf-stand / json-stand calls, no job write.
- Valid → existing pipeline; optionally attach `email` to `meta.json`.

### `GET /auth/me` (optional, small)

- 200 `{ "email": "…" }` if session ok, else 401. Helps landing skip modal.

### `POST /auth/logout` (optional)

- Clear session store entry + expire cookie.

## In-memory store

Process-local dicts (or small classes):

- `pending_codes[email] = { code_hash, expires, attempts }`
- `sessions[session_id] = { email, expires }`
- Periodic or lazy cleanup of expired entries
- Docker restart wipes auth state (accepted)

## Frontend (`pdf-to-excel-landing`)

- `js/cta.js`: `fetch(..., { credentials: "include" })`
- On 401: open auth modal; after verify success, retry convert once
- Modal: email, «код», resend with cooldown
- No Metrika goal until successful convert (unchanged)
- Keep both variants `/` and `/a` wired to same CTA/auth JS

## Config (env on 33)

| Var | Purpose |
|-----|---------|
| `SMTP_HOST` | default `mail.antonbutov.com` |
| `SMTP_PORT` | 587 / 465 |
| `SMTP_USER` / `SMTP_PASSWORD` | auth |
| `SMTP_FROM` | `mail@antonbutov.com` |
| `AUTH_SESSION_DAYS` | default 7 |
| `AUTH_CODE_TTL_SEC` | default 600 |
| `AUTH_COOKIE_SECURE` | default true (false only for local) |

## Security

- Codes: 6 digits, 10 min TTL, attempt cap, rate limits
- Sessions: unguessable id, HttpOnly + Secure + SameSite=Lax
- Convert gate before any heavy work
- No plaintext code in logs (log email + rid only)
- CORS not needed (same-origin `/api/`)

## Tests

- Unit: request-code rate limit, verify success/fail, convert 401 without cookie, convert 200 with session (pipeline mocked)
- No real SMTP in CI (mock sender)
- Existing corpus tests unchanged (auth bypass fixture or test dependency injection)

## Rollout

1. Implement + test in pdfexel-api; deploy CI to 33
2. Landing modal + credentials; deploy to 206
3. Set SMTP secrets on 33 / GitHub if missing
4. Smoke: request code → verify → convert on pdfexel.ru

## Success criteria

- Anonymous `POST /convert` → 401, zero stand calls
- Verified user can convert with cookie
- Email delivers OTP in normal conditions
