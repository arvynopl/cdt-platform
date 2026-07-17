"""
synthetic_validation/agents.py — Behavioral trading agents (pure Python).

Two families:
  1. Five RATIONAL base strategies (the "rational scaffold"). They decide
     buy/sell/hold from price/indicator SIGNALS only — never from a gain/loss
     reference point — so they serve as negative controls (expected DEI ≈ 0).
  2. A DISPOSITION overlay agent that injects the disposition effect as a
     behavioral rule: realize winners quickly, refuse to realize losers until
     a much larger adverse move. Severity is controlled by the asymmetry knob
     ``k`` (loser threshold = k × winner threshold).

CRITICAL: This module performs NO bias-metric math (no PGR/PLR/OCS/LAI). It only
emits trade decisions. The agent keeps a tiny internal cost-basis ledger purely
to evaluate its own behavioral rules; this is decision bookkeeping, not detection
logic, and is fully independent of modules.analytics.

All randomness flows through an injected ``random.Random`` for reproducibility.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bar:
    """One round of market data for one stock (read from MarketSnapshot)."""
    round_num: int            # 1..ROUNDS
    stock_id: str
    close: float
    ma_5: float | None
    ma_20: float | None
    rsi_14: float | None
    trend: str | None      # "up" | "down" | "neutral" | None


@dataclass(frozen=True)
class Decision:
    """A single emitted action. quantity == 0 ⇒ hold."""
    round_num: int
    stock_id: str
    action_type: str          # "buy" | "sell" | "hold"
    quantity: int


@dataclass
class _Holding:
    """Internal cost-basis ledger for the AGENT'S OWN rule evaluation only."""
    quantity: int
    avg_cost: float
    buy_round: int


# Severity → (gain_take, loss_tolerance): the agent realizes a WINNER once its
# paper gain reaches +gain_take, but refuses to realize a LOSER until its paper
# loss reaches -loss_tolerance. gain_take == loss_tolerance is symmetric
# (rational); loss_tolerance ≫ gain_take injects the disposition effect by
# letting losers linger as open paper losses while winners are cashed in. The
# asymmetry grows with severity. Values are chosen for BEHAVIORAL plausibility
# (a reluctance-to-realize-losses gap), NOT tuned to the detector's DEI
# thresholds — that would be a soft inverse-crime.
DISPOSITION_PROFILES: dict[str, tuple[float, float]] = {
    "none":     (0.01, 0.01),   # symmetric realization
    "mild":     (0.01, 0.05),
    "moderate": (0.01, 0.12),
    "severe":   (0.01, 0.50),   # essentially never realize a loser in-window
}

GAIN_THRESHOLD: float = 0.01    # default winner take-profit threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _equal_weight_qty(price: float, capital_slice: float) -> int:
    """Shares affordable for one stock given an equal-weight capital slice."""
    if price <= 0:
        return 0
    return max(int(capital_slice // price), 0)


def _window_by_stock(bars: list[Bar]) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    for b in bars:
        out.setdefault(b.stock_id, []).append(b)
    for sid in out:
        out[sid].sort(key=lambda x: x.round_num)
    return out


# ---------------------------------------------------------------------------
# Disposition overlay agent (the graded-severity signal source)
# ---------------------------------------------------------------------------
def disposition_agent(
    bars: list[Bar],
    *,
    gain_take: float,
    loss_tolerance: float,
    initial_capital: float,
    rng: random.Random | None = None,
) -> list[Decision]:
    """Buy an equal-weight basket at round 1, then each subsequent round apply
    an asymmetric realization rule:

        - paper gain >=  +gain_take        → SELL (realize winner)
        - paper loss <=  -loss_tolerance   → SELL (realize loser, reluctantly)
        - otherwise                        → HOLD

    gain_take == loss_tolerance is symmetric (rational). loss_tolerance ≫
    gain_take makes winners realized far more readily than losers, so realized
    gains accumulate while losers linger as open paper losses — the behavioral
    signature of the disposition effect. The detector independently measures the
    resulting DEI; this function never computes PGR/PLR/DEI.
    """
    by_stock = _window_by_stock(bars)
    stock_ids = sorted(by_stock.keys())
    if not stock_ids:
        return []
    capital_slice = initial_capital / len(stock_ids)
    rounds = max(b.round_num for b in bars)

    decisions: list[Decision] = []
    holdings: dict[str, _Holding] = {}

    # Round 1: buy the basket.
    for sid in stock_ids:
        first = by_stock[sid][0]
        qty = _equal_weight_qty(first.close, capital_slice)
        if qty > 0:
            decisions.append(Decision(1, sid, "buy", qty))
            holdings[sid] = _Holding(qty, first.close, 1)
        else:
            decisions.append(Decision(1, sid, "hold", 0))

    # Rounds 2..N: asymmetric take-profit / loss-tolerance realization.
    for r in range(2, rounds + 1):
        for sid in stock_ids:
            bar = next((b for b in by_stock[sid] if b.round_num == r), None)
            if bar is None:
                continue
            h = holdings.get(sid)
            if h is None:
                decisions.append(Decision(r, sid, "hold", 0))
                continue
            move = (bar.close / h.avg_cost) - 1.0 if h.avg_cost > 0 else 0.0
            if move >= gain_take or move <= -loss_tolerance:
                decisions.append(Decision(r, sid, "sell", h.quantity))
                del holdings[sid]
            else:
                decisions.append(Decision(r, sid, "hold", 0))
    return decisions


# Severity → number of round-trips (buy→sell pairs) the OVERCONFIDENCE agent
# executes. Overconfidence manifests as overtrading (Barber & Odean, 2000): a
# high turnover that erodes net performance. More round-trips ⇒ higher trade
# frequency ⇒ higher detected OCS. Values chosen for behavioral plausibility,
# NOT tuned to OCS thresholds.
OVERCONFIDENCE_PROFILES: dict[str, int] = {
    "none": 1,
    "mild": 4,
    "moderate": 8,
    "severe": 13,
}

# Severity → (winner_hold, loser_hold): rounds an agent holds a position that
# is in gain vs. in loss before realizing it. Loss aversion (Kahneman &
# Tversky, 1979) = holding losers longer than winners. loser_hold > winner_hold
# injects it; the gap grows with severity. Behavioral knob, NOT tuned to LAI
# thresholds.
LOSS_AVERSION_PROFILES: dict[str, tuple[int, int]] = {
    "none":     (3, 3),
    "mild":     (2, 4),
    "moderate": (2, 6),
    "severe":   (2, 10),
}


def overconfidence_agent(
    bars: list[Bar],
    *,
    n_roundtrips: int,
    initial_capital: float,
    rng: random.Random | None = None,
) -> list[Decision]:
    """Execute ``n_roundtrips`` buy→sell round-trips on distinct (stock, round)
    slots — injecting overtrading. Each round-trip buys a stock in one round and
    sells it the next. Higher n_roundtrips ⇒ higher trade frequency, which the
    detector independently turns into a higher Overconfidence Score. This agent
    never computes OCS."""
    by_stock = _window_by_stock(bars)
    stock_ids = sorted(by_stock.keys())
    if not stock_ids:
        return []
    capital_slice = initial_capital / len(stock_ids)
    rounds = max(b.round_num for b in bars)
    n = max(0, min(n_roundtrips, rounds - 1))

    decisions: list[Decision] = []
    for i in range(n):
        sid = stock_ids[i % len(stock_ids)]
        buy_round = (i % (rounds - 1)) + 1
        sell_round = buy_round + 1
        buy_bar = next((b for b in by_stock[sid] if b.round_num == buy_round), None)
        if buy_bar is None:
            continue
        qty = _equal_weight_qty(buy_bar.close, capital_slice)
        if qty <= 0:
            continue
        decisions.append(Decision(buy_round, sid, "buy", qty))
        decisions.append(Decision(sell_round, sid, "sell", qty))
    if not decisions:
        # Degenerate (n=0): a single hold so the session is non-empty.
        decisions.append(Decision(1, stock_ids[0], "hold", 0))
    return decisions


def loss_aversion_agent(
    bars: list[Bar],
    *,
    winner_hold: int,
    loser_hold: int,
    initial_capital: float,
    rng: random.Random | None = None,
) -> list[Decision]:
    """Buy an equal-weight basket at round 1, then realize each position after a
    holding period that depends on its sign: winners after ``winner_hold``
    rounds, losers after ``loser_hold`` rounds (loser_hold ≥ winner_hold injects
    loss aversion). Any position still open at the final round is force-realized,
    so every position becomes a realized trade with a measurable holding period.
    The detector independently computes LAI from these holding periods."""
    by_stock = _window_by_stock(bars)
    stock_ids = sorted(by_stock.keys())
    if not stock_ids:
        return []
    capital_slice = initial_capital / len(stock_ids)
    rounds = max(b.round_num for b in bars)

    decisions: list[Decision] = []
    holdings: dict[str, _Holding] = {}
    for sid in stock_ids:
        first = by_stock[sid][0]
        qty = _equal_weight_qty(first.close, capital_slice)
        if qty > 0:
            decisions.append(Decision(1, sid, "buy", qty))
            holdings[sid] = _Holding(qty, first.close, 1)
        else:
            decisions.append(Decision(1, sid, "hold", 0))

    for r in range(2, rounds + 1):
        for sid in stock_ids:
            bar = next((b for b in by_stock[sid] if b.round_num == r), None)
            if bar is None:
                continue
            h = holdings.get(sid)
            if h is None:
                decisions.append(Decision(r, sid, "hold", 0))
                continue
            held = r - h.buy_round
            move = (bar.close / h.avg_cost) - 1.0 if h.avg_cost > 0 else 0.0
            threshold = winner_hold if move > 0 else loser_hold
            force = (r == rounds)   # realize everything by the last round
            if held >= threshold or force:
                decisions.append(Decision(r, sid, "sell", h.quantity))
                del holdings[sid]
            else:
                decisions.append(Decision(r, sid, "hold", 0))
    return decisions


# ---------------------------------------------------------------------------
# Five RATIONAL base strategies (negative controls)
# ---------------------------------------------------------------------------
def _basket_buy_round1(
    by_stock: dict[str, list[Bar]], capital_slice: float
) -> tuple[list[Decision], dict[str, _Holding]]:
    decisions: list[Decision] = []
    holdings: dict[str, _Holding] = {}
    for sid in sorted(by_stock):
        first = by_stock[sid][0]
        qty = _equal_weight_qty(first.close, capital_slice)
        if qty > 0:
            decisions.append(Decision(1, sid, "buy", qty))
            holdings[sid] = _Holding(qty, first.close, 1)
        else:
            decisions.append(Decision(1, sid, "hold", 0))
    return decisions, holdings


def buy_and_hold(bars, *, initial_capital, rng=None) -> list[Decision]:
    """Buy basket round 1, hold to the end (no realized trades)."""
    by_stock = _window_by_stock(bars)
    if not by_stock:
        return []
    capital_slice = initial_capital / len(by_stock)
    decisions, holdings = _basket_buy_round1(by_stock, capital_slice)
    rounds = max(b.round_num for b in bars)
    for r in range(2, rounds + 1):
        for sid in sorted(by_stock):
            decisions.append(Decision(r, sid, "hold", 0))
    return decisions


def _signal_strategy(
    bars: list[Bar],
    *,
    initial_capital: float,
    buy_signal: Callable[[Bar], bool],
    sell_signal: Callable[[Bar], bool],
    rng=None,
) -> list[Decision]:
    """Generic signal-driven strategy: buy when buy_signal fires and not held;
    sell when sell_signal fires and held. Exits are signal-based (NOT keyed to
    gain/loss), so realization is roughly symmetric ⇒ low disposition effect."""
    by_stock = _window_by_stock(bars)
    stock_ids = sorted(by_stock.keys())
    if not stock_ids:
        return []
    capital_slice = initial_capital / len(stock_ids)
    rounds = max(b.round_num for b in bars)
    decisions: list[Decision] = []
    holdings: dict[str, _Holding] = {}
    for r in range(1, rounds + 1):
        for sid in stock_ids:
            bar = next((b for b in by_stock[sid] if b.round_num == r), None)
            if bar is None:
                continue
            held = sid in holdings
            if not held and buy_signal(bar):
                qty = _equal_weight_qty(bar.close, capital_slice)
                if qty > 0:
                    decisions.append(Decision(r, sid, "buy", qty))
                    holdings[sid] = _Holding(qty, bar.close, r)
                    continue
            if held and sell_signal(bar):
                decisions.append(Decision(r, sid, "sell", holdings[sid].quantity))
                del holdings[sid]
                continue
            decisions.append(Decision(r, sid, "hold", 0))
    return decisions


def momentum(bars, *, initial_capital, rng=None) -> list[Decision]:
    return _signal_strategy(
        bars, initial_capital=initial_capital,
        buy_signal=lambda b: b.trend == "up",
        sell_signal=lambda b: b.trend == "down",
        rng=rng,
    )


def mean_reversion(bars, *, initial_capital, rng=None) -> list[Decision]:
    return _signal_strategy(
        bars, initial_capital=initial_capital,
        buy_signal=lambda b: b.rsi_14 is not None and b.rsi_14 < 35.0,
        sell_signal=lambda b: b.rsi_14 is not None and b.rsi_14 > 65.0,
        rng=rng,
    )


def ma_crossover(bars, *, initial_capital, rng=None) -> list[Decision]:
    return _signal_strategy(
        bars, initial_capital=initial_capital,
        buy_signal=lambda b: b.ma_5 is not None and b.ma_20 is not None and b.ma_5 > b.ma_20,
        sell_signal=lambda b: b.ma_5 is not None and b.ma_20 is not None and b.ma_5 < b.ma_20,
        rng=rng,
    )


def breakout(bars, *, initial_capital, rng=None) -> list[Decision]:
    return _signal_strategy(
        bars, initial_capital=initial_capital,
        buy_signal=lambda b: b.ma_20 is not None and b.close > b.ma_20,
        sell_signal=lambda b: b.ma_20 is not None and b.close < b.ma_20,
        rng=rng,
    )


# Registry of the five rational base strategies (negative controls).
RATIONAL_STRATEGIES: dict[str, Callable] = {
    "buy_and_hold": buy_and_hold,
    "momentum": momentum,
    "mean_reversion": mean_reversion,
    "ma_crossover": ma_crossover,
    "breakout": breakout,
}
