"""modules/auth/rate_limit.py — in-memory sliding-window rate limiter.

Locks a username after ``AUTH_RATE_LIMIT_MAX`` failed logins within
``AUTH_RATE_LIMIT_WINDOW_SEC`` seconds. Acceptable for an MVP SQLite
deployment; swap for a Redis-backed implementation in production.

The window is reset on a successful authentication (via ``reset_attempts``).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from config import AUTH_RATE_LIMIT_MAX, AUTH_RATE_LIMIT_WINDOW_SEC

_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def _now() -> datetime:
    return datetime.now(UTC)


def _prune(username: str) -> None:
    """Drop failures older than the sliding window."""
    cutoff = _now() - timedelta(seconds=AUTH_RATE_LIMIT_WINDOW_SEC)
    dq = _attempts[username]
    while dq and dq[0] < cutoff:
        dq.popleft()


def record_failure(username: str) -> None:
    """Record one failed authentication attempt for ``username``."""
    if not username:
        return
    _prune(username)
    _attempts[username].append(_now())


def is_locked(username: str) -> bool:
    """Return True when the account has exceeded the failure threshold."""
    if not username:
        return False
    _prune(username)
    return len(_attempts[username]) >= AUTH_RATE_LIMIT_MAX


def reset_attempts(username: str) -> None:
    """Clear the failure window — call on a successful login."""
    if not username:
        return
    _attempts.pop(username, None)


def _debug_failure_count(username: str) -> int:
    """Test helper — number of live failures in the window."""
    _prune(username)
    return len(_attempts[username])
