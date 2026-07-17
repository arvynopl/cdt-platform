"""
tests/test_integration.py — End-to-end integration test.

Programmatically creates a user, logs 14 rounds of actions for 6 stocks,
then verifies the full pipeline: features → bias metrics → CDT update →
feedback generation, checking all DB records exist with valid values.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base,
    BiasMetric,
    FeedbackHistory,
    MarketSnapshot,
    StockCatalog,
    User,
    UserAction,
)
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.logger import log_action

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STOCKS = [
    ("BBCA.JK", "BBCA", "Finance", "low"),
    ("TLKM.JK", "TLKM", "Telecom", "low_medium"),
    ("ANTM.JK", "ANTM", "Mining", "high"),
    ("GOTO.JK", "GOTO", "Technology", "high"),
    ("UNVR.JK", "UNVR", "Consumer", "medium"),
    ("BBRI.JK", "BBRI", "Finance", "medium"),
]

PRICES = {
    "BBCA.JK": 9000.0,
    "TLKM.JK": 3000.0,
    "ANTM.JK": 2000.0,
    "GOTO.JK": 70.0,
    "UNVR.JK": 2000.0,
    "BBRI.JK": 4000.0,
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    # Seed stocks
    for stock_id, ticker, sector, vol_class in STOCKS:
        s = StockCatalog(
            stock_id=stock_id, ticker=ticker, name=f"{ticker} Corp",
            sector=sector, volatility_class=vol_class, bias_role="test",
        )
        sess.add(s)
    sess.flush()

    # Seed 20 snapshots per stock (more than 14 rounds needed)
    base_date = date(2024, 4, 2)
    for stock_id, _, _, _ in STOCKS:
        price = PRICES[stock_id]
        for day in range(20):
            snap = MarketSnapshot(
                stock_id=stock_id,
                date=base_date + timedelta(days=day),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000_000,
                ma_5=price, ma_20=price, rsi_14=50.0,
                volatility_20d=0.02, trend="neutral", daily_return=0.0,
            )
            sess.add(snap)
    sess.flush()

    yield sess
    sess.close()


@pytest.fixture()
def user(db):
    u = User(alias="integration_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _get_snapshot(db, stock_id: str, round_num: int) -> MarketSnapshot:
    """Fetch snapshot for stock at round_num (1-indexed)."""
    base_date = date(2024, 4, 2)
    target_date = base_date + timedelta(days=round_num - 1)
    return (
        db.query(MarketSnapshot)
        .filter_by(stock_id=stock_id, date=target_date)
        .first()
    )


# ---------------------------------------------------------------------------
# Helpers to simulate scripted sessions
# ---------------------------------------------------------------------------

def _log_full_session(db, user_id: int, session_id: str, buy_stocks=None, sell_stocks=None):
    """
    Log 14 rounds × 6 stocks = 84 UserActions.

    buy_stocks:  list of stock_ids to buy in round 1.
    sell_stocks: list of stock_ids to sell in round 14 (if previously bought).
    """
    buy_stocks = buy_stocks or []
    sell_stocks = sell_stocks or []
    bought_qty: dict[str, int] = {}

    for rnd in range(1, 15):
        for stock_id, _, _, _ in STOCKS:
            snap = _get_snapshot(db, stock_id, rnd)
            if snap is None:
                continue

            if rnd == 1 and stock_id in buy_stocks:
                qty = 10
                action_type = "buy"
                bought_qty[stock_id] = qty
                action_val = qty * snap.close
            elif rnd == 14 and stock_id in sell_stocks and stock_id in bought_qty:
                qty = bought_qty[stock_id]
                action_type = "sell"
                action_val = qty * snap.close
            else:
                qty = 0
                action_type = "hold"
                action_val = 0.0

            log_action(
                session=db,
                user_id=user_id,
                session_id=session_id,
                scenario_round=rnd,
                stock_id=stock_id,
                snapshot_id=snap.id,
                action_type=action_type,
                quantity=qty,
                action_value=action_val,
                response_time_ms=500,
            )
    db.flush()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_full_pipeline_creates_all_records(db, user):
    """Full session: log → compute metrics → update CDT → generate feedback."""
    session_id = str(uuid.uuid4())

    # 1. Log 14 rounds
    _log_full_session(
        db, user.id, session_id,
        buy_stocks=["BBCA.JK", "ANTM.JK"],
        sell_stocks=["BBCA.JK"],  # sell winner, hold loser
    )

    # Verify actions logged
    action_count = db.query(UserAction).filter_by(
        user_id=user.id, session_id=session_id
    ).count()
    assert action_count == 14 * len(STOCKS), f"Expected {14 * len(STOCKS)} actions, got {action_count}"

    # 2. Compute bias metrics
    metric = compute_and_save_metrics(db, user.id, session_id)
    assert metric.id is not None
    assert 0.0 <= (metric.overconfidence_score or 0.0) <= 1.0
    assert metric.disposition_dei is not None
    assert metric.loss_aversion_index is not None

    # 3. Update CDT profile
    profile = update_profile(db, user.id, metric, session_id)
    assert profile.session_count == 1
    assert 0.0 <= profile.risk_preference <= 1.0
    bv = profile.bias_intensity_vector
    assert "overconfidence" in bv
    assert "disposition" in bv
    assert "loss_aversion" in bv

    # 4. Generate feedback
    features = extract_session_features(db, user.id, session_id)
    feedbacks = generate_feedback(
        db_session=db,
        user_id=user.id,
        session_id=session_id,
        bias_metric=metric,
        profile=profile,
        realized_trades=features.realized_trades,
        open_positions=features.open_positions,
    )
    assert len(feedbacks) == 3, f"Expected 3 feedback records, got {len(feedbacks)}"

    # Verify all feedback rows in DB
    fb_count = db.query(FeedbackHistory).filter_by(
        user_id=user.id, session_id=session_id
    ).count()
    assert fb_count == 3


def test_three_sessions_ema_convergence(db, user):
    """Three sessions update CDT profile; session_count = 3 after all."""
    for _ in range(3):
        sid = str(uuid.uuid4())
        _log_full_session(db, user.id, sid)
        metric = compute_and_save_metrics(db, user.id, sid)
        features = extract_session_features(db, user.id, sid)
        profile = update_profile(db, user.id, metric, sid)
        generate_feedback(db, user.id, sid, metric, profile,
                          features.realized_trades, features.open_positions)

    from modules.cdt.profile import get_or_create_profile
    profile = get_or_create_profile(db, user.id)
    assert profile.session_count == 3

    total_fb = db.query(FeedbackHistory).filter_by(user_id=user.id).count()
    assert total_fb == 9  # 3 sessions × 3 bias types


def test_bias_metric_values_in_valid_range(db, user):
    """Computed bias metrics must be within expected value ranges."""
    sid = str(uuid.uuid4())
    _log_full_session(db, user.id, sid)
    metric = compute_and_save_metrics(db, user.id, sid)

    assert 0.0 <= (metric.overconfidence_score or 0.0) <= 1.0
    assert -1.0 <= (metric.disposition_dei or 0.0) <= 1.0
    assert 0.0 <= (metric.disposition_pgr or 0.0) <= 1.0
    assert 0.0 <= (metric.disposition_plr or 0.0) <= 1.0
    assert (metric.loss_aversion_index or 0.0) >= 0.0


def test_final_price_uses_market_not_cost_basis():
    """Bug 1 regression guard: final_price for held positions must come from
    the last MarketSnapshot close, NOT from the cost-basis (avg_price).

    Setup: buy BBCA at 9 000 in round 1, hold all 14 rounds.
           Day-13 snapshot (round 14) has close = 10 500  ≠ buy price.
    Expected: open_positions[0]['final_price'] == 10 500.0
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    # Seed stock
    s = StockCatalog(
        stock_id="BBCA.JK", ticker="BBCA", name="BCA Corp",
        sector="Finance", volatility_class="low", bias_role="test",
    )
    sess.add(s)
    sess.flush()

    # Seed 14 snapshots: days 0-12 close=9000, day 13 close=10500
    base_date = date(2024, 4, 2)
    snap_ids: list[int] = []
    for day in range(14):
        close = 10_500.0 if day == 13 else 9_000.0
        snap = MarketSnapshot(
            stock_id="BBCA.JK",
            date=base_date + timedelta(days=day),
            open=close, high=close, low=close, close=close,
            volume=1_000_000, ma_5=close, ma_20=close, rsi_14=50.0,
            volatility_20d=0.02, trend="neutral", daily_return=0.0,
        )
        sess.add(snap)
        sess.flush()
        snap_ids.append(snap.id)

    # Seed user
    u = User(alias="bug1_user", experience_level="beginner")
    sess.add(u)
    sess.flush()

    session_id = str(uuid.uuid4())
    buy_price = 9_000.0

    # Log 14 rounds: buy round 1, hold rounds 2-14
    for rnd in range(1, 15):
        snap_id = snap_ids[rnd - 1]
        if rnd == 1:
            atype, qty, val = "buy", 10, 10 * buy_price
        else:
            atype, qty, val = "hold", 0, 0.0
        log_action(
            session=sess,
            user_id=u.id,
            session_id=session_id,
            scenario_round=rnd,
            stock_id="BBCA.JK",
            snapshot_id=snap_id,
            action_type=atype,
            quantity=qty,
            action_value=val,
            response_time_ms=500,
        )
    sess.flush()

    features = extract_session_features(sess, u.id, session_id)

    assert len(features.open_positions) == 1, "Expected 1 open position (BBCA held all 14 rounds)"
    pos = features.open_positions[0]

    # The final price MUST come from the last snapshot (10 500), not avg_price (9 000)
    assert pos["final_price"] == pytest.approx(10_500.0), (
        f"final_price should be 10500 (last snapshot close), got {pos['final_price']} "
        f"(avg_price={pos['avg_price']})"
    )
    assert pos["avg_price"] == pytest.approx(9_000.0)
    assert pos["unrealized_pnl"] == pytest.approx((10_500.0 - 9_000.0) * 10)

    sess.close()


def test_mild_severity_classification():
    """Session with DEI in mild range (0.05–0.14) → FeedbackHistory severity=='mild'."""
    from config import DEI_MILD, DEI_MODERATE
    from modules.analytics.bias_metrics import classify_severity

    # Verify threshold boundary is correct
    assert DEI_MILD < DEI_MODERATE

    # A value in the mild band
    mid = (DEI_MILD + DEI_MODERATE) / 2
    assert classify_severity(mid, 0.5, DEI_MODERATE, DEI_MILD) == "mild"

    # Build a full pipeline that produces a mild DEI
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    for stock_id, ticker, sector, vol_class in STOCKS:
        sess.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=f"{ticker} Corp",
            sector=sector, volatility_class=vol_class, bias_role="test",
        ))
    sess.flush()

    base_date = date(2024, 4, 2)
    for stock_id, _, _, _ in STOCKS:
        price = PRICES[stock_id]
        for day in range(20):
            sess.add(MarketSnapshot(
                stock_id=stock_id, date=base_date + timedelta(days=day),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000_000,
                ma_5=price, ma_20=price, rsi_14=50.0,
                volatility_20d=0.02, trend="neutral", daily_return=0.0,
            ))
    sess.flush()

    u = User(alias="mild_user", experience_level="beginner")
    sess.add(u)
    sess.flush()

    # Craft a session: buy 1 winner (sell at gain), hold 1 loser (open at loss)
    # → PGR > 0, PLR = 0 → DEI > 0 but small (one trade each)
    # With equal counts, DEI = PGR - PLR = 1/(1+0) - 0/(0+1) = 1 → too high
    # Use: sell winner, hold losers, keep DEI between 0.05 and 0.15
    # Easiest: use the bias_metrics API directly with a crafted BiasMetric
    session_id = str(uuid.uuid4())
    from database.models import FeedbackHistory
    from modules.cdt.profile import get_or_create_profile

    # Directly create a BiasMetric with mild DEI
    mild_dei = (DEI_MILD + DEI_MODERATE) / 2  # ~0.10
    metric = BiasMetric(
        user_id=u.id, session_id=session_id,
        overconfidence_score=0.1,
        disposition_pgr=mild_dei + 0.3, disposition_plr=0.3,
        disposition_dei=mild_dei,
        loss_aversion_index=1.0,
    )
    sess.add(metric)
    sess.flush()

    profile = get_or_create_profile(sess, u.id)
    generate_feedback(sess, u.id, session_id, metric, profile)

    feedback_records = sess.query(FeedbackHistory).filter_by(
        user_id=u.id, session_id=session_id, bias_type="disposition_effect"
    ).all()
    assert len(feedback_records) == 1
    assert feedback_records[0].severity == "mild", (
        f"Expected 'mild' for DEI={mild_dei:.3f}, got '{feedback_records[0].severity}'"
    )
    sess.close()


def test_full_pipeline_with_twelve_stocks():
    """Full pipeline test with 12 stocks (6 original + 6 new IDX additions).

    Verifies that the analytics pipeline handles the expanded stock universe:
    14 rounds × 12 stocks = 168 UserActions expected.
    """
    TWELVE_STOCKS = [
        ("BBCA.JK", "BBCA", "Finance", "low"),
        ("TLKM.JK", "TLKM", "Telecom", "low_medium"),
        ("ANTM.JK", "ANTM", "Mining", "high"),
        ("GOTO.JK", "GOTO", "Technology", "high"),
        ("UNVR.JK", "UNVR", "Consumer", "medium"),
        ("BBRI.JK", "BBRI", "Finance", "medium"),
        ("ASII.JK", "ASII", "Conglomerate", "medium"),
        ("BMRI.JK", "BMRI", "Finance", "low_medium"),
        ("ICBP.JK", "ICBP", "Consumer", "low"),
        ("MDKA.JK", "MDKA", "Mining", "high"),
        ("BRIS.JK", "BRIS", "Finance", "medium"),
        ("EMTK.JK", "EMTK", "Media & Tech", "high"),
    ]
    TWELVE_PRICES = {
        "BBCA.JK": 9000.0, "TLKM.JK": 3000.0, "ANTM.JK": 2000.0,
        "GOTO.JK": 70.0, "UNVR.JK": 2000.0, "BBRI.JK": 4000.0,
        "ASII.JK": 5000.0, "BMRI.JK": 5500.0, "ICBP.JK": 10000.0,
        "MDKA.JK": 3000.0, "BRIS.JK": 2000.0, "EMTK.JK": 1500.0,
    }

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    for stock_id, ticker, sector, vol_class in TWELVE_STOCKS:
        sess.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=f"{ticker} Corp",
            sector=sector, volatility_class=vol_class, bias_role="test",
        ))
    sess.flush()

    base_date = date(2024, 4, 2)
    snap_ids: dict[str, list[int]] = {s[0]: [] for s in TWELVE_STOCKS}
    for stock_id, _, _, _ in TWELVE_STOCKS:
        price = TWELVE_PRICES[stock_id]
        for day in range(50):
            snap = MarketSnapshot(
                stock_id=stock_id,
                date=base_date + timedelta(days=day),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000_000,
                ma_5=price, ma_20=price, rsi_14=50.0,
                volatility_20d=0.02, trend="neutral", daily_return=0.0,
            )
            sess.add(snap)
            sess.flush()
            snap_ids[stock_id].append(snap.id)
    sess.flush()

    u = User(alias="twelve_stock_user", experience_level="beginner")
    sess.add(u)
    sess.flush()

    session_id = str(uuid.uuid4())

    # Log 14 rounds × 12 stocks; buy BBCA and MDKA in round 1, sell BBCA in round 14
    bought_qty: dict[str, int] = {}
    for rnd in range(1, 15):
        for stock_id, _, _, _ in TWELVE_STOCKS:
            sid_snaps = snap_ids[stock_id]
            snap_id = sid_snaps[rnd - 1]
            price = TWELVE_PRICES[stock_id]

            if rnd == 1 and stock_id in ("BBCA.JK", "MDKA.JK"):
                qty = 5
                atype = "buy"
                bought_qty[stock_id] = qty
                val = qty * price
            elif rnd == 14 and stock_id == "BBCA.JK" and stock_id in bought_qty:
                qty = bought_qty[stock_id]
                atype = "sell"
                val = qty * price
            else:
                qty = 0
                atype = "hold"
                val = 0.0

            log_action(
                session=sess,
                user_id=u.id,
                session_id=session_id,
                scenario_round=rnd,
                stock_id=stock_id,
                snapshot_id=snap_id,
                action_type=atype,
                quantity=qty,
                action_value=val,
                response_time_ms=500,
            )
    sess.flush()

    # Verify action count: 14 rounds × 12 stocks = 168
    action_count = sess.query(UserAction).filter_by(
        user_id=u.id, session_id=session_id
    ).count()
    assert action_count == 14 * 12, f"Expected 168 actions, got {action_count}"

    # Run full pipeline
    metric = compute_and_save_metrics(sess, u.id, session_id)
    assert 0.0 <= (metric.overconfidence_score or 0.0) <= 1.0
    assert metric.disposition_dei is not None
    assert metric.loss_aversion_index is not None

    profile = update_profile(sess, u.id, metric, session_id)
    assert profile.session_count == 1
    assert 0.0 <= profile.risk_preference <= 1.0

    features = extract_session_features(sess, u.id, session_id)
    feedbacks = generate_feedback(
        db_session=sess,
        user_id=u.id,
        session_id=session_id,
        bias_metric=metric,
        profile=profile,
        realized_trades=features.realized_trades,
        open_positions=features.open_positions,
    )
    assert len(feedbacks) == 3

    sess.close()
