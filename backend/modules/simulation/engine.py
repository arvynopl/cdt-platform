"""
modules/simulation/engine.py — Historical replay scenario engine.

Selects a random contiguous 14-trading-day window from the MarketSnapshot
table and exposes one day at a time to the simulation UI.
"""

from __future__ import annotations

import random
from datetime import date

from sqlalchemy.orm import Session

from config import PRE_WINDOW_DAYS, ROUNDS_PER_SESSION
from database.models import MarketSnapshot


class SimulationEngine:
    """Manages a single 14-round simulation session over historical IDX data.

    Args:
        user_id:    ID of the participating user.
        session_id: UUID string identifying this session.
        db_session: Active SQLAlchemy session for reading market data.
        start_date: Optional fixed start date for the window. When provided
                    (e.g. when resuming an in-progress session) the engine
                    reconstructs the same window instead of picking a random
                    one. The date must exist in MarketSnapshot.
    """

    def __init__(
        self,
        user_id: int,
        session_id: str,
        db_session: Session,
        start_date: date | None = None,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self._db = db_session
        self._current_round: int = 1

        # {stock_id: [MarketSnapshot × ROUNDS_PER_SESSION]} sorted by date
        self._window: dict[str, list[MarketSnapshot]] = {}
        self._stock_ids: list[str] = []
        self._start_date = None
        self._end_date = None

        self._select_window(fixed_start_date=start_date)

    # ------------------------------------------------------------------
    # Window selection
    # ------------------------------------------------------------------

    def _select_window(self, fixed_start_date: date | None = None) -> None:
        """Pick a contiguous ROUNDS_PER_SESSION-day trading window.

        When ``fixed_start_date`` is supplied (resume path) the window starts
        at that exact trading date; otherwise a random start index is chosen.

        Strategy:
            1. Fetch all distinct trading dates shared across all stocks.
            2. Pick a start index — fixed if provided, else random in
               [0, len(dates) - ROUNDS_PER_SESSION].
            3. Load the MarketSnapshot rows for those dates for every stock.
        """
        # All distinct dates available in the DB, sorted ascending
        date_rows = (
            self._db.query(MarketSnapshot.date)
            .distinct()
            .order_by(MarketSnapshot.date)
            .all()
        )
        all_dates = [r[0] for r in date_rows]

        if len(all_dates) < ROUNDS_PER_SESSION:
            raise RuntimeError(
                f"Not enough trading days in DB: "
                f"need {ROUNDS_PER_SESSION}, found {len(all_dates)}."
            )

        max_start = len(all_dates) - ROUNDS_PER_SESSION
        if fixed_start_date is not None:
            try:
                start_idx = all_dates.index(fixed_start_date)
            except ValueError as exc:
                raise RuntimeError(
                    f"Cannot resume session: start_date {fixed_start_date} "
                    "not found in MarketSnapshot."
                ) from exc
            if start_idx > max_start:
                raise RuntimeError(
                    f"Cannot resume session: start_date {fixed_start_date} "
                    f"leaves fewer than {ROUNDS_PER_SESSION} trading days "
                    "ahead of it."
                )
        else:
            start_idx = random.randint(0, max_start)
        window_dates = all_dates[start_idx : start_idx + ROUNDS_PER_SESSION]

        self._start_date = window_dates[0]
        self._end_date = window_dates[-1]

        # Fetch all snapshots for these dates
        snapshots = (
            self._db.query(MarketSnapshot)
            .filter(MarketSnapshot.date.in_(window_dates))
            .order_by(MarketSnapshot.stock_id, MarketSnapshot.date)
            .all()
        )

        # Group by stock_id
        window: dict[str, list[MarketSnapshot]] = {}
        for snap in snapshots:
            window.setdefault(snap.stock_id, []).append(snap)

        # Keep only stocks that have data for every window date
        complete_stocks = {
            sid: snaps
            for sid, snaps in window.items()
            if len(snaps) == ROUNDS_PER_SESSION
        }

        if not complete_stocks:
            raise RuntimeError(
                "No stock has complete data for the selected window. "
                "Please check the database seed."
            )

        # Sort each stock's snapshots by date to ensure round order
        for sid in complete_stocks:
            complete_stocks[sid].sort(key=lambda s: s.date)

        self._window = complete_stocks
        self._stock_ids = sorted(complete_stocks.keys())

    # ------------------------------------------------------------------
    # Round navigation
    # ------------------------------------------------------------------

    @property
    def current_round(self) -> int:
        """Current round number (1-indexed; ROUNDS_PER_SESSION + 1 means complete)."""
        return self._current_round

    def advance_round(self) -> None:
        """Move to the next round.

        Raises:
            RuntimeError: if the session is already complete.
        """
        if self.is_complete():
            raise RuntimeError("Session already complete.")
        self._current_round += 1

    def is_complete(self) -> bool:
        """Return True when all rounds have been played."""
        return self._current_round > ROUNDS_PER_SESSION

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def get_current_round_data(self) -> dict[str, MarketSnapshot]:
        """Return snapshots for all stocks at the current round.

        Returns:
            Dict mapping stock_id → MarketSnapshot for today's round.

        Raises:
            RuntimeError: if the session is complete.
        """
        if self.is_complete():
            raise RuntimeError("Session is complete; no more round data.")
        idx = self._current_round - 1  # 0-based index
        return {sid: snaps[idx] for sid, snaps in self._window.items()}

    def get_round_data(self, round_num: int) -> dict[str, MarketSnapshot]:
        """Return snapshots for a specific round number (1-indexed).

        Used by the analytics layer to replay the full session.
        """
        if not (1 <= round_num <= ROUNDS_PER_SESSION):
            raise ValueError(f"round_num must be 1–{ROUNDS_PER_SESSION}, got {round_num}.")
        idx = round_num - 1
        return {sid: snaps[idx] for sid, snaps in self._window.items()}

    def get_all_round_data(self) -> list[dict[str, MarketSnapshot]]:
        """Return a list of per-round dicts (index 0 = round 1).

        Useful for post-session analytics.
        """
        return [
            {sid: snaps[i] for sid, snaps in self._window.items()}
            for i in range(ROUNDS_PER_SESSION)
        ]

    def get_price_history(self, stock_id: str) -> list[float]:
        """Return the sequence of closing prices for *stock_id* across all rounds."""
        if stock_id not in self._window:
            raise KeyError(f"Stock {stock_id!r} not in session window.")
        return [s.close for s in self._window[stock_id]]

    def get_window_metadata(self) -> dict:
        """Return summary metadata about the selected window."""
        return {
            "start_date": self._start_date,
            "end_date": self._end_date,
            "stock_ids": self._stock_ids,
            "rounds": ROUNDS_PER_SESSION,
        }

    def get_pre_window_history(self) -> dict[str, list[dict]]:
        """Fetch PRE_WINDOW_DAYS of market data before the trading window.

        Must be called while the DB session (self._db) is still active.

        Returns:
            Dict mapping stock_id → list of serialized snapshot dicts
            (keys: date, open, high, low, close, volume, ma_5, ma_20),
            ordered chronologically.
        """
        if self._start_date is None:
            return {}

        pre_snaps = (
            self._db.query(MarketSnapshot)
            .filter(
                MarketSnapshot.date < self._start_date,
                MarketSnapshot.stock_id.in_(self._stock_ids),
            )
            .order_by(MarketSnapshot.stock_id, MarketSnapshot.date.desc())
            .all()
        )

        history: dict[str, list[dict]] = {}
        for snap in pre_snaps:
            if snap.stock_id not in history:
                history[snap.stock_id] = []
            if len(history[snap.stock_id]) < PRE_WINDOW_DAYS:
                history[snap.stock_id].append({
                    "date": snap.date,
                    "open": snap.open,
                    "high": snap.high,
                    "low": snap.low,
                    "close": snap.close,
                    "volume": snap.volume,
                    "ma_5": snap.ma_5,
                    "ma_20": snap.ma_20,
                })

        # Reverse each list to chronological order
        for sid in history:
            history[sid].reverse()

        return history

    @property
    def stock_ids(self) -> list[str]:
        """Sorted list of stock_ids in this window."""
        return self._stock_ids
