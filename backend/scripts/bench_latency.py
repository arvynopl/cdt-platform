#!/usr/bin/env python3
"""
scripts/bench_latency.py — Latency benchmark for FR01 and NFR01.

Measures two production-relevant latencies against a real database backend:

  * FR01  — Action-logging latency (target <= 500 ms per logged event).
            Time to persist a single UserAction row (log_action + commit).
  * NFR01 — Post-session analytic pipeline latency (target <= 5 s per request).
            Time to run the exact 4-step pipeline executed by the app after a
            session ends: compute_and_save_metrics -> extract_session_features
            -> update_profile -> generate_feedback (mirrors
            modules/simulation/ui.py::_run_post_session_pipeline, steps 1-4).

Backends
--------
  --target local   Local SQLite file (pure compute + local disk I/O; lower bound
                   for NFR01, excludes network). Default.
  --target neon    Remote PostgreSQL via CDT_DATABASE_URL or --db (end-to-end,
                   includes network round-trip — the honest FR01 figure).

The FIRST iteration is reported separately as a COLD measurement (connection
establishment / serverless resume / cache warmup); iterations 2..N are the WARM
steady state used for the headline statistics.

Usage
-----
  python scripts/bench_latency.py --target local  --iterations 30
  CDT_DATABASE_URL="postgresql://...neon.tech/db?sslmode=require" \
      python scripts/bench_latency.py --target neon --iterations 30
  python scripts/bench_latency.py --target neon --db "postgresql://..." --latex reports/latency.tex

Output: console summary table + a ready-to-paste LaTeX table (--latex path).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta

# --- make the repo root importable when run from anywhere ---------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base,
    MarketSnapshot,
    SessionSummary,
    StockCatalog,
    User,
)
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.logger import log_action

# --- representative workload --------------------------------------------------
# Bench-only namespace ("BENCH*.JK" / "BNC*") so seeding NEVER collides with a
# real/seeded database (e.g. a Neon branch that already holds the 12 IDX stocks).
# All bench rows carry bias_role='bench' and alias 'bench_*' for easy cleanup.
STOCKS = [
    ("BENCH1.JK", "BNC1", "Finance", "low"),
    ("BENCH2.JK", "BNC2", "Telecom", "low_medium"),
    ("BENCH3.JK", "BNC3", "Mining", "high"),
    ("BENCH4.JK", "BNC4", "Technology", "high"),
    ("BENCH5.JK", "BNC5", "Consumer", "medium"),
    ("BENCH6.JK", "BNC6", "Finance", "medium"),
]
BASE_PRICES = {
    "BENCH1.JK": 9000.0, "BENCH2.JK": 3000.0, "BENCH3.JK": 2000.0,
    "BENCH4.JK": 70.0, "BENCH5.JK": 2000.0, "BENCH6.JK": 4000.0,
}
BASE_DATE = date(2024, 4, 2)
ROUNDS = 14
N_SNAPSHOT_DAYS = 20
# Buy early, sell at mixed horizons -> exercises DEI/LAI/OCS code paths fully.
BUY_ROUND = {"BENCH1.JK": 1, "BENCH3.JK": 1, "BENCH4.JK": 3}
SELL_ROUND = {"BENCH1.JK": 10, "BENCH3.JK": 14, "BENCH4.JK": 12}


def _price(stock_id: str, day: int) -> float:
    """Deterministic price with up/down variation so realized P&L is non-trivial."""
    base = BASE_PRICES[stock_id]
    return round(base * (1.0 + 0.03 * math.sin(day / 2.0) + 0.0015 * day), 4)


def build_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # PostgreSQL / Neon: pool_pre_ping mirrors production connection handling.
    return create_engine(url, pool_pre_ping=True)


def seed(session) -> None:
    """Idempotently seed 6 bench stocks x 20 daily snapshots with price variation.

    Safe to run against a database that already contains other (e.g. production)
    stocks: only the missing BENCH* rows are inserted, so re-runs are no-ops.
    """
    bench_ids = [s[0] for s in STOCKS]
    existing = {
        sid for (sid,) in session.query(StockCatalog.stock_id)
        .filter(StockCatalog.stock_id.in_(bench_ids)).all()
    }
    for stock_id, ticker, sector, vol in STOCKS:
        if stock_id in existing:
            continue
        session.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=f"{ticker} Corp",
            sector=sector, volatility_class=vol, bias_role="bench",
        ))
    session.commit()

    for stock_id, _, _, _ in STOCKS:
        have = (session.query(MarketSnapshot)
                .filter(MarketSnapshot.stock_id == stock_id).count())
        if have >= N_SNAPSHOT_DAYS:
            continue
        for day in range(N_SNAPSHOT_DAYS):
            p = _price(stock_id, day)
            session.add(MarketSnapshot(
                stock_id=stock_id, date=BASE_DATE + timedelta(days=day),
                open=p, high=p * 1.01, low=p * 0.99, close=p, volume=1_000_000,
                ma_5=p, ma_20=p, rsi_14=50.0, volatility_20d=0.02,
                trend="neutral", daily_return=0.0,
            ))
    session.commit()


def _snapshot_id(session, stock_id: str, rnd: int) -> int | None:
    target = BASE_DATE + timedelta(days=rnd - 1)
    snap = session.query(MarketSnapshot).filter_by(stock_id=stock_id, date=target).first()
    return snap.id if snap else None


def log_session_timed(session, user_id: int, session_id: str) -> list[float]:
    """Log 14 rounds x 6 stocks; commit per action. Returns per-action latency (ms)."""
    latencies_ms: list[float] = []
    bought: dict[str, int] = {}
    for rnd in range(1, ROUNDS + 1):
        for stock_id, _, _, _ in STOCKS:
            snap_id = _snapshot_id(session, stock_id, rnd)
            if snap_id is None:
                continue
            price = _price(stock_id, rnd - 1)
            if BUY_ROUND.get(stock_id) == rnd:
                qty, atype = 10, "buy"
                bought[stock_id] = qty
                aval = qty * price
            elif SELL_ROUND.get(stock_id) == rnd and stock_id in bought:
                qty, atype = bought[stock_id], "sell"
                aval = qty * price
            else:
                qty, atype, aval = 0, "hold", 0.0
            t0 = time.perf_counter()
            log_action(
                session=session, user_id=user_id, session_id=session_id,
                scenario_round=rnd, stock_id=stock_id, snapshot_id=snap_id,
                action_type=atype, quantity=qty, action_value=aval,
                response_time_ms=500,
            )
            session.commit()  # FR01: persistence per event (worst case)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    return latencies_ms


def pipeline_timed(session, user_id: int, session_id: str) -> float:
    """Run the 4-step post-session pipeline + commit. Returns latency (ms)."""
    t0 = time.perf_counter()
    bias_metric = compute_and_save_metrics(session, user_id, session_id)
    features = extract_session_features(session, user_id, session_id)
    profile = update_profile(session, user_id, bias_metric, session_id)
    generate_feedback(
        db_session=session, user_id=user_id, session_id=session_id,
        bias_metric=bias_metric, profile=profile,
        realized_trades=features.realized_trades,
        open_positions=features.open_positions,
    )
    session.commit()
    return (time.perf_counter() - t0) * 1000.0


# --- statistics ---------------------------------------------------------------
def pctl(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * (q / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def summarize(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "p50": pctl(xs, 50), "p95": pctl(xs, 95),
        "max": max(xs) if xs else float("nan"),
        "mean": sum(xs) / len(xs) if xs else float("nan"),
    }


def _id(x: float, dec: int = 1) -> str:
    """Indonesian decimal format (comma separator)."""
    return f"{x:.{dec}f}".replace(".", ",")


# --- LaTeX --------------------------------------------------------------------
def latex_table(target: str, fr01: dict, nfr01: dict,
                fr01_cold: float, nfr01_cold: float) -> str:
    fr01_status = "Terpenuhi" if fr01["p95"] <= 500 else "Tidak Terpenuhi"
    nfr01_status = "Terpenuhi" if nfr01["p95"] <= 5000 else "Tidak Terpenuhi"
    env = ("PostgreSQL/Neon (end-to-end, termasuk jaringan)"
           if target == "neon" else "SQLite lokal (komputasi, tanpa jaringan)")
    return rf"""% Auto-generated by scripts/bench_latency.py (target={target})
\begin{{table}}[ht]
  \centering
  \caption{{Hasil pengukuran latensi pada lingkungan {env}}}
  \label{{tbl:latensi-nfr}}
  \begin{{tabular}}{{|l|c|c|c|c|c|c|}}
    \hline
    Metrik & Ambang & $n$ & p50 (ms) & p95 (ms) & Maks (ms) & Status \\ \hline
    Pencatatan aksi (FR01) & $\leq$ 500 ms & {fr01['n']} & {_id(fr01['p50'])} & {_id(fr01['p95'])} & {_id(fr01['max'])} & {fr01_status} \\ \hline
    Pipa analitik pasca-sesi (NFR01) & $\leq$ 5000 ms & {nfr01['n']} & {_id(nfr01['p50'])} & {_id(nfr01['p95'])} & {_id(nfr01['max'])} & {nfr01_status} \\ \hline
  \end{{tabular}}

  \vspace{{0.2cm}}
  \footnotesize Latensi keadaan tunak (\textit{{warm}}); pengukuran \textit{{cold-start}} pertama
  dilaporkan terpisah: FR01 {_id(fr01_cold)} ms, NFR01 {_id(nfr01_cold)} ms.
\end{{table}}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="FR01/NFR01 latency benchmark.")
    ap.add_argument("--target", choices=["local", "neon"], default="local")
    ap.add_argument("--iterations", type=int, default=30,
                    help="Total sessions (iteration 1 = cold, rest = warm).")
    ap.add_argument("--db", default=None,
                    help="Override DB URL (defaults: local->sqlite tmp, neon->CDT_DATABASE_URL).")
    ap.add_argument("--latex", default=None, help="Path to write the LaTeX table.")
    ap.add_argument("--force", action="store_true",
                    help="Skip the write-confirmation prompt for non-SQLite targets (CI use).")
    args = ap.parse_args()

    if args.db:
        url = args.db
    elif args.target == "neon":
        url = os.environ.get("CDT_DATABASE_URL", "")
        if not url or url.startswith("sqlite"):
            print("ERROR: --target neon needs CDT_DATABASE_URL set to a PostgreSQL URL "
                  "(or pass --db).", file=sys.stderr)
            return 2
    else:
        url = f"sqlite:////tmp/bench_latency_{uuid.uuid4().hex[:8]}.db"

    safe = url.split("@")[-1] if "@" in url else url
    print(f"[bench] target={args.target}  iterations={args.iterations}  db={safe}")

    # Safety: the benchmark WRITES seed rows (stocks, users, sessions) to the
    # target DB. Never run it against production. Bench rows are identifiable
    # (User.alias='bench_*', StockCatalog.bias_role='bench') for later cleanup.
    if not url.startswith("sqlite") and not args.force:
        print("\n  WARNING: this will CREATE TABLES and INSERT rows into the database above.\n"
              "  Point CDT_DATABASE_URL at a THROWAWAY Neon branch, not production.\n"
              "  Bench data uses alias 'bench_*' / bias_role 'bench' so it can be deleted later.")
        if input("  Type 'yes' to proceed: ").strip().lower() != "yes":
            print("  Aborted.")
            return 1

    engine = build_engine(url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    seed(sess)

    fr01_all: list[float] = []
    nfr01_all: list[float] = []
    fr01_cold = nfr01_cold = float("nan")

    for i in range(args.iterations):
        u = User(alias=f"bench_{uuid.uuid4().hex[:8]}", experience_level="beginner")
        sess.add(u)
        sess.flush()
        session_id = str(uuid.uuid4())
        sess.add(SessionSummary(
            user_id=u.id, session_id=session_id,
            started_at=datetime.now(UTC), status="in_progress",
        ))
        sess.commit()

        log_ms = log_session_timed(sess, u.id, session_id)
        pipe_ms = pipeline_timed(sess, u.id, session_id)

        if i == 0:  # cold
            fr01_cold = pctl(log_ms, 50)
            nfr01_cold = pipe_ms
        else:       # warm
            fr01_all.extend(log_ms)
            nfr01_all.append(pipe_ms)
        print(f"  iter {i + 1:>2}/{args.iterations}  "
              f"log_p50={pctl(log_ms, 50):7.2f}ms  pipeline={pipe_ms:8.2f}ms"
              f"{'   (cold)' if i == 0 else ''}")

    sess.close()

    fr01 = summarize(fr01_all)
    nfr01 = summarize(nfr01_all)

    print("\n=== WARM steady-state (iterations 2..N) ===")
    print(f"FR01  action-logging  n={fr01['n']:>4}  "
          f"p50={fr01['p50']:.2f}  p95={fr01['p95']:.2f}  max={fr01['max']:.2f} ms  "
          f"(target <=500)  -> {'PASS' if fr01['p95'] <= 500 else 'FAIL'}")
    print(f"NFR01 pipeline        n={nfr01['n']:>4}  "
          f"p50={nfr01['p50']:.2f}  p95={nfr01['p95']:.2f}  max={nfr01['max']:.2f} ms  "
          f"(target <=5000) -> {'PASS' if nfr01['p95'] <= 5000 else 'FAIL'}")
    print(f"COLD first call: FR01={fr01_cold:.2f}ms  NFR01={nfr01_cold:.2f}ms")

    tex = latex_table(args.target, fr01, nfr01, fr01_cold, nfr01_cold)
    print("\n=== LaTeX table ===\n" + tex)
    if args.latex:
        os.makedirs(os.path.dirname(os.path.abspath(args.latex)), exist_ok=True)
        with open(args.latex, "w") as fh:
            fh.write(tex + "\n")
        print(f"\n[bench] LaTeX table written to {args.latex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
