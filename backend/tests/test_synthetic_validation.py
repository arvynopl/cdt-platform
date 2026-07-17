"""
tests/test_synthetic_validation.py — Tests for the Layer-1 verification harness.

Covers:
  - The anti-"inverse-crime" decoupling guard: the GENERATOR modules
    (agents, runner, ground_truth) must not import modules.analytics.
  - Agent purity and determinism.
  - Disposition overlay produces the intended asymmetric realization behavior
    (more asymmetry ⇒ more winners realized than losers), WITHOUT computing DEI.
  - End-to-end emission → real detector reads the synthetic session.

Uses the shared in-memory ``db`` fixture from conftest.py.
"""

from __future__ import annotations

import ast
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from database.models import MarketSnapshot, StockCatalog, UserAction
from synthetic_validation import agents
from synthetic_validation.agents import Bar, disposition_agent
from synthetic_validation.ground_truth import SyntheticGroundTruth

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_MODULES = ["agents.py", "runner.py", "ground_truth.py"]


# ---------------------------------------------------------------------------
# Decoupling guard (anti "inverse crime")
# ---------------------------------------------------------------------------
def _imported_names(py_path: Path) -> set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module_file", GENERATOR_MODULES)
def test_generator_does_not_import_analytics(module_file):
    """The generator side must share NO math with the detector. Enforced
    structurally: no import of modules.analytics in the generator modules."""
    path = REPO_ROOT / "synthetic_validation" / module_file
    imports = _imported_names(path)
    offending = {m for m in imports if "analytics" in m or "bias_metric" in m}
    assert not offending, (
        f"{module_file} imports detector code {offending} — inverse-crime risk. "
        "Bias must be injected as behavior, measured independently."
    )


# ---------------------------------------------------------------------------
# Agent behavior
# ---------------------------------------------------------------------------
def _synthetic_window(n_stocks=4, rounds=14, *, up_stocks=2) -> list[Bar]:
    """Build a deterministic window: ``up_stocks`` rise monotonically, the rest
    fall monotonically. Lets us assert realization behavior precisely."""
    bars: list[Bar] = []
    for s in range(n_stocks):
        rising = s < up_stocks
        base = 1000.0
        for r in range(1, rounds + 1):
            drift = (r - 1) * (20.0 if rising else -20.0)
            bars.append(Bar(
                round_num=r, stock_id=f"S{s}.JK", close=base + drift,
                ma_5=base + drift, ma_20=base, rsi_14=50.0,
                trend="up" if rising else "down",
            ))
    return bars


def test_disposition_determinism():
    bars = _synthetic_window()
    a = disposition_agent(bars, gain_take=0.01, loss_tolerance=0.12, initial_capital=10_000_000, rng=random.Random(1))
    b = disposition_agent(bars, gain_take=0.01, loss_tolerance=0.12, initial_capital=10_000_000, rng=random.Random(1))
    assert a == b


def test_disposition_asymmetry_realizes_more_winners_than_losers():
    """Strong disposition (loss_tolerance ≫ gain_take) ⇒ winners realized far
    more often than losers, vs. a symmetric profile. Asserted on the EMITTED
    ACTIONS, not on any DEI computation."""
    bars = _synthetic_window(n_stocks=4, up_stocks=2)

    def realized_winners_losers(gain_take, loss_tolerance):
        decs = disposition_agent(
            bars, gain_take=gain_take, loss_tolerance=loss_tolerance,
            initial_capital=10_000_000, rng=random.Random(0),
        )
        sells = [d for d in decs if d.action_type == "sell"]
        # In our deterministic window S0/S1 rise (winners), S2/S3 fall (losers).
        winners = sum(1 for d in sells if d.stock_id in ("S0.JK", "S1.JK"))
        losers = sum(1 for d in sells if d.stock_id in ("S2.JK", "S3.JK"))
        return winners, losers

    w_sym, l_sym = realized_winners_losers(0.01, 0.01)   # symmetric
    w_dis, l_dis = realized_winners_losers(0.01, 0.50)   # strong disposition
    # The winner-minus-loser realization gap widens under disposition.
    assert (w_dis - l_dis) > (w_sym - l_sym)


def test_buy_and_hold_emits_no_sells():
    bars = _synthetic_window()
    decs = agents.buy_and_hold(bars, initial_capital=10_000_000)
    assert all(d.action_type != "sell" for d in decs)
    assert any(d.action_type == "buy" for d in decs)


def test_ground_truth_ordinal():
    gt = SyntheticGroundTruth(
        agent_id="x", session_id="s", base_strategy="disposition_basket",
        injected_bias="disposition", injected_severity="moderate",
        rule_parameters={"k": 4.0}, market_window=("a", "b"), rng_seed=1,
    )
    assert gt.severity_ordinal == 2


# ---------------------------------------------------------------------------
# End-to-end: emitted actions are readable by the real detector
# ---------------------------------------------------------------------------
def _seed_min_market(db, n_stocks=4, rounds=14):
    start = date(2025, 1, 1)
    for s in range(n_stocks):
        sid = f"S{s}.JK"
        db.add(StockCatalog(
            stock_id=sid, ticker=f"S{s}", name=f"Stock {s}",
            sector="Test", volatility_class="medium",
        ))
        rising = s < 2
        for r in range(rounds):
            d = start + timedelta(days=r)
            base = 1000.0 + r * (20.0 if rising else -20.0)
            db.add(MarketSnapshot(
                stock_id=sid, date=d, open=base, high=base, low=base,
                close=base, volume=1000, ma_5=base, ma_20=1000.0,
                rsi_14=50.0, volatility_20d=0.02,
                trend="up" if rising else "down",
            ))
    db.flush()


def test_emitted_session_is_detector_readable(db):
    from synthetic_validation import evaluate, runner
    _seed_min_market(db)
    window = sorted({s.date for s in db.query(MarketSnapshot).all()})
    bars = runner.build_bars(db, window)
    decs = disposition_agent(bars, gain_take=0.01, loss_tolerance=0.50, initial_capital=10_000_000, rng=random.Random(0))
    user = runner.create_shell_user(db, "test0001")
    sid = runner.new_session_id()
    written = runner.emit_session(
        db, user_id=user.id, session_id=sid,
        decisions=decs, window_dates=window, rng=random.Random(0),
    )
    assert written > 0
    assert db.query(UserAction).filter_by(session_id=sid).count() == written

    # Agent-level aggregation across the agent's (here single) session works.
    from synthetic_validation.ground_truth import SyntheticGroundTruth
    gt = SyntheticGroundTruth(
        agent_id="a1", session_id="(multi)", base_strategy="loss_aversion_basket",
        injected_bias="loss_aversion", injected_severity="severe",
        rule_parameters={}, market_window=("a", "b"), rng_seed=0,
    )
    agent_recs = evaluate.build_agent_records(db, [(gt, user.id, [sid])])
    assert len(agent_recs) == 1
    assert agent_recs[0].n_sessions == 1
    assert isinstance(agent_recs[0].lai, float)
    assert agent_recs[0].lai_severity in {"none", "mild", "moderate", "severe"}

    # The REAL detector must run without error and return finite metrics.
    d = evaluate.detect_session(db, user.id, sid)
    assert isinstance(d["dei"], float)
    assert isinstance(d["ocs"], float)
    assert isinstance(d["lai"], float)
    for key in ("dei_severity", "ocs_severity", "lai_severity"):
        assert d[key] in {"none", "mild", "moderate", "severe"}


def test_overconfidence_turnover_monotone():
    """More injected round-trips ⇒ more emitted buy+sell actions (the turnover
    that drives OCS). Asserted on emitted actions, not on any OCS computation."""
    from synthetic_validation.agents import overconfidence_agent
    bars = _synthetic_window(n_stocks=6, rounds=14)

    def n_trades(n_rt):
        decs = overconfidence_agent(bars, n_roundtrips=n_rt, initial_capital=10_000_000)
        return sum(1 for d in decs if d.action_type in ("buy", "sell"))

    assert n_trades(2) < n_trades(6) < n_trades(13)


def test_loss_aversion_holds_losers_longer():
    """Loss-aversion agent realizes losers with longer holding periods than
    winners. Asserted on emitted sell rounds vs buy rounds, not on LAI."""
    from synthetic_validation.agents import loss_aversion_agent
    bars = _synthetic_window(n_stocks=4, up_stocks=2, rounds=14)
    decs = loss_aversion_agent(
        bars, winner_hold=2, loser_hold=10, initial_capital=10_000_000,
    )
    buys = {d.stock_id: d.round_num for d in decs if d.action_type == "buy"}
    holds = {}
    for d in decs:
        if d.action_type == "sell":
            holds[d.stock_id] = d.round_num - buys[d.stock_id]
    # S0/S1 rise (winners → short hold); S2/S3 fall (losers → long hold).
    winner_holds = [holds[s] for s in ("S0.JK", "S1.JK") if s in holds]
    loser_holds = [holds[s] for s in ("S2.JK", "S3.JK") if s in holds]
    assert winner_holds and loser_holds
    assert max(winner_holds) < min(loser_holds)
