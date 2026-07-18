"""tests/test_api_researcher.py — key-gated cohort/ops endpoints (Fase 1)."""

from __future__ import annotations

import pytest

from tests.test_api_auth import _register
from tests.test_api_simulation import _play_full_session

_RKEY = {"x-researcher-key": "rahasia-riset"}
_ATOKEN = {"x-admin-token": "token-admin"}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("CDT_RESEARCHER_PASSWORD", "rahasia-riset")
    monkeypatch.setenv("CDT_ADMIN_TOKEN", "token-admin")


class TestGates:
    def test_missing_key_rejected(self, api_client):
        assert api_client.get("/api/researcher/summary").status_code == 401
        assert api_client.get("/api/admin/summary").status_code == 401

    def test_wrong_key_rejected(self, api_client):
        resp = api_client.get(
            "/api/researcher/summary", headers={"x-researcher-key": "salah"}
        )
        assert resp.status_code == 401

    def test_unset_env_disables_endpoint(self, api_client, monkeypatch):
        monkeypatch.delenv("CDT_RESEARCHER_PASSWORD")
        resp = api_client.get("/api/researcher/summary", headers=_RKEY)
        assert resp.status_code == 503

    def test_user_session_cookie_grants_nothing(self, api_client):
        # A logged-in participant must NOT be able to read cohort data.
        _register(api_client)
        assert api_client.get("/api/researcher/summary").status_code == 401


class TestResearcherData:
    def test_summary_and_exports_after_session(self, api_client):
        _register(api_client)
        _play_full_session(api_client)

        summary = api_client.get(
            "/api/researcher/summary", headers=_RKEY
        ).json()
        assert summary["total_users"] >= 1
        assert summary["total_sessions"] >= 1

        users = api_client.get(
            "/api/researcher/export/users", headers=_RKEY
        ).json()
        assert users["count"] >= 1
        assert users["rows"][0]  # non-empty row dict

        sessions = api_client.get(
            "/api/researcher/export/sessions", headers=_RKEY
        ).json()
        assert sessions["count"] == 1

    def test_csv_format_downloads(self, api_client):
        _register(api_client)
        resp = api_client.get(
            "/api/researcher/export/users?format=csv", headers=_RKEY
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]

    def test_unknown_dataset_404(self, api_client):
        resp = api_client.get(
            "/api/researcher/export/tidak-ada", headers=_RKEY
        )
        assert resp.status_code == 404

    def test_ml_performance_shape(self, api_client):
        perf = api_client.get(
            "/api/researcher/ml-performance", headers=_RKEY
        ).json()
        assert "available" in perf


class TestAdminSummary:
    def test_counters_and_sql_avg_sus(self, api_client):
        _register(api_client)
        _play_full_session(api_client)
        from tests.conftest import csrf_headers

        payload = {f"sus_q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
        api_client.post(
            "/api/uat-feedback", json=payload, headers=csrf_headers(api_client)
        )

        out = api_client.get("/api/admin/summary", headers=_ATOKEN).json()
        assert out["total_users"] == 1
        assert out["completed_sessions"] == 1
        assert out["completion_rate"] == 1.0
        assert out["total_uat_feedback"] == 1
        # ((4-1)*5 + (5-2)*5) * 2.5 = 75.0, computed inside SQL
        assert out["avg_sus_score"] == 75.0
        assert out["total_session_errors"] == 0
