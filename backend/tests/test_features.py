"""
tests/test_features.py — Tests for extract_session_features and SessionFeatures fields.

Uses shared db/user fixtures from conftest.py.
"""

import uuid
from datetime import date, timedelta

import pytest

from config import ROUNDS_PER_SESSION
from database.models import MarketSnapshot, UserAction
from modules.analytics.features import extract_session_features

BASE_DATE = date(2024, 4, 2)
STOCK_IDS = ["BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK"]


def _snap(db, stock_id: str, round_num: int) -> MarketSnapshot:
    return db.query(MarketSnapshot).filter_by(
        stock_id=stock_id, date=BASE_DATE + timedelta(days=round_num - 1)
    ).first()


def _log_hold_session(db, user_id: int, session_id: str, response_time_ms: int = 500):
    """Log 14 rounds of hold-only actions (no buys or sells)."""
    for r in range(1, ROUNDS_PER_SESSION + 1):
        for sid in STOCK_IDS:
            snap = _snap(db, sid, r)
            db.add(UserAction(
                user_id=user_id, session_id=session_id,
                scenario_round=r, stock_id=sid, snapshot_id=snap.id,
                action_type="hold", quantity=0, action_value=0.0,
                response_time_ms=response_time_ms,
            ))
    db.flush()


def test_hold_only_session_counts(db, user):
    """14 rounds × 6 stocks holds → hold_count=84, buy_count=0, sell_count=0."""
    sid = str(uuid.uuid4())
    _log_hold_session(db, user.id, sid)
    features = extract_session_features(db, user.id, sid)
    assert features.buy_count == 0
    assert features.sell_count == 0
    assert features.hold_count == ROUNDS_PER_SESSION * len(STOCK_IDS)


def test_response_time_fields_populated(db, user):
    """All actions with response_time_ms=1000 → avg and max both 1000."""
    sid = str(uuid.uuid4())
    _log_hold_session(db, user.id, sid, response_time_ms=1000)
    features = extract_session_features(db, user.id, sid)
    assert features.avg_response_time_ms == pytest.approx(1000.0)
    assert features.max_response_time_ms == 1000


def test_portfolio_return_pct_zero_for_hold_only(db, user):
    """Hold-only session with flat prices → return ≈ 0%."""
    sid = str(uuid.uuid4())
    _log_hold_session(db, user.id, sid)
    features = extract_session_features(db, user.id, sid)
    assert features.portfolio_return_pct == pytest.approx(0.0, abs=1.0)


def test_buy_then_sell_creates_realized_trade(db, user):
    """Buy BBCA round 1, sell BBCA round 2 → one realized trade."""
    sid = str(uuid.uuid4())
    buy_snap = _snap(db, "BBCA.JK", 1)
    sell_snap = _snap(db, "BBCA.JK", 2)

    db.add(UserAction(
        user_id=user.id, session_id=sid, scenario_round=1,
        stock_id="BBCA.JK", snapshot_id=buy_snap.id,
        action_type="buy", quantity=10, action_value=10 * buy_snap.close,
        response_time_ms=300,
    ))
    db.add(UserAction(
        user_id=user.id, session_id=sid, scenario_round=2,
        stock_id="BBCA.JK", snapshot_id=sell_snap.id,
        action_type="sell", quantity=10, action_value=10 * sell_snap.close,
        response_time_ms=400,
    ))
    # Hold all other stocks rounds 1-14
    for r in range(1, ROUNDS_PER_SESSION + 1):
        for sid2 in STOCK_IDS:
            if sid2 == "BBCA.JK":
                continue
            snap = _snap(db, sid2, r)
            db.add(UserAction(
                user_id=user.id, session_id=sid, scenario_round=r,
                stock_id=sid2, snapshot_id=snap.id,
                action_type="hold", quantity=0, action_value=0.0,
                response_time_ms=300,
            ))
    db.flush()

    features = extract_session_features(db, user.id, sid)
    assert features.buy_count == 1
    assert features.sell_count == 1
    assert len(features.realized_trades) == 1
    trade = features.realized_trades[0]
    assert trade["stock_id"] == "BBCA.JK"
    assert trade["buy_round"] == 1
    assert trade["sell_round"] == 2


def test_empty_session_zero_response_time(db, user):
    """No actions → avg_response_time_ms == 0, portfolio_return_pct == 0."""
    sid = str(uuid.uuid4())
    features = extract_session_features(db, user.id, sid)
    assert features.avg_response_time_ms == 0.0
    assert features.max_response_time_ms == 0
    assert features.portfolio_return_pct == pytest.approx(0.0, abs=0.01)
