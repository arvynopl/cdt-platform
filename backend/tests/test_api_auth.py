"""tests/test_api_auth.py — auth flow through the HTTP API (Fase 1)."""

from __future__ import annotations

from tests.conftest import csrf_headers

_SURVEY = {
    "dei_q1": 3, "dei_q2": 4, "dei_q3": 3,
    "ocs_q1": 4, "ocs_q2": 2, "ocs_q3": 3,
    "lai_q1": 5, "lai_q2": 4, "lai_q3": 3,
}


def _register_payload(username: str = "budi.santoso") -> dict:
    return {
        "username": username,
        "password": "rahasia-123",
        "full_name": "Budi Santoso",
        "age": 25,
        "gender": "laki-laki",
        "risk_profile": "moderat",
        "investing_capability": "pemula",
        "onboarding_survey": _SURVEY,
        "consent": True,
    }


def _register(client, username: str = "budi.santoso"):
    resp = client.post("/api/auth/register", json=_register_payload(username))
    assert resp.status_code == 201, resp.text
    return resp


class TestRegistration:
    def test_register_sets_session_and_me_works(self, api_client):
        resp = _register(api_client)
        body = resp.json()
        assert body["username"] == "budi.santoso"
        assert "cdt_session" in api_client.cookies
        assert "cdt_csrf" in api_client.cookies

        me = api_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "budi.santoso"

    def test_duplicate_username_conflicts(self, api_client):
        _register(api_client)
        resp = api_client.post(
            "/api/auth/register", json=_register_payload("budi.santoso")
        )
        assert resp.status_code == 409

    def test_consent_required(self, api_client):
        payload = _register_payload() | {"consent": False}
        resp = api_client.post("/api/auth/register", json=payload)
        assert resp.status_code == 422

    def test_check_username_flow(self, api_client):
        resp = api_client.post(
            "/api/auth/check-username", json={"username": "belum.ada"}
        )
        assert resp.json() == {"exists": False}
        _register(api_client, "sudah.ada")
        resp = api_client.post(
            "/api/auth/check-username", json={"username": "sudah.ada"}
        )
        assert resp.json() == {"exists": True}


class TestLogin:
    def test_login_logout_cycle(self, api_client):
        _register(api_client)
        api_client.cookies.clear()

        resp = api_client.post(
            "/api/auth/login",
            json={"username": "budi.santoso", "password": "rahasia-123"},
        )
        assert resp.status_code == 200
        assert api_client.get("/api/auth/me").status_code == 200

        out = api_client.post("/api/auth/logout", headers=csrf_headers(api_client))
        assert out.status_code == 200
        # Cookie cleared AND server-side revoked.
        assert api_client.get("/api/auth/me").status_code == 401

    def test_wrong_password_rejected(self, api_client):
        _register(api_client)
        api_client.cookies.clear()
        resp = api_client.post(
            "/api/auth/login",
            json={"username": "budi.santoso", "password": "salah-semua"},
        )
        assert resp.status_code == 401

    def test_rate_limit_locks_after_max_failures(self, api_client):
        _register(api_client)
        api_client.cookies.clear()
        for _ in range(5):  # AUTH_RATE_LIMIT_MAX
            api_client.post(
                "/api/auth/login",
                json={"username": "budi.santoso", "password": "salah"},
            )
        # Locked now — even the CORRECT password is refused.
        resp = api_client.post(
            "/api/auth/login",
            json={"username": "budi.santoso", "password": "rahasia-123"},
        )
        assert resp.status_code == 429

    def test_logout_requires_csrf_header(self, api_client):
        _register(api_client)
        resp = api_client.post("/api/auth/logout")  # no X-CSRF-Token
        assert resp.status_code == 403
        # Session is still alive afterwards.
        assert api_client.get("/api/auth/me").status_code == 200
