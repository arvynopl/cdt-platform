"""
synthetic_validation/runner.py — Turn agent Decisions into persisted UserAction
rows against a real price window, and create the shell users that own them.

The runner is the ONLY place this package touches the database. It reads
MarketSnapshot / StockCatalog (the same fixtures the app uses) and writes
UserAction rows in exactly the schema the detector expects. It never imports
the analytics layer.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.models import MarketSnapshot, User, UserAction
from synthetic_validation.agents import Bar

logger = logging.getLogger(__name__)

# Shell synthetic users are denylisted from human cohort stats via this prefix.
SYNTH_USERNAME_PREFIX = "synth_"


def common_window_dates(session: Session, rounds: int, rng: random.Random):
    """Pick a random contiguous block of ``rounds`` dates on which every stock
    in the catalog has a snapshot (so the basket is fully tradable)."""
    n_stocks = session.query(MarketSnapshot.stock_id).distinct().count()
    # date → number of stocks with a snapshot that day
    rows = session.query(MarketSnapshot.date).all()
    from collections import Counter
    counts = Counter(d for (d,) in rows)
    full_dates = sorted(d for d, c in counts.items() if c == n_stocks)
    if len(full_dates) < rounds:
        raise ValueError(
            f"Only {len(full_dates)} fully-covered dates; need {rounds}."
        )
    start = rng.randint(0, len(full_dates) - rounds)
    return full_dates[start:start + rounds]


def build_bars(session: Session, window_dates) -> list[Bar]:
    """Construct Bar objects (round_num 1..N) for all stocks over the window."""
    date_to_round = {d: i + 1 for i, d in enumerate(window_dates)}
    snaps = (
        session.query(MarketSnapshot)
        .filter(MarketSnapshot.date.in_(window_dates))
        .all()
    )
    bars: list[Bar] = []
    for s in snaps:
        bars.append(Bar(
            round_num=date_to_round[s.date],
            stock_id=s.stock_id,
            close=s.close,
            ma_5=s.ma_5,
            ma_20=s.ma_20,
            rsi_14=s.rsi_14,
            trend=s.trend,
        ))
    return bars


def _snapshot_index(session: Session, window_dates) -> dict[tuple, MarketSnapshot]:
    """(stock_id, date) → MarketSnapshot, for resolving snapshot_id + price."""
    snaps = (
        session.query(MarketSnapshot)
        .filter(MarketSnapshot.date.in_(window_dates))
        .all()
    )
    return {(s.stock_id, s.date): s for s in snaps}


def create_shell_user(session: Session, agent_id: str) -> User:
    """Create (and flush) a denylisted shell user to own one synthetic session."""
    user = User(
        username=f"{SYNTH_USERNAME_PREFIX}{agent_id}",
        alias=f"{SYNTH_USERNAME_PREFIX}{agent_id}",
        experience_level="synthetic",
    )
    session.add(user)
    session.flush()
    return user


def emit_session(
    session: Session,
    *,
    user_id: int,
    session_id: str,
    decisions: list,
    window_dates,
    rng: random.Random,
) -> int:
    """Write Decisions as UserAction rows. Returns the number of rows written.

    response_time_ms is sampled from a plausible band; it does not feed any of
    the three core bias metrics but must be non-null.
    """
    date_for_round = {i + 1: d for i, d in enumerate(window_dates)}
    snap_idx = _snapshot_index(session, window_dates)
    written = 0
    for d in decisions:
        the_date = date_for_round[d.round_num]
        snap = snap_idx.get((d.stock_id, the_date))
        if snap is None:
            continue
        price = snap.close
        qty = d.quantity
        action_value = qty * price if d.action_type in ("buy", "sell") else 0.0
        session.add(UserAction(
            user_id=user_id,
            session_id=session_id,
            scenario_round=d.round_num,
            stock_id=d.stock_id,
            snapshot_id=snap.id,
            action_type=d.action_type,
            quantity=qty,
            action_value=action_value,
            response_time_ms=rng.randint(800, 6000),
            timestamp=datetime.now(UTC),
        ))
        written += 1
    session.flush()
    return written


def new_session_id() -> str:
    return str(uuid.uuid4())
