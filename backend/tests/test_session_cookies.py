"""tests/test_session_cookies.py — auth-cookie attributes per environment.

Dev default is SameSite=Lax over http (localhost cross-port is same-site). A
cross-site production deployment (Vercel frontend → fly.dev API) needs
SameSite=None with Secure, or the browser never sends the cookie. Both are
driven by config.COOKIE_SECURE / COOKIE_SAMESITE and consumed by
app.security.sessions.
"""

from __future__ import annotations

import pytest
from fastapi import Response

import config
from app.security import sessions


def _set_cookies(response: Response) -> list[str]:
    """Lower-cased Set-Cookie header values emitted by the response."""
    return [
        value.decode().lower()
        for (name, value) in response.raw_headers
        if name == b"set-cookie"
    ]


def test_dev_cookies_are_lax_and_insecure(monkeypatch):
    monkeypatch.setattr(sessions, "COOKIE_SECURE", False)
    monkeypatch.setattr(sessions, "_SAMESITE", "lax")
    resp = Response()

    sessions.set_session_cookies(resp, "sess-token", "csrf-token")

    cookies = _set_cookies(resp)
    assert len(cookies) == 2
    assert any("cdt_session=" in c for c in cookies)
    assert any("cdt_csrf=" in c for c in cookies)
    for c in cookies:
        assert "samesite=lax" in c
        assert "secure" not in c


def test_prod_cookies_are_samesite_none_and_secure(monkeypatch):
    monkeypatch.setattr(sessions, "COOKIE_SECURE", True)
    monkeypatch.setattr(sessions, "_SAMESITE", "none")
    resp = Response()

    sessions.set_session_cookies(resp, "sess-token", "csrf-token")

    cookies = _set_cookies(resp)
    assert len(cookies) == 2
    for c in cookies:
        assert "samesite=none" in c
        assert "secure" in c

    session_cookie = next(c for c in cookies if "cdt_session=" in c)
    csrf_cookie = next(c for c in cookies if "cdt_csrf=" in c)
    assert "httponly" in session_cookie
    assert "httponly" not in csrf_cookie  # JS must read the CSRF token


def test_clear_cookies_match_attributes(monkeypatch):
    # The browser only removes a cookie when the deletion echoes the same
    # Secure/SameSite it was set with.
    monkeypatch.setattr(sessions, "COOKIE_SECURE", True)
    monkeypatch.setattr(sessions, "_SAMESITE", "none")
    resp = Response()

    sessions.clear_session_cookies(resp)

    cookies = _set_cookies(resp)
    assert len(cookies) == 2
    for c in cookies:
        assert "samesite=none" in c
        assert "secure" in c
        assert "max-age=0" in c or "expires=" in c


def test_validate_rejects_samesite_none_without_secure(monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SAMESITE", "none")
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    with pytest.raises(ValueError, match="requires CDT_COOKIE_SECURE"):
        config.validate_api_config()


def test_validate_rejects_unknown_samesite(monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SAMESITE", "sometimes")
    with pytest.raises(ValueError, match="lax|strict|none"):
        config.validate_api_config()
