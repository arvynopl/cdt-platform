"""app/deps.py — shared FastAPI dependencies.

``get_db`` yields a transactional SQLAlchemy session from the same factory
the domain layer uses (commit on success, rollback on exception).
``current_user`` resolves the session cookie to a User or raises 401.
``require_csrf`` enforces the double-submit token on mutating routes.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.security.sessions import csrf_matches, resolve_auth_session
from config import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from database.connection import get_session
from database.models import User


def get_db() -> Generator[Session, None, None]:
    with get_session() as sess:
        yield sess


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth = resolve_auth_session(db, token)
    if auth is None:
        raise HTTPException(status_code=401, detail="Sesi tidak valid atau kedaluwarsa.")
    user = db.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Pengguna tidak ditemukan.")
    return user


def require_csrf(request: Request) -> None:
    """Double-submit CSRF guard for mutating endpoints (audit F5)."""
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    header = request.headers.get(CSRF_HEADER_NAME)
    if not csrf_matches(cookie, header):
        raise HTTPException(
            status_code=403,
            detail="Token CSRF tidak valid. Muat ulang halaman lalu coba lagi.",
        )


def client_ip(request: Request) -> str | None:
    """Best-effort client IP: honour the left-most X-Forwarded-For entry when
    behind the platform proxy (Fly.io sets it), else the socket peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
