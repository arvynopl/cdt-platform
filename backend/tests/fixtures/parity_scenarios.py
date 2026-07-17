"""tests/fixtures/parity_scenarios.py — golden-master parity scenario runner.

Defines deterministic simulation-session scenarios and executes the FULL
production analytics pipeline over them:

    log_action → extract_session_features → compute_disposition_effect
    → compute_bias_metrics_with_ci → compute_and_save_metrics
    → update_profile → generate_feedback

The module deliberately imports only via the shared package names
(``config``, ``database``, ``modules``) so the exact same file runs against
both codebases:

  * the frozen thesis-defense checkout of TA-18222007 (generator run — the
    recorded output is ``golden_master.json``), and
  * this repo's ported domain layer (``test_golden_master.py`` — must
    reproduce the recording exactly).

Determinism notes:
  * prices, dates, and actions are hard-coded literals;
  * the only RNG in the pipeline (bootstrap CI) is internally seeded
    (``random.Random(0)``) by ``compute_bias_metrics_with_ci``;
  * wall-clock timestamps are excluded from the captured output.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base, MarketSnapshot, StockCatalog, User, UserSurvey
from modules.analytics.bias_metrics import (
    compute_and_save_metrics,
    compute_disposition_effect,
)
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.logger import log_action

# ---------------------------------------------------------------------------
# Deterministic market data: 2 stocks × 20 trading days
# ---------------------------------------------------------------------------

_START = date(2025, 1, 6)  # a Monday

_STOCKS = [
    # (stock_id, ticker, name, sector, volatility_class)
    ("VOLH.JK", "VOLH", "Parity High-Vol", "Mining", "high"),
    ("VOLL.JK", "VOLL", "Parity Low-Vol", "Finance", "low"),
]

_CLOSES: dict[str, list[float]] = {
    "VOLH.JK": [1000, 1050, 980, 1100, 1150, 1120, 1200, 1180, 1080, 1020,
                990, 1130, 1210, 1160, 1170, 1190, 1150, 1140, 1180, 1200],
    "VOLL.JK": [500, 495, 505, 490, 480, 470, 475, 460, 450, 455,
                445, 440, 435, 430, 432, 428, 430, 426, 424, 425],
}

_TRENDS = ["up", "down", "neutral"]


def _trading_dates(n: int) -> list[date]:
    """Return *n* consecutive weekdays starting at _START."""
    out: list[date] = []
    d = _START
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------
# Each action tuple: (round, stock_id, action_type, quantity).
# Rounds without an explicit tuple for a stock are auto-filled with "hold",
# mirroring the production auto-hold logger.

_S_ALL_HOLD: list[tuple[int, str, str, int]] = []

_S_SINGLE_WINNER = [
    (1, "VOLH.JK", "buy", 10),
    (5, "VOLH.JK", "sell", 10),   # 1000 → 1150: realized gain, held 4 rounds
]

_S_LOSER_AND_OPEN = [
    (2, "VOLL.JK", "buy", 20),
    (12, "VOLL.JK", "sell", 20),  # 495 → 440: realized loss, held 10 rounds
    (3, "VOLH.JK", "buy", 5),     # open to end: 980 → 1160 paper gain
]

_S_ONLY_LOSERS = [
    (1, "VOLL.JK", "buy", 10),
    (6, "VOLL.JK", "sell", 10),   # 500 → 470: loss, held 5
    (2, "VOLH.JK", "buy", 10),
    (10, "VOLH.JK", "sell", 10),  # 1050 → 1020: loss, held 8
]

_S_ACTIVE_TRADER = [
    (1, "VOLH.JK", "buy", 10), (2, "VOLH.JK", "sell", 10),    # win, held 1
    (3, "VOLH.JK", "buy", 10), (5, "VOLH.JK", "sell", 10),    # win, held 2
    (6, "VOLH.JK", "buy", 10), (7, "VOLH.JK", "sell", 10),    # win, held 1
    (1, "VOLL.JK", "buy", 15), (4, "VOLL.JK", "sell", 15),    # loss, held 3
    (5, "VOLL.JK", "buy", 15), (9, "VOLL.JK", "sell", 15),    # loss, held 4
    (10, "VOLH.JK", "buy", 8),                                 # open paper gain
]

# (scenario_name, [session action lists...], onboarding_survey or None)
SCENARIOS: list[tuple[str, list[list[tuple[int, str, str, int]]], dict | None]] = [
    ("all_hold", [_S_ALL_HOLD], None),
    ("single_winner", [_S_SINGLE_WINNER], None),
    ("loser_and_open", [_S_LOSER_AND_OPEN], None),
    ("only_losers", [_S_ONLY_LOSERS], None),
    ("active_trader", [_S_ACTIVE_TRADER], None),
    (
        "longitudinal_with_priors",
        [_S_SINGLE_WINNER, _S_ONLY_LOSERS, _S_ACTIVE_TRADER],
        {
            "q_risk_tolerance": 4,
            "q_loss_sensitivity": 5,
            "q_trading_frequency": 2,
            "q_holding_behavior": 4,
        },
    ),
]

ROUNDS = 14


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _seed_market(sess: Session) -> dict[tuple[str, int], MarketSnapshot]:
    """Insert catalog + snapshots; return (stock_id, round_1idx) → snapshot."""
    dates = _trading_dates(20)
    for stock_id, ticker, name, sector, vol in _STOCKS:
        sess.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=name,
            sector=sector, volatility_class=vol,
        ))
    sess.flush()

    by_round: dict[tuple[str, int], MarketSnapshot] = {}
    for stock_id, _, _, _, vol in _STOCKS:
        closes = _CLOSES[stock_id]
        for i, d in enumerate(dates):
            close = float(closes[i])
            snap = MarketSnapshot(
                stock_id=stock_id,
                date=d,
                open=close - 5.0,
                high=close + 10.0,
                low=close - 10.0,
                close=close,
                volume=1_000_000 + 10_000 * i,
                ma_5=close - 8.0,
                ma_20=close - 15.0,
                rsi_14=float(50 + (i * 3) % 40),
                volatility_20d=0.08 if vol == "high" else 0.03,
                trend=_TRENDS[i % 3],
                daily_return=0.01 if i % 2 == 0 else -0.01,
            )
            sess.add(snap)
            sess.flush()
            if i < ROUNDS:
                by_round[(stock_id, i + 1)] = snap
    return by_round


def _run_session(
    sess: Session,
    user_id: int,
    session_id: str,
    actions: list[tuple[int, str, str, int]],
    snaps: dict[tuple[str, int], MarketSnapshot],
) -> dict[str, Any]:
    """Log one session's actions (with production-style auto-hold) and run
    the full analytics pipeline, returning the captured outputs."""
    explicit = {(rnd, sid): (atype, qty) for rnd, sid, atype, qty in actions}

    for rnd in range(1, ROUNDS + 1):
        for stock_id, *_ in _STOCKS:
            snap = snaps[(stock_id, rnd)]
            atype, qty = explicit.get((rnd, stock_id), ("hold", 0))
            log_action(
                session=sess,
                user_id=user_id,
                session_id=session_id,
                scenario_round=rnd,
                stock_id=stock_id,
                snapshot_id=snap.id,
                action_type=atype,
                quantity=qty,
                action_value=qty * snap.close if qty else 0.0,
                response_time_ms=1500,
            )
    sess.flush()

    features = extract_session_features(sess, user_id, session_id)
    pgr, plr, dei_raw = compute_disposition_effect(features)
    metric = compute_and_save_metrics(sess, user_id, session_id)
    profile = update_profile(sess, user_id, metric, session_id)
    generate_feedback(
        db_session=sess,
        user_id=user_id,
        session_id=session_id,
        bias_metric=metric,
        profile=profile,
        realized_trades=features.realized_trades,
        open_positions=features.open_positions,
    )
    sess.flush()

    from database.models import FeedbackHistory
    feedback_rows = (
        sess.query(FeedbackHistory)
        .filter_by(user_id=user_id, session_id=session_id)
        .order_by(FeedbackHistory.bias_type)
        .all()
    )

    return {
        "features": {
            "buy_count": features.buy_count,
            "sell_count": features.sell_count,
            "hold_count": features.hold_count,
            "final_value": features.final_value,
            "realized_trade_count": features.realized_trade_count,
            "portfolio_return_pct": features.portfolio_return_pct,
            "avg_rsi_at_buy": features.avg_rsi_at_buy,
            "avg_rsi_at_sell": features.avg_rsi_at_sell,
            "overbought_buy_rate": features.overbought_buy_rate,
            "trend_following_buy_rate": features.trend_following_buy_rate,
            "counter_trend_hold_rate": features.counter_trend_hold_rate,
            "avg_volatility_at_buy": features.avg_volatility_at_buy,
            "buy_above_ma20_rate": features.buy_above_ma20_rate,
        },
        "disposition": {"pgr": pgr, "plr": plr, "dei": dei_raw},
        "metric": {
            "overconfidence_score": metric.overconfidence_score,
            "disposition_pgr": metric.disposition_pgr,
            "disposition_plr": metric.disposition_plr,
            "disposition_dei": metric.disposition_dei,
            "loss_aversion_index": metric.loss_aversion_index,
            "dei_ci": [metric.dei_ci_lower, metric.dei_ci_upper],
            "ocs_ci": [metric.ocs_ci_lower, metric.ocs_ci_upper],
            "lai_ci": [metric.lai_ci_lower, metric.lai_ci_upper],
            "ci_low_confidence": bool(metric.ci_low_confidence),
        },
        "profile": {
            "bias_intensity_vector": dict(profile.bias_intensity_vector),
            "risk_preference": profile.risk_preference,
            "stability_index": profile.stability_index,
            "session_count": profile.session_count,
            "interaction_scores": (
                dict(profile.interaction_scores)
                if profile.interaction_scores else None
            ),
        },
        "feedback": [
            {
                "bias_type": f.bias_type,
                "severity": f.severity,
                "explanation_text": f.explanation_text,
                "recommendation_text": f.recommendation_text,
            }
            for f in feedback_rows
        ],
    }


def run_all() -> dict[str, Any]:
    """Execute every scenario on a fresh in-memory DB; return captured outputs."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    results: dict[str, Any] = {}

    with factory() as sess:
        snaps = _seed_market(sess)

        for idx, (name, sessions, survey) in enumerate(SCENARIOS):
            user = User(
                username=f"parity_{name}",
                alias=f"parity_{name}",
                experience_level="beginner",
            )
            sess.add(user)
            sess.flush()
            if survey is not None:
                sess.add(UserSurvey(user_id=user.id, **survey))
                sess.flush()

            per_session = []
            for s_i, actions in enumerate(sessions):
                session_id = f"parity-{idx:02d}-{s_i:02d}"
                per_session.append(
                    _run_session(sess, user.id, session_id, actions, snaps)
                )
            results[name] = per_session

    return results


if __name__ == "__main__":
    import json
    import sys

    out = run_all()
    target = sys.argv[1] if len(sys.argv) > 1 else "golden_master.json"
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"Wrote {target}: {sum(len(v) for v in out.values())} sessions "
          f"across {len(out)} scenarios")
