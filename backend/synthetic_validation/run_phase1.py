"""
synthetic_validation/run_phase1.py — Phase 1 verification run.

Builds an ISOLATED SQLite database (never the production cdt_bias.db), seeds it
from the real data files, generates a graded-severity disposition cohort plus
rational-strategy controls, runs the unmodified detector, and reports DEI
recovery against the pre-registered pass-bars.

Usage:
    python -m synthetic_validation.run_phase1            # default temp DB
    CDT_DATABASE_URL=sqlite:///tmp/synth.db python -m synthetic_validation.run_phase1
"""

from __future__ import annotations

# --- Isolate the database BEFORE importing config-bound modules -------------
import os
import tempfile

if "CDT_DATABASE_URL" not in os.environ:
    _tmp = os.path.join(tempfile.gettempdir(), "synth_validation_phase1.db")
    if os.path.exists(_tmp):
        os.remove(_tmp)
    os.environ["CDT_DATABASE_URL"] = f"sqlite:///{_tmp}"
# ---------------------------------------------------------------------------

import logging
import random
from collections import Counter

from config import INITIAL_CAPITAL, ROUNDS_PER_SESSION
from database.connection import get_session, init_db
from database.models import MarketSnapshot
from database.seed import seed_market_snapshots, seed_stock_catalog
from synthetic_validation import agents, evaluate, runner
from synthetic_validation.ground_truth import SyntheticGroundTruth

logging.basicConfig(level=logging.WARNING)

MASTER_SEED = 20260608
N_PER_SEVERITY = 30        # disposition agents per severity level
N_PER_STRATEGY = 10        # rational control runs per strategy
SEVERITIES = ["none", "mild", "moderate", "severe"]


def _full_coverage_dates(session) -> list:
    n_stocks = session.query(MarketSnapshot.stock_id).distinct().count()
    counts = Counter(d for (d,) in session.query(MarketSnapshot.date).all())
    return sorted(d for d, c in counts.items() if c == n_stocks)


def _pick_window(full_dates, rounds, rng):
    start = rng.randint(0, len(full_dates) - rounds)
    return full_dates[start:start + rounds]


def main() -> None:
    init_db()
    with get_session() as session:
        if session.query(MarketSnapshot).count() == 0:
            seed_stock_catalog(session)
            seed_market_snapshots(session)
        session.commit()

        full_dates = _full_coverage_dates(session)
        items = []           # list[(SyntheticGroundTruth, user_id)]
        idx = 0

        # --- Disposition cohort (graded severity) ---------------------------
        for sev in SEVERITIES:
            gain_take, loss_tol = agents.DISPOSITION_PROFILES[sev]
            for _ in range(N_PER_SEVERITY):
                seed = MASTER_SEED + idx
                rng = random.Random(seed)
                window = _pick_window(full_dates, ROUNDS_PER_SESSION, rng)
                bars = runner.build_bars(session, window)
                decisions = agents.disposition_agent(
                    bars, gain_take=gain_take, loss_tolerance=loss_tol,
                    initial_capital=INITIAL_CAPITAL, rng=rng,
                )
                agent_id = f"disp_{sev}_{idx:04d}"
                user = runner.create_shell_user(session, agent_id)
                sid = runner.new_session_id()
                runner.emit_session(
                    session, user_id=user.id, session_id=sid,
                    decisions=decisions, window_dates=window, rng=rng,
                )
                gt = SyntheticGroundTruth(
                    agent_id=agent_id, session_id=sid,
                    base_strategy="disposition_basket",
                    injected_bias="none" if sev == "none" else "disposition",
                    injected_severity=sev,
                    rule_parameters={"gain_take": gain_take, "loss_tolerance": loss_tol},
                    market_window=(window[0].isoformat(), window[-1].isoformat()),
                    rng_seed=seed,
                )
                items.append((gt, user.id))
                idx += 1

        # --- Rational-strategy controls (injected none) ---------------------
        for strat_name, strat_fn in agents.RATIONAL_STRATEGIES.items():
            for _ in range(N_PER_STRATEGY):
                seed = MASTER_SEED + idx
                rng = random.Random(seed)
                window = _pick_window(full_dates, ROUNDS_PER_SESSION, rng)
                bars = runner.build_bars(session, window)
                decisions = strat_fn(bars, initial_capital=INITIAL_CAPITAL, rng=rng)
                agent_id = f"ctrl_{strat_name}_{idx:04d}"
                user = runner.create_shell_user(session, agent_id)
                sid = runner.new_session_id()
                runner.emit_session(
                    session, user_id=user.id, session_id=sid,
                    decisions=decisions, window_dates=window, rng=rng,
                )
                gt = SyntheticGroundTruth(
                    agent_id=agent_id, session_id=sid,
                    base_strategy=strat_name,
                    injected_bias="none", injected_severity="none",
                    rule_parameters={},
                    market_window=(window[0].isoformat(), window[-1].isoformat()),
                    rng_seed=seed,
                )
                items.append((gt, user.id))
                idx += 1

        session.commit()

        # --- Score with the REAL detector -----------------------------------
        records = evaluate.build_records(session, items)

    # --- Report -------------------------------------------------------------
    disp_records = [r for r in records if r.agent_id.startswith("disp_")]
    rho = evaluate.spearman_recovery(disp_records)
    precision, recall = evaluate.presence_precision_recall(records)
    exact, within, catastrophic = evaluate.severity_accuracy(disp_records)
    cm = evaluate.confusion_matrix(disp_records)

    def _verdict(value, bar, op=">="):
        ok = (value >= bar) if op == ">=" else (value <= bar)
        return "PASS" if ok else "FAIL"

    print("\n" + "=" * 64)
    print("  PHASE 1 — DISPOSITION-EFFECT RECOVERY (Layer-1 verification)")
    print("=" * 64)
    print(f"  Cohort: {len(disp_records)} disposition agents "
          f"({N_PER_SEVERITY}/severity) + {len(records)-len(disp_records)} rational controls")
    print(f"  Master seed: {MASTER_SEED}  (fully reproducible)")
    print("-" * 64)
    print(f"  Spearman ρ (injected severity vs |DEI|)   {rho:6.3f}   "
          f"[bar 0.80]  {_verdict(rho, 0.80)}")
    print(f"  Presence recall  (biased caught)          {recall:6.3f}   "
          f"[bar 0.85]  {_verdict(recall, 0.85)}")
    print(f"  Presence precision (rational not flagged) {precision:6.3f}   "
          f"[bar 0.80]  {_verdict(precision, 0.80)}")
    print(f"  Severity exact-match                      {exact:6.3f}   "
          f"[bar 0.70]  {_verdict(exact, 0.70)}")
    print(f"  Severity within-one-level                 {within:6.3f}   "
          f"[bar 0.90]  {_verdict(within, 0.90)}")
    print(f"  Catastrophic errors (severe↔none)         {catastrophic:6d}   "
          f"[bar 0]     {_verdict(catastrophic, 0, op='<=')}")
    print("-" * 64)
    print("  Mean |DEI| by injected severity:")
    import statistics
    for sev in SEVERITIES:
        vals = [abs(r.detected_dei) for r in disp_records if r.injected_severity == sev]
        ns = [r.n_realized for r in disp_records if r.injected_severity == sev]
        if vals:
            print(f"    {sev:9s}  mean|DEI|={statistics.mean(vals):.3f}  "
                  f"mean realized trades={statistics.mean(ns):.1f}")
    print("-" * 64)
    print("  Confusion matrix (rows=injected, cols=detected):")
    print(cm.to_string().replace("\n", "\n    ").rjust(0))
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
