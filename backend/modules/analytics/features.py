"""
modules/analytics/features.py — Session feature extraction pipeline.

Transforms raw UserAction rows into a structured SessionFeatures dataclass
that the bias-metrics module consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from config import INITIAL_CAPITAL, ROUNDS_PER_SESSION
from database.models import MarketSnapshot, UserAction


@dataclass
class SessionFeatures:
    """All features needed to compute the three bias metrics for one session.

    Attributes:
        user_id:         User identifier.
        session_id:      UUID string for the session.
        buy_count:       Total buy actions (quantity > 0).
        sell_count:      Total sell actions (quantity > 0).
        hold_count:      Total hold / zero-quantity actions.
        initial_value:   Portfolio value at session start (always INITIAL_CAPITAL).
        final_value:     Portfolio value at session end (cash + remaining holdings).
        realized_trades: List of dicts describing completed buy→sell round-trips.
                         Keys: stock_id, buy_round, sell_round, buy_price,
                               sell_price, quantity.
        open_positions:  List of dicts for holdings still open at session end.
                         Keys: stock_id, quantity, avg_price, final_price,
                               rounds_held.
        response_times:  Response times in milliseconds per action.
    """

    user_id: int
    session_id: str
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    initial_value: float = INITIAL_CAPITAL
    final_value: float = INITIAL_CAPITAL
    realized_trades: list = field(default_factory=list)
    open_positions: list = field(default_factory=list)
    response_times: list = field(default_factory=list)
    realized_trade_count: int = 0       # Number of completed buy→sell round-trips this session
    # Derived timing and return metrics (populated at end of extract_session_features)
    avg_response_time_ms: float = 0.0
    max_response_time_ms: int = 0
    portfolio_return_pct: float = 0.0
    # ── Technical indicator behavioral features ──────────────────────────────
    # These are populated by extract_session_features() when MarketSnapshot
    # indicator columns (rsi_14, ma_20, volatility_20d, trend) are non-null.
    # All rates are in [0.0, 1.0]; averages use the full action set.
    avg_rsi_at_buy: float = 0.0           # Mean RSI-14 at all buy actions
    overbought_buy_rate: float = 0.0      # Fraction of buys where RSI > 70 (overbought zone)
    avg_rsi_at_sell: float = 0.0          # Mean RSI-14 at all sell actions
    trend_following_buy_rate: float = 0.0 # Fraction of buys where trend = "up"
    counter_trend_hold_rate: float = 0.0  # Fraction of holds where trend = "down"
    avg_volatility_at_buy: float = 0.0    # Mean 20-day rolling volatility at buy actions
    buy_above_ma20_rate: float = 0.0      # Fraction of buys where close > MA20


def extract_session_features(
    db_session: Session, user_id: int, session_id: str
) -> SessionFeatures:
    """Build a SessionFeatures object from the database for a completed session.

    The function reconstructs portfolio state by replaying UserAction rows in
    round order, tracking cost basis and open positions, then computing the
    final portfolio value from the last available snapshot prices.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user whose session to analyse.
        session_id: UUID string of the completed session.

    Returns:
        Populated SessionFeatures dataclass.
    """
    actions = (
        db_session.query(UserAction)
        .filter_by(user_id=user_id, session_id=session_id)
        .order_by(UserAction.scenario_round, UserAction.timestamp)
        .all()
    )

    features = SessionFeatures(user_id=user_id, session_id=session_id)
    features.initial_value = INITIAL_CAPITAL

    # ── Pre-pass: batch-fetch all MarketSnapshot rows for indicator data ─────
    # This avoids N+1 queries inside the main loop. We gather all unique
    # snapshot_ids from the action set, fetch in one query, then cache.
    all_snapshot_ids = list({a.snapshot_id for a in actions if a.snapshot_id})
    snapshot_cache: dict[int, MarketSnapshot] = {}
    if all_snapshot_ids:
        snaps = (
            db_session.query(MarketSnapshot)
            .filter(MarketSnapshot.id.in_(all_snapshot_ids))
            .all()
        )
        snapshot_cache = {s.id: s for s in snaps}

    cash = INITIAL_CAPITAL
    # holdings: stock_id → {quantity, avg_price, buy_round}
    holdings: dict[str, dict] = {}
    realized_trades: list[dict] = []
    response_times: list[int] = []

    # Snapshot prices used for final valuation: {snapshot_id: close}
    snap_prices: dict[int, float] = {}

    # Pass 1: replay trades chronologically
    for action in actions:
        response_times.append(action.response_time_ms)

        # Cache snapshot price
        if action.snapshot_id not in snap_prices:
            snap = db_session.get(MarketSnapshot, action.snapshot_id)
            if snap:
                snap_prices[action.snapshot_id] = snap.close

        price = snap_prices.get(action.snapshot_id, 0.0)

        if action.action_type == "buy" and action.quantity > 0:
            features.buy_count += 1
            cost = action.quantity * price
            cash -= cost
            sid = action.stock_id
            if sid in holdings:
                h = holdings[sid]
                total_qty = h["quantity"] + action.quantity
                h["avg_price"] = (
                    h["avg_price"] * h["quantity"] + price * action.quantity
                ) / total_qty
                h["quantity"] = total_qty
            else:
                holdings[sid] = {
                    "quantity": action.quantity,
                    "avg_price": price,
                    "buy_round": action.scenario_round,
                }

        elif action.action_type == "sell" and action.quantity > 0:
            features.sell_count += 1
            sid = action.stock_id
            if sid in holdings:
                h = holdings[sid]
                proceeds = action.quantity * price
                cash += proceeds
                realized_trades.append({
                    "stock_id": sid,
                    "buy_round": h["buy_round"],
                    "sell_round": action.scenario_round,
                    "buy_price": h["avg_price"],
                    "sell_price": price,
                    "quantity": action.quantity,
                })
                h["quantity"] -= action.quantity
                if h["quantity"] <= 0:
                    del holdings[sid]
        else:
            features.hold_count += 1

    # Pass 2: final snapshot prices for open positions
    # Query MarketSnapshot directly for each held stock at the window end date.
    # This handles the case where a stock was HOLDed all 14 rounds (no sell action),
    # which means snap_prices may not contain that stock's round-14 price.
    last_round = max((a.scenario_round for a in actions), default=ROUNDS_PER_SESSION)
    last_prices: dict[str, float] = {}
    if holdings and actions:
        # Determine window end date from the snapshot of the chronologically last action
        last_action = max(actions, key=lambda a: (a.scenario_round, a.timestamp))
        last_snap = db_session.get(MarketSnapshot, last_action.snapshot_id)
        window_end_date = last_snap.date if last_snap else None
        if window_end_date:
            # Batch-fetch all end-of-window prices in one query (avoids N+1)
            end_snaps = (
                db_session.query(MarketSnapshot)
                .filter(MarketSnapshot.stock_id.in_(list(holdings.keys())))
                .filter(MarketSnapshot.date == window_end_date)
                .all()
            )
            for snap in end_snaps:
                last_prices[snap.stock_id] = snap.close

    open_positions: list[dict] = []
    for sid, h in holdings.items():
        final_price = last_prices.get(sid, h["avg_price"])  # fallback only if DB has no data
        open_positions.append({
            "stock_id": sid,
            "quantity": h["quantity"],
            "avg_price": h["avg_price"],
            "final_price": final_price,
            "rounds_held": last_round - h["buy_round"],
            "unrealized_pnl": (final_price - h["avg_price"]) * h["quantity"],
        })

    # Final portfolio value
    market_value = sum(
        p["quantity"] * p["final_price"] for p in open_positions
    )
    features.final_value = cash + market_value
    features.realized_trades = realized_trades
    features.realized_trade_count = len(realized_trades)
    features.open_positions = open_positions
    features.response_times = response_times

    # Derived timing and return metrics
    if response_times:
        features.avg_response_time_ms = sum(response_times) / len(response_times)
        features.max_response_time_ms = max(response_times)
    features.portfolio_return_pct = (
        (features.final_value - features.initial_value)
        / max(features.initial_value, 1.0)
    ) * 100.0

    # ── Pass 3: compute technical indicator behavioral statistics ─────────────
    buy_rsi_vals: list[float] = []
    sell_rsi_vals: list[float] = []
    overbought_buys: int = 0
    trend_following_buys: int = 0
    counter_trend_holds: int = 0
    volatility_at_buy: list[float] = []
    buy_above_ma20: int = 0
    total_holds: int = 0

    for action in actions:
        snap = snapshot_cache.get(action.snapshot_id)
        if snap is None:
            continue

        rsi = getattr(snap, "rsi_14", None)
        ma20 = getattr(snap, "ma_20", None)
        vol = getattr(snap, "volatility_20d", None)
        trend = getattr(snap, "trend", None)
        close = getattr(snap, "close", None)

        if action.action_type == "buy" and action.quantity > 0:
            if rsi is not None:
                buy_rsi_vals.append(float(rsi))
                if float(rsi) > 70.0:
                    overbought_buys += 1
            if trend == "up":
                trend_following_buys += 1
            if vol is not None:
                volatility_at_buy.append(float(vol))
            if close is not None and ma20 is not None and float(close) > float(ma20):
                buy_above_ma20 += 1

        elif action.action_type == "sell" and action.quantity > 0:
            if rsi is not None:
                sell_rsi_vals.append(float(rsi))

        else:  # hold
            total_holds += 1
            if trend == "down":
                counter_trend_holds += 1

    # Populate SessionFeatures indicator fields
    n_buys = features.buy_count

    features.avg_rsi_at_buy = (sum(buy_rsi_vals) / len(buy_rsi_vals)) if buy_rsi_vals else 0.0
    features.avg_rsi_at_sell = (sum(sell_rsi_vals) / len(sell_rsi_vals)) if sell_rsi_vals else 0.0
    features.overbought_buy_rate = (overbought_buys / n_buys) if n_buys > 0 else 0.0
    features.trend_following_buy_rate = (trend_following_buys / n_buys) if n_buys > 0 else 0.0
    features.counter_trend_hold_rate = (counter_trend_holds / total_holds) if total_holds > 0 else 0.0
    features.avg_volatility_at_buy = (sum(volatility_at_buy) / len(volatility_at_buy)) if volatility_at_buy else 0.0
    features.buy_above_ma20_rate = (buy_above_ma20 / n_buys) if n_buys > 0 else 0.0

    return features
