"""app/security/sessions.py — server-side login sessions (audit F5/F6).

The browser receives two cookies at login:

  * ``cdt_session`` — httpOnly, the opaque session token. Only its SHA-256
    digest is persisted (`AuthSession.token_hash`), so a leaked database
    cannot mint live sessions.
  * ``cdt_csrf`` — JS-readable, the CSRF double-submit token. Mutating
    requests must echo it in the ``X-CSRF-Token`` header; SameSite=Lax plus
    the header check blocks cross-site request forgery without server-side
    CSRF state.

Expiry: absolute cap (SESSION_ABSOLUTE_TTL_HOURS from creation) plus a
sliding idle window (SESSION_IDLE_TTL_HOURS since last authenticated
request). Logout revokes server-side.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy.orm import Session

from config import (
    COOKIE_SECURE,
    CSRF_COOKIE_NAME,
    SESSION_ABSOLUTE_TTL_HOURS,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TTL_HOURS,
)
from database.models import AuthSession


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_aware(dt: datetime) -> datetime:
    """Treat naive datetimes from SQLite as UTC (Postgres returns aware)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def create_auth_session(
    db: Session, user_id: int, user_agent: str | None = None
) -> tuple[str, str]:
    """Persist a new AuthSession; return (session_token, csrf_token).

    Both tokens are cryptographically random; only the session token's hash
    touches the database. The CSRF token is stateless (double-submit) and
    never stored.
    """
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(AuthSession(
        token_hash=_hash_token(token),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(hours=SESSION_ABSOLUTE_TTL_HOURS),
        last_seen_at=now,
        user_agent=(user_agent or "")[:256] or None,
    ))
    db.flush()
    return token, csrf


def resolve_auth_session(db: Session, token: str | None) -> AuthSession | None:
    """Return the live AuthSession for *token*, refreshing its idle window.

    Returns None for missing/unknown/revoked/expired/idle-timed-out tokens.
    """
    if not token:
        return None
    row: AuthSession | None = (
        db.query(AuthSession).filter_by(token_hash=_hash_token(token)).first()
    )
    if row is None or row.revoked_at is not None:
        return None

    now = datetime.now(UTC)
    if now >= _ensure_aware(row.expires_at):
        return None
    if now - _ensure_aware(row.last_seen_at) > timedelta(hours=SESSION_IDLE_TTL_HOURS):
        return None

    row.last_seen_at = now  # sliding refresh
    db.flush()
    return row


def revoke_auth_session(db: Session, token: str | None) -> None:
    """Server-side logout: mark the session revoked (idempotent)."""
    if not token:
        return
    row = db.query(AuthSession).filter_by(token_hash=_hash_token(token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.flush()


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    """Constant-time double-submit comparison."""
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    max_age = SESSION_ABSOLUTE_TTL_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE_NAME, session_token,
        max_age=max_age, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME, csrf_token,
        max_age=max_age, httponly=False, secure=COOKIE_SECURE,
        samesite="lax", path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
