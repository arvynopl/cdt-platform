"""
synthetic_validation/run_phase2.py — Phase 2 verification run (all 3 biases).

Extends Phase 1 to the overconfidence and loss-aversion overlays. Builds an
ISOLATED SQLite database, seeds it from the real data files, generates one
graded-severity cohort per bias plus shared rational controls, runs the
unmodified detector, and reports per-bias recovery against the pre-registered
pass-bars with confusion matrices.

Usage:
    python -m synthetic_validation.run_phase2
"""

from __future__ import annotations

import os
import tempfile

if "CDT_DATABASE_URL" not in os.environ:
    _tmp = os.path.join(tempfile.gettempdir(), "synth_validation_phase2.db")
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
N_PER_SEVERITY = 30
N_PER_STRATEGY = 10
SEVERITIES = ["none", "mild", "moderate", "severe"]

# Pre-registered bars (identical to Phase 1).
BARS = {
    "rho": 0.80, "recall": 0.85, "precision": 0.80,
    "exact": 0.70, "within": 0.90,
}


def _full_coverage_dates(session):
    n_stocks = session.query(MarketSnapshot.stock_id).distinct().count()
    counts = Counter(d for (d,) in session.query(MarketSnapshot.date).all())
    return sorted(d for d, c in counts.items() if c == n_stocks)


def _emit_agent(session, full_dates, seed, agent_id, decision_fn):
    rng = random.Random(seed)
    start = rng.randint(0, len(full_dates) - ROUNDS_PER_SESSION)
    window = full_dates[start:start + ROUNDS_PER_SESSION]
    bars = runner.build_bars(session, window)
    decisions = decision_fn(bars, rng)
    user = runner.create_shell_user(session, agent_id)
    sid = runner.new_session_id()
    runner.emit_session(
        session, user_id=user.id, session_id=sid,
        decisions=decisions, window_dates=window, rng=rng,
    )
    return user.id, sid, window


def _verdict(value, bar, op=">="):
    ok = (value >= bar) if op == ">=" else (value <= bar)
    return "PASS" if ok else "MISS"


def _report_bias(title, bias, graded_records, eval_records):
    rho = evaluate.spearman_recovery(graded_records, bias)
    precision, recall = evaluate.presence_precision_recall(eval_records, bias)
    exact, within, catastrophic = evaluate.severity_accuracy(graded_records, bias)
    cm = evaluate.confusion_matrix(graded_records, bias)
    field = evaluate.BIAS_FIELDS[bias][0]

    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)
    print(f"  Spearman ρ (severity vs |{field.upper()}|)   {rho:6.3f}   "
          f"[bar {BARS['rho']:.2f}]  {_verdict(rho, BARS['rho'])}")
    print(f"  Presence recall                       {recall:6.3f}   "
          f"[bar {BARS['recall']:.2f}]  {_verdict(recall, BARS['recall'])}")
    print(f"  Presence precision                    {precision:6.3f}   "
          f"[bar {BARS['precision']:.2f}]  {_verdict(precision, BARS['precision'])}")
    print(f"  Severity exact-match (diagnostic)     {exact:6.3f}   "
          f"[bar {BARS['exact']:.2f}]  {_verdict(exact, BARS['exact'])}")
    print(f"  Severity within-one-level             {within:6.3f}   "
          f"[bar {BARS['within']:.2f}]  {_verdict(within, BARS['within'])}")
    print(f"  Catastrophic errors                   {catastrophic:6d}   "
          f"[bar 0]     {_verdict(catastrophic, 0, op='<=')}")
    print("  Mean |metric| by injected severity:")
    for sev in SEVERITIES:
        vals = [evaluate._val(r, bias) for r in graded_records if r.injected_severity == sev]
        if vals:
            print(f"    {sev:9s}  mean={statistics.mean(vals):.3f}")
    print("  Confusion matrix (rows=injected, cols=detected):")
    print("    " + cm.to_string().replace("\n", "\n    "))


def main() -> None:
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

        # --- One graded cohort per bias -------------------------------------
        for sev in SEVERITIES:
            for _ in range(N_PER_SEVERITY):
                # Disposition
                gt_take, loss_tol = agents.DISPOSITION_PROFILES[sev]
                uid, sid, win = _emit_agent(
                    session, full_dates, MASTER_SEED + idx, f"disp_{sev}_{idx:04d}",
                    lambda b, rng: agents.disposition_agent(
                        b, gain_take=gt_take, loss_tolerance=loss_tol,
                        initial_capital=INITIAL_CAPITAL, rng=rng),
                )
                cohorts["disposition"].append((SyntheticGroundTruth(
                    agent_id=f"disp_{sev}_{idx:04d}", session_id=sid,
                    base_strategy="disposition_basket",
                    injected_bias="none" if sev == "none" else "disposition",
                    injected_severity=sev,
                    rule_parameters={"gain_take": gt_take, "loss_tolerance": loss_tol},
                    market_window=(win[0].isoformat(), win[-1].isoformat()),
                    rng_seed=MASTER_SEED + idx), uid))
                idx += 1

                # Overconfidence
                n_rt = agents.OVERCONFIDENCE_PROFILES[sev]
                uid, sid, win = _emit_agent(
                    session, full_dates, MASTER_SEED + idx, f"over_{sev}_{idx:04d}",
                    lambda b, rng: agents.overconfidence_agent(
                        b, n_roundtrips=n_rt, initial_capital=INITIAL_CAPITAL, rng=rng),
                )
                cohorts["overconfidence"].append((SyntheticGroundTruth(
                    agent_id=f"over_{sev}_{idx:04d}", session_id=sid,
                    base_strategy="overconfidence_churn",
                    injected_bias="none" if sev == "none" else "overconfidence",
                    injected_severity=sev, rule_parameters={"n_roundtrips": n_rt},
                    market_window=(win[0].isoformat(), win[-1].isoformat()),
                    rng_seed=MASTER_SEED + idx), uid))
                idx += 1

                # Loss aversion
                w_hold, l_hold = agents.LOSS_AVERSION_PROFILES[sev]
                uid, sid, win = _emit_agent(
                    session, full_dates, MASTER_SEED + idx, f"loss_{sev}_{idx:04d}",
                    lambda b, rng: agents.loss_aversion_agent(
                        b, winner_hold=w_hold, loser_hold=l_hold,
                        initial_capital=INITIAL_CAPITAL, rng=rng),
                )
                cohorts["loss_aversion"].append((SyntheticGroundTruth(
                    agent_id=f"loss_{sev}_{idx:04d}", session_id=sid,
                    base_strategy="loss_aversion_basket",
                    injected_bias="none" if sev == "none" else "loss_aversion",
                    injected_severity=sev,
                    rule_parameters={"winner_hold": w_hold, "loser_hold": l_hold},
                    market_window=(win[0].isoformat(), win[-1].isoformat()),
                    rng_seed=MASTER_SEED + idx), uid))
                idx += 1

        # --- Shared rational controls (injected none) -----------------------
        for strat_name, strat_fn in agents.RATIONAL_STRATEGIES.items():
            for _ in range(N_PER_STRATEGY):
                uid, sid, win = _emit_agent(
                    session, full_dates, MASTER_SEED + idx, f"ctrl_{strat_name}_{idx:04d}",
                    lambda b, rng, fn=strat_fn: fn(b, initial_capital=INITIAL_CAPITAL, rng=rng),
                )
                controls.append((SyntheticGroundTruth(
                    agent_id=f"ctrl_{strat_name}_{idx:04d}", session_id=sid,
                    base_strategy=strat_name, injected_bias="none",
                    injected_severity="none", rule_parameters={},
                    market_window=(win[0].isoformat(), win[-1].isoformat()),
                    rng_seed=MASTER_SEED + idx), uid))
                idx += 1

        session.commit()

        control_records = evaluate.build_records(session, controls)
        bias_records = {
            b: evaluate.build_records(session, items) for b, items in cohorts.items()
        }

    titles = {
        "disposition": "DISPOSITION EFFECT (DEI)",
        "overconfidence": "OVERCONFIDENCE (OCS)",
        "loss_aversion": "LOSS AVERSION (LAI)",
    }
    print("\n" + "#" * 64)
    print(f"#  PHASE 2 — THREE-BIAS RECOVERY  (seed {MASTER_SEED}, "
          f"{N_PER_SEVERITY}/severity + {len(controls)} controls)")
    print("#" * 64)
    for bias in ("disposition", "overconfidence", "loss_aversion"):
        graded = bias_records[bias]
        eval_set = graded + control_records   # controls add specificity (precision)
        _report_bias(titles[bias], bias, graded, eval_set)
    print("\n" + "#" * 64 + "\n")


if __name__ == "__main__":
    main()
