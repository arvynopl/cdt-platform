"""
synthetic_validation/run_phase3.py — Phase 3 verification run.

Same three-bias overlays as Phase 2, but evaluated PER AGENT across multiple
sessions. Each synthetic agent is one shell user owning K sessions (different
windows); the detector runs per session and the metrics are averaged into a
per-agent estimate before scoring. This mirrors the production CDT's
cross-session consolidation (EMA) and is the principled fix for the
single-session LAI noise observed in Phase 2 — NOT a change to any threshold or
injection knob.

K_SESSIONS = 3 matches the real-UAT target of ≥3 sessions per participant.

Usage:
    python -m synthetic_validation.run_phase3
"""

from __future__ import annotations

import os
import tempfile

if "CDT_DATABASE_URL" not in os.environ:
    _tmp = os.path.join(tempfile.gettempdir(), "synth_validation_phase3.db")
    if os.path.exists(_tmp):
        os.remove(_tmp)
    os.environ["CDT_DATABASE_URL"] = f"sqlite:///{_tmp}"

import logging
import random
import statistics
from collections import Counter

from config import INITIAL_CAPITAL, ROUNDS_PER_SESSION
from database.connection import get_session, init_db
from database.models import MarketSnapshot
from database.seed import seed_market_snapshots, seed_stock_catalog
from synthetic_validation import agents, evaluate, runner
from synthetic_validation.ground_truth import SyntheticGroundTruth

logging.basicConfig(level=logging.WARNING)

MASTER_SEED = 20260608
N_PER_SEVERITY = 20      # agents per severity per bias
N_PER_STRATEGY = 5       # control agents per rational strategy
K_SESSIONS = int(os.environ.get("CDT_SYNTH_K", "3"))  # sessions/agent (≥3-session UAT target)
SEVERITIES = ["none", "mild", "moderate", "severe"]
BARS = {"rho": 0.80, "recall": 0.85, "precision": 0.80, "exact": 0.70, "within": 0.90}

# Phase 2 single-session ρ, for the side-by-side improvement column.
PHASE2_RHO = {"disposition": 0.820, "overconfidence": 0.968, "loss_aversion": 0.630}


def _full_coverage_dates(session):
    n_stocks = session.query(MarketSnapshot.stock_id).distinct().count()
    counts = Counter(d for (d,) in session.query(MarketSnapshot.date).all())
    return sorted(d for d, c in counts.items() if c == n_stocks)


def _emit_agent_sessions(session, full_dates, base_seed, agent_id, decision_fn):
    """One shell user, K_SESSIONS sessions across different windows."""
    user = runner.create_shell_user(session, agent_id)
    session_ids = []
    for ksess in range(K_SESSIONS):
        rng = random.Random(base_seed * 100 + ksess)
        start = rng.randint(0, len(full_dates) - ROUNDS_PER_SESSION)
        window = full_dates[start:start + ROUNDS_PER_SESSION]
        bars = runner.build_bars(session, window)
        decisions = decision_fn(bars, rng)
        sid = runner.new_session_id()
        runner.emit_session(
            session, user_id=user.id, session_id=sid,
            decisions=decisions, window_dates=window, rng=rng,
        )
        session_ids.append(sid)
    return user.id, session_ids


def _gt(agent_id, sev, bias, params):
    return SyntheticGroundTruth(
        agent_id=agent_id, session_id="(multi)", base_strategy=bias,
        injected_bias="none" if sev == "none" else bias,
        injected_severity=sev, rule_parameters=params,
        market_window=("(multi)", "(multi)"), rng_seed=0,
    )


def _verdict(value, bar, op=">="):
    ok = (value >= bar) if op == ">=" else (value <= bar)
    return "PASS" if ok else "MISS"


def _report(title, bias, graded, eval_set):
    rho = evaluate.spearman_recovery(graded, bias)
    precision, recall = evaluate.presence_precision_recall(eval_set, bias)
    exact, within, catastrophic = evaluate.severity_accuracy(graded, bias)
    cm = evaluate.confusion_matrix(graded, bias)
    field = evaluate.BIAS_FIELDS[bias][0].upper()
    delta = rho - PHASE2_RHO[bias]
    print("\n" + "=" * 66)
    print(f"  {title}")
    print("=" * 66)
    print(f"  Spearman ρ (severity vs |{field}|)  {rho:6.3f}   [bar 0.80]  "
          f"{_verdict(rho, BARS['rho'])}   (Phase 2: {PHASE2_RHO[bias]:.3f}, Δ {delta:+.3f})")
    print(f"  Presence recall                      {recall:6.3f}   [bar 0.85]  {_verdict(recall, BARS['recall'])}")
    print(f"  Presence precision                   {precision:6.3f}   [bar 0.80]  {_verdict(precision, BARS['precision'])}")
    print(f"  Severity exact-match (diagnostic)    {exact:6.3f}   [bar 0.70]  {_verdict(exact, BARS['exact'])}")
    print(f"  Severity within-one-level            {within:6.3f}   [bar 0.90]  {_verdict(within, BARS['within'])}")
    print(f"  Catastrophic errors                  {catastrophic:6d}   [bar 0]     {_verdict(catastrophic, 0, '<=')}")
    print("  Mean |metric| by injected severity:")
    for sev in SEVERITIES:
        vals = [evaluate._val(r, bias) for r in graded if r.injected_severity == sev]
        if vals:
            print(f"    {sev:9s}  mean={statistics.mean(vals):.3f}")
    print("  Confusion matrix (rows=injected, cols=detected):")
    print("    " + cm.to_string().replace("\n", "\n    "))


def main():
    init_db()
    with get_session() as session:
        if session.query(MarketSnapshot).count() == 0:
            seed_stock_catalog(session)
            seed_market_snapshots(session)
        session.commit()
        full_dates = _full_coverage_dates(session)

        idx = 0
        cohorts = {"disposition": [], "overconfidence": [], "loss_aversion": []}
        controls = []

        for sev in SEVERITIES:
            for _ in range(N_PER_SEVERITY):
                gt_take, loss_tol = agents.DISPOSITION_PROFILES[sev]
                aid = f"disp_{sev}_{idx:04d}"
                uid, sids = _emit_agent_sessions(
                    session, full_dates, MASTER_SEED + idx, aid,
                    lambda b, rng: agents.disposition_agent(
                        b, gain_take=gt_take, loss_tolerance=loss_tol,
                        initial_capital=INITIAL_CAPITAL, rng=rng))
                cohorts["disposition"].append(
                    (_gt(aid, sev, "disposition", {"gain_take": gt_take, "loss_tolerance": loss_tol}), uid, sids))
                idx += 1

                n_rt = agents.OVERCONFIDENCE_PROFILES[sev]
                aid = f"over_{sev}_{idx:04d}"
                uid, sids = _emit_agent_sessions(
                    session, full_dates, MASTER_SEED + idx, aid,
                    lambda b, rng: agents.overconfidence_agent(
                        b, n_roundtrips=n_rt, initial_capital=INITIAL_CAPITAL, rng=rng))
                cohorts["overconfidence"].append(
                    (_gt(aid, sev, "overconfidence", {"n_roundtrips": n_rt}), uid, sids))
                idx += 1

                w_hold, l_hold = agents.LOSS_AVERSION_PROFILES[sev]
                aid = f"loss_{sev}_{idx:04d}"
                uid, sids = _emit_agent_sessions(
                    session, full_dates, MASTER_SEED + idx, aid,
                    lambda b, rng: agents.loss_aversion_agent(
                        b, winner_hold=w_hold, loser_hold=l_hold,
                        initial_capital=INITIAL_CAPITAL, rng=rng))
                cohorts["loss_aversion"].append(
                    (_gt(aid, sev, "loss_aversion", {"winner_hold": w_hold, "loser_hold": l_hold}), uid, sids))
                idx += 1

        for strat_name, strat_fn in agents.RATIONAL_STRATEGIES.items():
            for _ in range(N_PER_STRATEGY):
                aid = f"ctrl_{strat_name}_{idx:04d}"
                uid, sids = _emit_agent_sessions(
                    session, full_dates, MASTER_SEED + idx, aid,
                    lambda b, rng, fn=strat_fn: fn(b, initial_capital=INITIAL_CAPITAL, rng=rng))
                controls.append((_gt(aid, "none", "none", {}), uid, sids))
                idx += 1

        session.commit()
        control_records = evaluate.build_agent_records(session, controls)
        bias_records = {b: evaluate.build_agent_records(session, items) for b, items in cohorts.items()}

    titles = {
        "disposition": "DISPOSITION EFFECT (DEI)",
        "overconfidence": "OVERCONFIDENCE (OCS)",
        "loss_aversion": "LOSS AVERSION (LAI)",
    }
    print("\n" + "#" * 66)
    print(f"#  PHASE 3 — PER-AGENT RECOVERY  (K={K_SESSIONS} sessions/agent, "
          f"{N_PER_SEVERITY}/severity, seed {MASTER_SEED})")
    print("#" * 66)
    for bias in ("disposition", "overconfidence", "loss_aversion"):
        graded = bias_records[bias]
        _report(titles[bias], bias, graded, graded + control_records)
    print("\n" + "#" * 66 + "\n")


if __name__ == "__main__":
    main()
