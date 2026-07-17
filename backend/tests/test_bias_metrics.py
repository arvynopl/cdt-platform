"""
tests/test_bias_metrics.py — Unit tests for bias metric formulas.

Critical test scenarios:
    - test_disposition_effect: sells all winners, holds all losers → DEI > 0.5
    - test_overconfidence:      14 trades + portfolio decline → OCS > 0.7
    - test_loss_aversion:       holds losers 3× longer → LAI > 2.0
    - test_ci_*:                bootstrapped confidence-interval properties
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, MarketSnapshot, StockCatalog, User, UserAction
from modules.analytics.bias_metrics import (
    classify_severity,
    compute_and_save_metrics,
    compute_bias_metrics_with_ci,
    compute_disposition_effect,
    compute_loss_aversion_index,
    compute_overconfidence_score,
)
from modules.analytics.features import SessionFeatures

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_features(
    buy_count=0,
    sell_count=0,
    hold_count=0,
    initial_value=10_000_000.0,
    final_value=10_000_000.0,
    realized_trades=None,
    open_positions=None,
):
    f = SessionFeatures(user_id=1, session_id="test-session")
    f.buy_count = buy_count
    f.sell_count = sell_count
    f.hold_count = hold_count
    f.initial_value = initial_value
    f.final_value = final_value
    f.realized_trades = realized_trades or []
    f.open_positions = open_positions or []
    return f


# ---------------------------------------------------------------------------
# Disposition Effect
# ---------------------------------------------------------------------------

def test_disposition_effect_sells_winners_holds_losers():
    """Sells all 5 winners, holds all 3 losers → DEI > 0.5."""
    features = make_features(
        realized_trades=[
            # 5 winning sells
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 5,
             "buy_price": 8000, "sell_price": 9000, "quantity": 100},
            {"stock_id": "BBCA.JK", "buy_round": 2, "sell_round": 6,
             "buy_price": 7500, "sell_price": 8500, "quantity": 50},
            {"stock_id": "TLKM.JK", "buy_round": 1, "sell_round": 4,
             "buy_price": 3000, "sell_price": 3500, "quantity": 200},
            {"stock_id": "BBRI.JK", "buy_round": 3, "sell_round": 8,
             "buy_price": 4000, "sell_price": 4500, "quantity": 100},
            {"stock_id": "ANTM.JK", "buy_round": 2, "sell_round": 7,
             "buy_price": 2000, "sell_price": 2400, "quantity": 200},
        ],
        open_positions=[
            # 3 losing open positions (paper losses)
            {"stock_id": "GOTO.JK", "quantity": 1000, "avg_price": 80,
             "final_price": 60, "rounds_held": 8, "unrealized_pnl": -20000},
            {"stock_id": "UNVR.JK", "quantity": 100, "avg_price": 2500,
             "final_price": 2000, "rounds_held": 5, "unrealized_pnl": -50000},
            {"stock_id": "TLKM.JK", "quantity": 50, "avg_price": 3200,
             "final_price": 2800, "rounds_held": 7, "unrealized_pnl": -20000},
        ],
    )
    pgr, plr, dei = compute_disposition_effect(features)
    assert dei > 0.5, f"Expected DEI > 0.5, got {dei:.4f} (PGR={pgr:.4f}, PLR={plr:.4f})"
    assert pgr > plr


def test_disposition_effect_holds_winners_sells_losers():
    """Sells all losers, holds all winners → DEI < 0 (reversed disposition)."""
    features = make_features(
        realized_trades=[
            {"stock_id": "GOTO.JK", "buy_round": 1, "sell_round": 5,
             "buy_price": 80, "sell_price": 60, "quantity": 1000},
        ],
        open_positions=[
            {"stock_id": "BBCA.JK", "quantity": 100, "avg_price": 8000,
             "final_price": 9000, "rounds_held": 10, "unrealized_pnl": 100000},
        ],
    )
    pgr, plr, dei = compute_disposition_effect(features)
    assert dei < 0


def test_disposition_effect_no_trades():
    """No realized trades and no open positions → DEI = 0."""
    features = make_features()
    pgr, plr, dei = compute_disposition_effect(features)
    assert pgr == 0.0
    assert plr == 0.0
    assert dei == 0.0


def test_disposition_effect_only_paper_gains():
    """Only paper gains (no sells) → PGR = 0, PLR = 0, DEI = 0."""
    features = make_features(
        open_positions=[
            {"stock_id": "BBCA.JK", "quantity": 100, "avg_price": 8000,
             "final_price": 10000, "rounds_held": 5, "unrealized_pnl": 200000},
        ]
    )
    pgr, plr, dei = compute_disposition_effect(features)
    # PGR = 0 / (0 + 1) = 0, PLR = 0 / (0 + 0) = 0
    assert pgr == 0.0
    assert dei == 0.0


# ---------------------------------------------------------------------------
# Overconfidence Score
# ---------------------------------------------------------------------------

def test_overconfidence_high_frequency_poor_performance():
    """14 trades + portfolio decline → OCS > 0.5 (moderate).

    With new shifted-sigmoid formula:
        raw = (14/14) / 0.85 = 1.176 → OCS = 2*(sigmoid(1.176)-0.5) ≈ 0.529
    """
    features = make_features(
        buy_count=7,
        sell_count=7,
        initial_value=10_000_000.0,
        final_value=8_500_000.0,   # 15% decline
    )
    ocs = compute_overconfidence_score(features)
    assert ocs > 0.5, f"Expected OCS > 0.5, got {ocs:.4f}"


def test_overconfidence_low_frequency_good_performance():
    """Low trading, portfolio grew → OCS should be lower."""
    features = make_features(
        buy_count=2,
        sell_count=1,
        initial_value=10_000_000.0,
        final_value=11_000_000.0,  # 10% gain
    )
    ocs_low = compute_overconfidence_score(features)
    features_high = make_features(
        buy_count=7, sell_count=7,
        initial_value=10_000_000.0, final_value=8_500_000.0,
    )
    ocs_high = compute_overconfidence_score(features_high)
    assert ocs_low < ocs_high


def test_overconfidence_no_trades_returns_low():
    """No trades at all → OCS should be low (sigmoid of near-zero)."""
    features = make_features(buy_count=0, sell_count=0)
    ocs = compute_overconfidence_score(features)
    assert 0.0 <= ocs <= 0.6


def test_ocs_zero_trades_returns_zero():
    """All-hold session (0 trades) → OCS = 0.0 exactly.

    raw = 0 → sigmoid(0) = 0.5 → 2*(0.5-0.5) = 0.0
    """
    features = make_features(buy_count=0, sell_count=0)
    ocs = compute_overconfidence_score(features)
    assert ocs == pytest.approx(0.0), f"Expected OCS ≈ 0.0 for zero trades, got {ocs:.6f}"


def test_ocs_single_buy_returns_near_zero():
    """Single buy (1 trade, perf=1.0) → OCS < 0.05.

    raw = (1/14) / 1.0 = 0.071 → OCS = 2*(sigmoid(0.071)-0.5) ≈ 0.036
    """
    features = make_features(
        buy_count=1,
        sell_count=0,
        initial_value=10_000_000.0,
        final_value=10_000_000.0,
    )
    ocs = compute_overconfidence_score(features)
    assert ocs < 0.05, f"Expected OCS < 0.05 for single buy, got {ocs:.6f}"


def test_overconfidence_bounded_zero_to_one():
    """OCS must always be in [0, 1]."""
    for buy, sell, final in [(0, 0, 10_000_000), (14, 0, 1), (7, 7, 8_000_000)]:
        features = make_features(
            buy_count=buy, sell_count=sell,
            initial_value=10_000_000.0, final_value=float(final),
        )
        ocs = compute_overconfidence_score(features)
        assert 0.0 <= ocs <= 1.0


# ---------------------------------------------------------------------------
# Loss Aversion Index
# ---------------------------------------------------------------------------

def test_loss_aversion_holds_losers_3x_longer():
    """Holds losers avg 6 rounds, winners avg 2 rounds → LAI = 3.0 > 2.0."""
    features = make_features(
        realized_trades=[
            # Winners: sold quickly
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 3,
             "buy_price": 8000, "sell_price": 9000, "quantity": 100},
            {"stock_id": "TLKM.JK", "buy_round": 2, "sell_round": 4,
             "buy_price": 3000, "sell_price": 3500, "quantity": 200},
            # Losers: held long
            {"stock_id": "GOTO.JK", "buy_round": 1, "sell_round": 7,
             "buy_price": 80, "sell_price": 60, "quantity": 1000},
            {"stock_id": "UNVR.JK", "buy_round": 2, "sell_round": 8,
             "buy_price": 2500, "sell_price": 2000, "quantity": 100},
        ]
    )
    lai = compute_loss_aversion_index(features)
    assert lai > 2.0, f"Expected LAI > 2.0, got {lai:.4f}"


def test_loss_aversion_equal_holds():
    """Holds winners and losers for the same duration → LAI ≈ 1."""
    features = make_features(
        realized_trades=[
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 5,
             "buy_price": 8000, "sell_price": 9000, "quantity": 100},
            {"stock_id": "GOTO.JK", "buy_round": 1, "sell_round": 5,
             "buy_price": 80, "sell_price": 60, "quantity": 1000},
        ]
    )
    lai = compute_loss_aversion_index(features)
    assert lai == pytest.approx(1.0)


def test_loss_aversion_no_trades_returns_zero():
    """No completed trades → avg_hold_losers=0, avg_hold_winners=0, LAI = 0/1 = 0."""
    features = make_features()
    lai = compute_loss_aversion_index(features)
    assert lai == pytest.approx(0.0)


def test_loss_aversion_only_winners_returns_zero_over_avg():
    """Only winning trades → no loser hold periods → avg_losers = 0 → LAI = 0."""
    features = make_features(
        realized_trades=[
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 4,
             "buy_price": 8000, "sell_price": 9000, "quantity": 100},
        ]
    )
    lai = compute_loss_aversion_index(features)
    # avg_losers = 0, avg_winners = 3 → LAI = 0/3 = 0
    assert lai == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------

def test_classify_severity_severe():
    assert classify_severity(0.65, 0.5, 0.15) == "severe"


def test_classify_severity_moderate():
    assert classify_severity(0.3, 0.5, 0.15) == "moderate"


def test_classify_severity_none():
    assert classify_severity(0.05, 0.5, 0.15) == "none"


def test_classify_severity_boundary_severe():
    assert classify_severity(0.5, 0.5, 0.15) == "severe"


def test_classify_severity_boundary_moderate():
    assert classify_severity(0.15, 0.5, 0.15) == "moderate"


def test_classify_severity_mild_level():
    """Value between mild_t and moderate_t → 'mild'."""
    assert classify_severity(0.10, 0.5, 0.15, mild_t=0.08) == "mild"


def test_classify_severity_mild_boundary():
    """At exactly mild_t → 'mild'; just below → 'none'."""
    assert classify_severity(0.08, 0.5, 0.15, mild_t=0.08) == "mild"
    assert classify_severity(0.07, 0.5, 0.15, mild_t=0.08) == "none"


def test_classify_severity_mild_not_triggered_without_threshold():
    """Existing 3-arg calls still return 'none' below moderate (no mild path)."""
    assert classify_severity(0.10, 0.5, 0.15) == "none"


# ---------------------------------------------------------------------------
# Edge-case: break-even trades in DEI
# ---------------------------------------------------------------------------

def test_disposition_effect_break_even_trades():
    """Break-even sells (sell_price == buy_price) are excluded from both
    realized_gains and realized_losses, per Odean (1998) counting convention.

    With one break-even trade and one open paper gain:
        realized_gains=0, realized_losses=0, paper_gains=1, paper_losses=0
        PGR = 0/(0+1) = 0, PLR = 0/(0+0) = 0 (no denom → 0)
        DEI = 0 - 0 = 0
    """
    features = make_features(
        realized_trades=[
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 5,
             "buy_price": 8000, "sell_price": 8000, "quantity": 100},  # break-even
        ],
        open_positions=[
            {"stock_id": "TLKM.JK", "quantity": 100, "avg_price": 3000,
             "final_price": 3500, "rounds_held": 5, "unrealized_pnl": 50000},
        ],
    )
    pgr, plr, dei = compute_disposition_effect(features)
    # Break-even trade contributes to neither realized_gains nor realized_losses
    assert pgr == pytest.approx(0.0), f"PGR should be 0 (no realized gains), got {pgr}"
    assert plr == pytest.approx(0.0), f"PLR should be 0 (no realized losses), got {plr}"
    assert dei == pytest.approx(0.0), f"DEI should be 0, got {dei}"


def test_disposition_effect_only_break_even_trades():
    """All realized trades are break-even and all open positions are break-even too.
    Every denominator is 0 → PGR=0, PLR=0, DEI=0.
    """
    features = make_features(
        realized_trades=[
            {"stock_id": "BBCA.JK", "buy_round": 1, "sell_round": 3,
             "buy_price": 5000, "sell_price": 5000, "quantity": 50},
            {"stock_id": "TLKM.JK", "buy_round": 2, "sell_round": 6,
             "buy_price": 3000, "sell_price": 3000, "quantity": 200},
        ],
        open_positions=[
            {"stock_id": "GOTO.JK", "quantity": 100, "avg_price": 80,
             "final_price": 80, "rounds_held": 5, "unrealized_pnl": 0},
        ],
    )
    pgr, plr, dei = compute_disposition_effect(features)
    assert pgr == pytest.approx(0.0)
    assert plr == pytest.approx(0.0)
    assert dei == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Edge-case: OCS with catastrophic portfolio loss
# ---------------------------------------------------------------------------

def test_overconfidence_catastrophic_loss():
    """When performance_ratio < 0.01 (portfolio nearly wiped), the floor at 0.01
    causes the raw ratio to be high, pushing OCS toward 1.0 for active traders.

    raw = trade_frequency / max(performance_ratio, 0.01)
    With 14 trades and final_value=1 (from 10M): performance_ratio ≈ 0.0000001
    → max(performance_ratio, 0.01) = 0.01
    → raw = 1.0 / 0.01 = 100 → sigmoid(100) ≈ 1.0 → OCS ≈ 1.0
    """
    features = make_features(
        buy_count=7,
        sell_count=7,
        initial_value=10_000_000.0,
        final_value=1.0,  # catastrophic loss
    )
    ocs = compute_overconfidence_score(features)
    # Result should still be in [0, 1] and be close to 1.0
    assert 0.0 <= ocs <= 1.0, f"OCS out of bounds: {ocs}"
    assert ocs > 0.9, f"Expected OCS near 1.0 for catastrophic loss + max trades, got {ocs:.4f}"


def test_overconfidence_catastrophic_loss_no_trades():
    """Catastrophic loss with zero trades → OCS = 0.0 (no overconfidence signal)."""
    features = make_features(
        buy_count=0,
        sell_count=0,
        initial_value=10_000_000.0,
        final_value=1.0,
    )
    ocs = compute_overconfidence_score(features)
    assert ocs == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------------------

def _make_trades(n_winners: int, n_losers: int) -> list[dict]:
    """Create realized-trade dicts: winners held 2 rounds, losers held 6 rounds."""
    trades = []
    for i in range(n_winners):
        trades.append({
            "stock_id": f"W{i}",
            "buy_round": 1, "sell_round": 3,   # hold = 2
            "buy_price": 100, "sell_price": 110, "quantity": 100,
        })
    for i in range(n_losers):
        trades.append({
            "stock_id": f"L{i}",
            "buy_round": 1, "sell_round": 7,   # hold = 6
            "buy_price": 100, "sell_price": 90, "quantity": 100,
        })
    return trades


def test_ci_contains_point_estimate():
    """For a session with 20 realized trades the bootstrapped 95% CI
    must bracket the point estimate for all three metrics.

    DEI: 10 winners, 10 losers, no open positions → DEI = 0.0.
    LAI: winners held 2 rounds, losers 6 rounds → LAI = 3.0.
    OCS: 20 buys + 20 sells, neutral performance → moderate OCS.

    With a deterministic seed (Random(0)) and 500 replicates the
    empirical 2.5th/97.5th percentiles reliably contain the point estimate.
    """
    features = make_features(
        buy_count=20,
        sell_count=20,
        initial_value=10_000_000.0,
        final_value=10_000_000.0,
        realized_trades=_make_trades(10, 10),
    )
    result = compute_bias_metrics_with_ci(features, n_bootstrap=500)

    assert result.dei_ci[0] <= result.dei <= result.dei_ci[1], (
        f"DEI={result.dei:.4f} not in CI {result.dei_ci}"
    )
    assert result.ocs_ci[0] <= result.ocs <= result.ocs_ci[1], (
        f"OCS={result.ocs:.4f} not in CI {result.ocs_ci}"
    )
    assert result.lai_ci[0] <= result.lai <= result.lai_ci[1], (
        f"LAI={result.lai:.4f} not in CI {result.lai_ci}"
    )


def test_ci_degenerate_below_min_trades():
    """When a session has fewer than 5 realized trades the CI must equal
    (metric, metric) for every metric and low_confidence must be True.
    """
    features = make_features(
        buy_count=3,
        sell_count=3,
        realized_trades=_make_trades(2, 1),   # 3 trades — below threshold
    )
    result = compute_bias_metrics_with_ci(features, n_bootstrap=500)

    assert result.low_confidence is True
    assert result.dei_ci == (result.dei, result.dei)
    assert result.ocs_ci == (result.ocs, result.ocs)
    assert result.lai_ci == (result.lai, result.lai)


def test_ci_width_decreases_with_more_trades():
    """CI width must shrink as the realized trade count grows.

    Both DEI and LAI are computed directly from trade-level data, so the
    bootstrap variance shrinks predictably with sample size.

    5 trades  (3W + 2L): each bootstrap replicate can flip heavily between
                         all-winner and all-loser outcomes → wide CI.
    100 trades (50W + 50L): law of large numbers → outcomes are stable
                             across replicates → narrow CI.
    """
    features_5 = make_features(
        buy_count=5,
        sell_count=5,
        realized_trades=_make_trades(3, 2),
    )
    features_100 = make_features(
        buy_count=100,
        sell_count=100,
        realized_trades=_make_trades(50, 50),
    )

    result_5 = compute_bias_metrics_with_ci(features_5, n_bootstrap=500)
    result_100 = compute_bias_metrics_with_ci(features_100, n_bootstrap=500)

    dei_width_5 = result_5.dei_ci[1] - result_5.dei_ci[0]
    dei_width_100 = result_100.dei_ci[1] - result_100.dei_ci[0]
    assert dei_width_100 < dei_width_5, (
        f"DEI CI should be narrower with 100 trades: "
        f"width_5={dei_width_5:.4f}, width_100={dei_width_100:.4f}"
    )

    lai_width_5 = result_5.lai_ci[1] - result_5.lai_ci[0]
    lai_width_100 = result_100.lai_ci[1] - result_100.lai_ci[0]
    assert lai_width_100 < lai_width_5, (
        f"LAI CI should be narrower with 100 trades: "
        f"width_5={lai_width_5:.4f}, width_100={lai_width_100:.4f}"
    )


# ---------------------------------------------------------------------------
# compute_and_save_metrics — CI column persistence
# ---------------------------------------------------------------------------

_SAVE_STOCKS = [
    ("BBCA.JK", "BBCA", "Bank Central Asia", "Finance", "low"),
    ("ANTM.JK", "ANTM", "Aneka Tambang", "Mining", "high"),
    ("GOTO.JK", "GOTO", "GoTo Gojek Tokopedia", "Technology", "high"),
]
_SAVE_PRICES = {"BBCA.JK": 9000.0, "ANTM.JK": 2000.0, "GOTO.JK": 70.0}


@pytest.fixture()
def _save_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    base_date = date(2024, 4, 2)
    for stock_id, ticker, name, sector, vol in _SAVE_STOCKS:
        sess.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=name,
            sector=sector, volatility_class=vol, bias_role="test",
        ))
    sess.flush()
    for stock_id, _, _, _, _ in _SAVE_STOCKS:
        price = _SAVE_PRICES[stock_id]
        for day in range(20):
            sess.add(MarketSnapshot(
                stock_id=stock_id,
                date=base_date + timedelta(days=day),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000_000,
                ma_5=price, ma_20=price, rsi_14=50.0,
                volatility_20d=0.02, trend="neutral", daily_return=0.0,
            ))
    sess.flush()
    yield sess
    sess.close()


def test_compute_and_save_metrics_persists_ci_columns(_save_db):
    """compute_and_save_metrics must populate all six CI bound columns
    and ci_low_confidence on the returned BiasMetric.

    Session: buy ANTM.JK in round 1, sell in round 8 (winner);
             buy GOTO.JK in round 2, sell in round 10 (winner).
    With only 2 realized trades the CI degenerates (low_confidence=True).
    We assert float types for CI bounds and the low_confidence flag,
    then verify the CI bounds bound the point estimate OR low_confidence is True.
    """
    db = _save_db
    user = User(alias="ci_test_user", experience_level="beginner")
    db.add(user)
    db.flush()

    session_id = str(uuid.uuid4())
    base_date = date(2024, 4, 2)

    def _snap(stock_id, day):
        return (
            db.query(MarketSnapshot)
            .filter_by(stock_id=stock_id, date=base_date + timedelta(days=day))
            .first()
        )

    for stock_id, _, _, _, _ in _SAVE_STOCKS:
        for rnd in range(1, 15):
            snap = _snap(stock_id, rnd - 1)
            db.add(UserAction(
                user_id=user.id, session_id=session_id,
                scenario_round=rnd, stock_id=stock_id,
                snapshot_id=snap.id, action_type="hold",
                quantity=0, action_value=0.0, response_time_ms=500,
            ))
    # Buy ANTM.JK round 1, sell round 8
    snap_buy = _snap("ANTM.JK", 0)
    snap_sell = _snap("ANTM.JK", 7)
    db.add(UserAction(
        user_id=user.id, session_id=session_id,
        scenario_round=1, stock_id="ANTM.JK",
        snapshot_id=snap_buy.id, action_type="buy",
        quantity=100, action_value=200_000.0, response_time_ms=400,
    ))
    db.add(UserAction(
        user_id=user.id, session_id=session_id,
        scenario_round=8, stock_id="ANTM.JK",
        snapshot_id=snap_sell.id, action_type="sell",
        quantity=100, action_value=200_000.0, response_time_ms=400,
    ))
    db.flush()

    metric = compute_and_save_metrics(db, user.id, session_id)

    # CI bound columns must be float
    assert isinstance(metric.dei_ci_lower, float)
    assert isinstance(metric.dei_ci_upper, float)
    assert isinstance(metric.ocs_ci_lower, float)
    assert isinstance(metric.ocs_ci_upper, float)
    assert isinstance(metric.lai_ci_lower, float)
    assert isinstance(metric.lai_ci_upper, float)

    # CI bounds must bracket the point estimate, OR low_confidence is True (degenerate case)
    assert (
        metric.dei_ci_lower <= metric.disposition_dei <= metric.dei_ci_upper
        or metric.ci_low_confidence is True
    )
    assert (
        metric.ocs_ci_lower <= metric.overconfidence_score <= metric.ocs_ci_upper
        or metric.ci_low_confidence is True
    )
    assert (
        metric.lai_ci_lower <= metric.loss_aversion_index <= metric.lai_ci_upper
        or metric.ci_low_confidence is True
    )
