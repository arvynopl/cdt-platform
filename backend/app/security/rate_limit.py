"""app/security/rate_limit.py — DB-backed login rate limiting (audit F7).

Replaces the legacy in-memory limiter (modules/auth/rate_limit.py, retained
only for its unit tests) with LoginAttempt rows, so limits survive redeploys
and gain an IP dimension. Thresholds reuse the research-era config values:
AUTH_RATE_LIMIT_MAX failures within AUTH_RATE_LIMIT_WINDOW_SEC lock the
username; the same threshold per client IP blocks username rotation from a
single source.

IP addresses are pseudonymised (SHA-256) before touching the database —
the same UU PDP contract as ConsentLog.ip_hash.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from config import AUTH_RATE_LIMIT_MAX, AUTH_RATE_LIMIT_WINDOW_SEC
from database.models import LoginAttempt


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


def _window_start() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=AUTH_RATE_LIMIT_WINDOW_SEC)


def is_locked(db: Session, username: str, ip: str | None = None) -> bool:
    """True when username OR source IP exceeded the failure threshold."""
    cutoff = _window_start()
    by_user = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )
    if by_user >= AUTH_RATE_LIMIT_MAX:
        return True

    ip_h = hash_ip(ip)
    if ip_h is None:
        return False
    by_ip = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_hash == ip_h,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )
    return by_ip >= AUTH_RATE_LIMIT_MAX


def record_attempt(username: str, *, success: bool, ip: str | None = None) -> None:
    """Persist one attempt in its OWN transaction.

    Deliberately not bound to the request session: a failed login raises
    HTTPException, which rolls the request transaction back — and the audit
    row must survive exactly that rollback, or the rate limiter never sees
    failures and cannot lock anything.
    """
    from database.connection import get_session

    with get_session() as own:
        own.add(LoginAttempt(
            username=username[:64],
            ip_hash=hash_ip(ip),
            success=success,
        ))


def clear_failures(db: Session, username: str) -> None:
    """On successful login, retire the username's failure window."""
    cutoff = _window_start()
    (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.flush()
