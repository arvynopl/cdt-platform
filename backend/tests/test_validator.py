"""
tests/test_validator.py — Tests for validate_session_completeness.

Uses the shared db/user fixtures from conftest.py.
"""

import uuid
from datetime import date, timedelta

from config import ROUNDS_PER_SESSION
from database.models import MarketSnapshot, UserAction
from modules.logging_engine.validator import validate_session_completeness

BASE_DATE = date(2024, 4, 2)
STOCK_IDS = ["BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK"]


def _get_snap(db, stock_id: str, round_num: int) -> MarketSnapshot:
    target = BASE_DATE + timedelta(days=round_num - 1)
    return db.query(MarketSnapshot).filter_by(stock_id=stock_id, date=target).first()


def _log_round(db, user_id: int, session_id: str, round_num: int, stock_ids=None):
    """Log one hold action per stock for the given round."""
    for sid in (stock_ids or STOCK_IDS):
        snap = _get_snap(db, sid, round_num)
        db.add(UserAction(
            user_id=user_id, session_id=session_id,
            scenario_round=round_num, stock_id=sid,
            snapshot_id=snap.id, action_type="hold",
            quantity=0, action_value=0.0, response_time_ms=500,
        ))
    db.flush()


def test_complete_session_is_complete(db, user):
    """Logging all 14 × 6 actions → is_complete=True, missing_rounds=[]."""
    sid = str(uuid.uuid4())
    for r in range(1, ROUNDS_PER_SESSION + 1):
        _log_round(db, user.id, sid, r)
    result = validate_session_completeness(db, user.id, sid)
    assert result["is_complete"] is True
    assert result["missing_rounds"] == []
    assert result["action_count"] == ROUNDS_PER_SESSION * len(STOCK_IDS)


def test_missing_rounds_detected(db, user):
    """Skipping rounds 5, 10 → is_complete=False, missing_rounds contains 5 and 10."""
    sid = str(uuid.uuid4())
    for r in range(1, ROUNDS_PER_SESSION + 1):
        if r not in (5, 10):
            _log_round(db, user.id, sid, r)
    result = validate_session_completeness(db, user.id, sid)
    assert result["is_complete"] is False
    assert 5 in result["missing_rounds"]
    assert 10 in result["missing_rounds"]


def test_empty_session_returns_zero_actions(db, user):
    """No actions logged → action_count=0 and missing_rounds is empty (no stocks known)."""
    sid = str(uuid.uuid4())
    result = validate_session_completeness(db, user.id, sid)
    # With no actions, the validator has no stock_ids to validate against.
    # An empty set is a subset of every set, so missing_rounds == [].
    # Completeness is inferred purely from action counts in real use.
    assert result["action_count"] == 0
    assert result["missing_rounds"] == []


def test_action_count_matches_logged(db, user):
    """After logging 84 actions, action_count == 84."""
    sid = str(uuid.uuid4())
    for r in range(1, ROUNDS_PER_SESSION + 1):
        _log_round(db, user.id, sid, r)
    result = validate_session_completeness(db, user.id, sid)
    assert result["action_count"] == ROUNDS_PER_SESSION * len(STOCK_IDS)
    assert result["expected_count"] == ROUNDS_PER_SESSION * len(STOCK_IDS)


def test_partial_stock_coverage_marks_round_missing(db, user):
    """Round 1 with only 3 of 6 stocks → round 1 in missing_rounds."""
    sid = str(uuid.uuid4())
    # Round 1: only 3 stocks
    _log_round(db, user.id, sid, 1, stock_ids=STOCK_IDS[:3])
    # Rounds 2-14: all stocks
    for r in range(2, ROUNDS_PER_SESSION + 1):
        _log_round(db, user.id, sid, r)
    result = validate_session_completeness(db, user.id, sid)
    assert 1 in result["missing_rounds"]
    assert result["is_complete"] is False
