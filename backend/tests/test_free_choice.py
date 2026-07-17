"""
tests/test_free_choice.py — Verify that sessions where the user only trades
a subset of available stocks still produce valid bias metrics, CDT updates,
and feedback records.

This tests the free-choice trading model introduced in v0.3.0, where the
simulation UI auto-logs "hold" for all non-interacted stocks, ensuring that
validate_session_completeness passes and the analytics pipeline runs cleanly.

Uses the shared db/user fixtures from conftest.py (12 stocks, 50 days).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from config import ROUNDS_PER_SESSION
from database.models import FeedbackHistory, MarketSnapshot, UserAction
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.logger import log_action
from modules.logging_engine.validator import validate_session_completeness

BASE_DATE = date(2024, 4, 2)

# Only 3 out of 12 stocks actively traded — rest auto-held
ACTIVE_STOCKS = ["BBCA.JK", "ANTM.JK", "MDKA.JK"]
ALL_STOCKS_12 = [
    "BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK",
    "ASII.JK", "BMRI.JK", "ICBP.JK", "MDKA.JK", "BRIS.JK", "EMTK.JK",
]

BASE_PRICES = {
    "BBCA.JK": 9000.0, "TLKM.JK": 3000.0, "ANTM.JK": 2000.0,
    "GOTO.JK": 70.0, "UNVR.JK": 2000.0, "BBRI.JK": 4000.0,
    "ASII.JK": 5000.0, "BMRI.JK": 5500.0, "ICBP.JK": 10000.0,
    "MDKA.JK": 3000.0, "BRIS.JK": 2000.0, "EMTK.JK": 1500.0,
}


def _get_snap(db, stock_id: str, round_num: int) -> MarketSnapshot:
    target_date = BASE_DATE + timedelta(days=round_num - 1)
    return db.query(MarketSnapshot).filter_by(
        stock_id=stock_id, date=target_date
    ).first()


def _log_free_choice_session(
    db,
    user_id: int,
    session_id: str,
    active_stocks: list[str],
    all_stocks: list[str],
    buy_in_round_1: list[str] | None = None,
    sell_in_round_14: list[str] | None = None,
) -> None:
    """Simulate the free-choice trading model.

    - active_stocks that appear in buy_in_round_1 are bought in round 1.
    - active_stocks that appear in sell_in_round_14 are sold in round 14.
    - All other (stock, round) combinations are logged as 'hold'.
    """
    buy_in_round_1 = buy_in_round_1 or []
    sell_in_round_14 = sell_in_round_14 or []
    bought_qty: dict[str, int] = {}

    for rnd in range(1, ROUNDS_PER_SESSION + 1):
        for sid in all_stocks:
            snap = _get_snap(db, sid, rnd)
            if snap is None:
                continue
            price = BASE_PRICES[sid]

            if rnd == 1 and sid in buy_in_round_1:
                qty = 10
                atype = "buy"
                bought_qty[sid] = qty
                val = qty * price
            elif rnd == 14 and sid in sell_in_round_14 and sid in bought_qty:
                qty = bought_qty[sid]
                atype = "sell"
                val = qty * price
            else:
                qty = 0
                atype = "hold"
                val = 0.0

            log_action(
                session=db,
                user_id=user_id,
                session_id=session_id,
                scenario_round=rnd,
                stock_id=sid,
                snapshot_id=snap.id,
                action_type=atype,
                quantity=qty,
                action_value=val,
                response_time_ms=500,
            )
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_free_choice_action_count(db, user):
    """14 rounds × 12 stocks = 168 actions even when only 3 stocks are traded."""
    session_id = str(uuid.uuid4())
    _log_free_choice_session(
        db, user.id, session_id,
        active_stocks=ACTIVE_STOCKS,
        all_stocks=ALL_STOCKS_12,
        buy_in_round_1=["BBCA.JK", "ANTM.JK"],
        sell_in_round_14=["BBCA.JK"],
    )

    count = db.query(UserAction).filter_by(
        user_id=user.id, session_id=session_id
    ).count()
    assert count == ROUNDS_PER_SESSION * len(ALL_STOCKS_12), (
        f"Expected {ROUNDS_PER_SESSION * len(ALL_STOCKS_12)} actions, got {count}"
    )


def test_free_choice_session_is_complete(db, user):
    """validate_session_completeness returns is_complete=True for a free-choice session."""
    session_id = str(uuid.uuid4())
    _log_free_choice_session(
        db, user.id, session_id,
        active_stocks=ACTIVE_STOCKS,
        all_stocks=ALL_STOCKS_12,
        buy_in_round_1=["BBCA.JK"],
    )

    result = validate_session_completeness(db, user.id, session_id)
    assert result["is_complete"] is True
    assert result["missing_rounds"] == []


def test_free_choice_bias_metrics_valid_range(db, user):
    """Bias metrics computed from a free-choice session are within valid ranges."""
    session_id = str(uuid.uuid4())
    _log_free_choice_session(
        db, user.id, session_id,
        active_stocks=ACTIVE_STOCKS,
        all_stocks=ALL_STOCKS_12,
        buy_in_round_1=["BBCA.JK", "ANTM.JK"],
        sell_in_round_14=["BBCA.JK"],
    )

    metric = compute_and_save_metrics(db, user.id, session_id)
    assert metric.id is not None
    assert 0.0 <= (metric.overconfidence_score or 0.0) <= 1.0
    assert -1.0 <= (metric.disposition_dei or 0.0) <= 1.0
    assert (metric.loss_aversion_index or 0.0) >= 0.0


def test_free_choice_full_pipeline(db, user):
    """Free-choice session runs the full pipeline and produces 3 feedback records."""
    session_id = str(uuid.uuid4())
    _log_free_choice_session(
        db, user.id, session_id,
        active_stocks=ACTIVE_STOCKS,
        all_stocks=ALL_STOCKS_12,
        buy_in_round_1=["ANTM.JK", "MDKA.JK"],
        sell_in_round_14=["ANTM.JK"],
    )

    metric = compute_and_save_metrics(db, user.id, session_id)
    features = extract_session_features(db, user.id, session_id)
    profile = update_profile(db, user.id, metric, session_id)
    feedbacks = generate_feedback(
        db_session=db,
        user_id=user.id,
        session_id=session_id,
        bias_metric=metric,
        profile=profile,
        realized_trades=features.realized_trades,
        open_positions=features.open_positions,
    )

    assert len(feedbacks) == 3
    fb_count = db.query(FeedbackHistory).filter_by(
        user_id=user.id, session_id=session_id
    ).count()
    assert fb_count == 3

    # CDT profile reflects the session
    assert profile.session_count == 1
    assert 0.0 <= profile.risk_preference <= 1.0


def test_all_hold_session_with_twelve_stocks(db, user):
    """A pure all-hold session across 12 stocks is valid and produces zero-bias metrics."""
    session_id = str(uuid.uuid4())
    _log_free_choice_session(
        db, user.id, session_id,
        active_stocks=[],
        all_stocks=ALL_STOCKS_12,
    )

    count = db.query(UserAction).filter_by(
        user_id=user.id, session_id=session_id
    ).count()
    assert count == ROUNDS_PER_SESSION * 12

    result = validate_session_completeness(db, user.id, session_id)
    assert result["is_complete"] is True

    metric = compute_and_save_metrics(db, user.id, session_id)
    # No trades → no realized gains/losses → DEI undefined (None or 0)
    assert metric.disposition_dei is None or metric.disposition_dei == 0.0
    # LAI undefined or 0 with no trades
    assert (metric.loss_aversion_index or 0.0) >= 0.0
