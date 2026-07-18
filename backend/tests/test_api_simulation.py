"""tests/test_api_simulation.py — session lifecycle through the HTTP API.

Exercises the Fase 1 contract end-to-end on the parity fixture market:
start → 14 batched rounds → background analytics → results, plus resume,
round-ordering guards, degraded orders, and F14 window non-repetition.
"""

from __future__ import annotations

from tests.conftest import csrf_headers
from tests.test_api_auth import _register

ROUNDS = 14


def _start(client) -> dict:
    resp = client.post("/api/sessions", headers=csrf_headers(client))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit(client, session_id: str, round_no: int, orders: list | None = None):
    resp = client.post(
        f"/api/sessions/{session_id}/rounds/{round_no}",
        json={"orders": orders or [], "response_time_ms": 1500},
        headers=csrf_headers(client),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _play_full_session(client, buy_round: int = 1, sell_round: int = 5) -> str:
    """Play 14 rounds with one profitable-or-not round-trip on VOLH.JK."""
    state = _start(client)
    sid = state["session_id"]
    for rnd in range(state["current_round"], ROUNDS + 1):
        orders = []
        if rnd == buy_round:
            orders = [{"stock_id": "VOLH.JK", "action": "buy", "quantity": 100}]
        elif rnd == sell_round:
            orders = [{"stock_id": "VOLH.JK", "action": "sell", "quantity": 100}]
        result = _submit(client, sid, rnd, orders)
    assert result["rounds_complete"] is True
    return sid


class TestSessionLifecycle:
    def test_start_requires_auth(self, api_client):
        resp = api_client.post("/api/sessions")
        assert resp.status_code in (401, 403)

    def test_start_payload_shape(self, api_client):
        _register(api_client)
        state = _start(api_client)
        assert state["resumed"] is False
        assert state["current_round"] == 1
        assert state["rounds_total"] == ROUNDS
        assert set(state["stock_ids"]) == {"VOLH.JK", "VOLL.JK"}
        for sid in state["stock_ids"]:
            assert len(state["window"][sid]) == ROUNDS
        assert state["portfolio"]["cash"] == 10_000_000.0

    def test_full_session_pipeline_and_results(self, api_client):
        _register(api_client)
        sid = _play_full_session(api_client)

        # TestClient runs background tasks synchronously after the response,
        # so the pipeline has already committed by now.
        status = api_client.get(f"/api/sessions/{sid}/analysis").json()
        assert status["status"] == "completed"

        results = api_client.get(f"/api/sessions/{sid}/results").json()
        assert results["metric"]["overconfidence_score"] is not None
        assert results["metric"]["disposition_dei"] is not None
        assert len(results["feedback"]) >= 1
        assert results["final_portfolio_value"] is not None

        # Profile was EMA-updated exactly once.
        profile = api_client.get("/api/me/profile").json()
        assert profile["profile"]["session_count"] == 1
        assert len(profile["metrics"]) == 1

    def test_round_order_enforced(self, api_client):
        _register(api_client)
        state = _start(api_client)
        sid = state["session_id"]
        resp = api_client.post(
            f"/api/sessions/{sid}/rounds/2",
            json={"orders": [], "response_time_ms": 100},
            headers=csrf_headers(api_client),
        )
        assert resp.status_code == 409

    def test_unaffordable_order_degrades_to_hold(self, api_client):
        _register(api_client)
        state = _start(api_client)
        sid = state["session_id"]
        result = _submit(api_client, sid, 1, [
            {"stock_id": "VOLH.JK", "action": "buy", "quantity": 10_000_000},
        ])
        assert result["errors"]  # rejection surfaced to the client…
        assert result["portfolio"]["holdings"] == []  # …and no position opened
        assert result["next_round"] == 2  # round still completed (auto-hold)

    def test_resume_replays_portfolio(self, api_client):
        _register(api_client)
        state = _start(api_client)
        sid = state["session_id"]
        _submit(api_client, sid, 1, [
            {"stock_id": "VOLH.JK", "action": "buy", "quantity": 50},
        ])
        _submit(api_client, sid, 2)
        _submit(api_client, sid, 3)

        # Fresh "browser" (same auth): starting again resumes, not restarts.
        resumed = _start(api_client)
        assert resumed["resumed"] is True
        assert resumed["session_id"] == sid
        assert resumed["current_round"] == 4
        holdings = resumed["portfolio"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["stock_id"] == "VOLH.JK"
        assert holdings[0]["quantity"] == 50

    def test_abandon_frees_the_slot(self, api_client):
        _register(api_client)
        state = _start(api_client)
        sid = state["session_id"]
        _submit(api_client, sid, 1)
        resp = api_client.post(
            f"/api/sessions/{sid}/abandon", headers=csrf_headers(api_client)
        )
        assert resp.status_code == 200
        fresh = _start(api_client)
        assert fresh["resumed"] is False
        assert fresh["session_id"] != sid


class TestWindowNonRepetition:
    def test_second_session_gets_new_window(self, api_client):
        """Audit F14: repeat sessions must not reuse a played start date."""
        _register(api_client)
        first_sid = _play_full_session(api_client)
        first = api_client.get(f"/api/sessions/{first_sid}/analysis").json()
        assert first["status"] == "completed"

        seen_starts = set()
        # Play several more sessions; every start date must be fresh until
        # the 7 candidate windows (20 days − 14 + 1) are exhausted.
        state1_start = None
        for _ in range(3):
            state = _start(api_client)
            assert state["window_start_date"] not in seen_starts
            if state1_start is None:
                state1_start = state["window_start_date"]
            seen_starts.add(state["window_start_date"])
            sid = state["session_id"]
            for rnd in range(1, ROUNDS + 1):
                _submit(api_client, sid, rnd)


class TestSurveys:
    def test_post_session_survey_upserts(self, api_client):
        _register(api_client)
        sid = _play_full_session(api_client)
        payload = {
            "self_overconfidence": 4, "self_disposition": 3,
            "self_loss_aversion": 2, "feedback_usefulness": 5,
        }
        r1 = api_client.post(
            f"/api/sessions/{sid}/post-survey",
            json=payload, headers=csrf_headers(api_client),
        )
        assert r1.status_code == 200
        r2 = api_client.post(
            f"/api/sessions/{sid}/post-survey",
            json=payload | {"feedback_usefulness": 1},
            headers=csrf_headers(api_client),
        )
        assert r2.status_code == 200  # latest answers win, no 500 on resubmit

    def test_uat_feedback_appends_and_scores(self, api_client):
        _register(api_client)
        payload = {f"sus_q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
        payload |= {"open_suggestion": "tambahkan pratinjau biaya order"}
        resp = api_client.post(
            "/api/uat-feedback", json=payload, headers=csrf_headers(api_client)
        )
        assert resp.status_code == 200
        assert resp.json()["sus_score"] == 75.0  # ((4-1)*5 + (5-2)*5) * 2.5
