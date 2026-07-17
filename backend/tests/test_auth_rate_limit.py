"""tests/test_auth_rate_limit.py — sliding-window rate limiter."""

from datetime import UTC

import pytest

from config import AUTH_RATE_LIMIT_MAX
from modules.auth import rate_limit


@pytest.fixture(autouse=True)
def _clear_state():
    rate_limit._attempts.clear()
    yield
    rate_limit._attempts.clear()


def test_not_locked_initially():
    assert rate_limit.is_locked("alice") is False


def test_lock_after_max_failures():
    for _ in range(AUTH_RATE_LIMIT_MAX):
        rate_limit.record_failure("alice")
    assert rate_limit.is_locked("alice") is True


def test_lock_is_per_username():
    for _ in range(AUTH_RATE_LIMIT_MAX):
        rate_limit.record_failure("alice")
    assert rate_limit.is_locked("alice") is True
    assert rate_limit.is_locked("bob") is False


def test_reset_clears_attempts():
    for _ in range(AUTH_RATE_LIMIT_MAX):
        rate_limit.record_failure("alice")
    rate_limit.reset_attempts("alice")
    assert rate_limit.is_locked("alice") is False
    assert rate_limit._debug_failure_count("alice") == 0


def test_window_expiry_unlocks(monkeypatch):
    """Simulate time passing by backdating recorded failures."""
    from datetime import datetime, timedelta

    from config import AUTH_RATE_LIMIT_WINDOW_SEC

    for _ in range(AUTH_RATE_LIMIT_MAX):
        rate_limit.record_failure("alice")
    assert rate_limit.is_locked("alice") is True

    # Backdate every failure outside the window
    dq = rate_limit._attempts["alice"]
    aged = datetime.now(UTC) - timedelta(seconds=AUTH_RATE_LIMIT_WINDOW_SEC + 10)
    for i in range(len(dq)):
        dq[i] = aged

    assert rate_limit.is_locked("alice") is False
    assert rate_limit._debug_failure_count("alice") == 0


def test_empty_username_noop():
    rate_limit.record_failure("")
    assert rate_limit.is_locked("") is False
    rate_limit.reset_attempts("")  # should not raise
