from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from pdfexel_api import settings


@dataclass
class PendingCode:
    code_hash: str
    expires_at: float
    attempts: int


@dataclass
class Session:
    email: str
    expires_at: float


class AuthStore:
    """Process-local OTP codes and sessions (wiped on restart)."""

    def __init__(self) -> None:
        self._codes: dict[str, PendingCode] = {}
        self._sessions: dict[str, Session] = {}
        self._rate: dict[str, list[float]] = {}

    def clear(self) -> None:
        self._codes.clear()
        self._sessions.clear()
        self._rate.clear()

    def _hash_code(self, email: str, code: str) -> str:
        msg = f"{email}:{code}".encode("utf-8")
        return hmac.new(settings.AUTH_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def check_rate_limit(self, key: str) -> bool:
        """Return True if allowed; False if over limit. Records a hit when allowed."""
        now = time.time()
        window = settings.AUTH_RATE_WINDOW_SEC
        limit = settings.AUTH_RATE_LIMIT
        k = (key or "unknown").strip().lower() or "unknown"
        hits = [t for t in self._rate.get(k, []) if now - t < window]
        if len(hits) >= limit:
            self._rate[k] = hits
            return False
        hits.append(now)
        self._rate[k] = hits
        return True

    def issue_code(self, email: str) -> str:
        email_n = email.strip().lower()
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._codes[email_n] = PendingCode(
            code_hash=self._hash_code(email_n, code),
            expires_at=time.time() + settings.AUTH_CODE_TTL_SEC,
            attempts=0,
        )
        return code

    def verify_code(self, email: str, code: str) -> bool:
        email_n = email.strip().lower()
        code_n = (code or "").strip()
        pending = self._codes.get(email_n)
        if pending is None:
            return False
        if time.time() > pending.expires_at:
            self._codes.pop(email_n, None)
            return False
        if pending.attempts >= settings.AUTH_CODE_MAX_ATTEMPTS:
            self._codes.pop(email_n, None)
            return False
        pending.attempts += 1
        expected = pending.code_hash
        got = self._hash_code(email_n, code_n)
        if not hmac.compare_digest(expected, got):
            if pending.attempts >= settings.AUTH_CODE_MAX_ATTEMPTS:
                self._codes.pop(email_n, None)
            return False
        self._codes.pop(email_n, None)
        return True

    def create_session(self, email: str) -> str:
        email_n = email.strip().lower()
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = Session(
            email=email_n,
            expires_at=time.time() + settings.AUTH_SESSION_DAYS * 86400,
        )
        return sid

    def get_email(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        sess = self._sessions.get(session_id)
        if sess is None:
            return None
        if time.time() > sess.expires_at:
            self._sessions.pop(session_id, None)
            return None
        return sess.email

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)


store = AuthStore()
