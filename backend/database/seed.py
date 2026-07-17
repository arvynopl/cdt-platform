"""
database/seed.py — Populate StockCatalog and MarketSnapshot from data files.

Functions:
    seed_stock_catalog(session)     — Insert 6 IDX stocks from stock_catalog.json
    seed_market_snapshots(session)  — Insert 2826 rows from all_market_snapshots.csv
    run_seed()                      — Convenience wrapper (creates session + calls both)
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from config import MARKET_SNAPSHOTS_FILE, STOCK_CATALOG_FILE
from database.connection import get_session, init_db
from database.models import MarketSnapshot, StockCatalog

logger = logging.getLogger(__name__)


def seed_stock_catalog(session: Session) -> int:
    """Seed StockCatalog from stock_catalog.json.

    Skips any stock_id that already exists (idempotent).

    Returns:
        Number of rows inserted.
    """
    if not STOCK_CATALOG_FILE.exists():
        raise FileNotFoundError(
            f"Stock catalog file not found: {STOCK_CATALOG_FILE}"
        )

    with open(STOCK_CATALOG_FILE, encoding="utf-8") as fh:
        catalog = json.load(fh)

    inserted = 0
    for item in catalog:
        existing = (
            session.query(StockCatalog)
            .filter_by(stock_id=item["stock_id"])
            .first()
        )
        if existing:
            continue

        stock = StockCatalog(
            stock_id=item["stock_id"],
            ticker=item["ticker"],
            name=item["name"],
            sector=item["sector"],
            volatility_class=item["volatility_class"],
            bias_role=item.get("bias_role"),
        )
        session.add(stock)
        inserted += 1

    session.flush()
    return inserted


def _safe_float(value) -> float | None:
    """Convert a value to float, returning None for NaN / empty strings."""
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def seed_market_snapshots(session: Session) -> int:
    """Seed MarketSnapshot from all_market_snapshots.csv.

    Skips rows where (stock_id, date) already exist (idempotent).

    Returns:
        Number of rows inserted.
    """
    if not MARKET_SNAPSHOTS_FILE.exists():
        raise FileNotFoundError(
            f"Market snapshots file not found: {MARKET_SNAPSHOTS_FILE}"
        )

    df = pd.read_csv(MARKET_SNAPSHOTS_FILE)

    # Collect existing (stock_id, date) pairs to skip duplicates
    existing_pairs = set(
        session.query(MarketSnapshot.stock_id, MarketSnapshot.date).all()
    )

    inserted = 0
    skipped_bad = 0
    for idx, row in df.iterrows():
        # --- Date parsing ---
        try:
            row_date = date.fromisoformat(str(row["date"]))
        except (ValueError, TypeError):
            logger.warning("Skipping row %d: invalid date %r", idx, row.get("date"))
            skipped_bad += 1
            continue

        key = (row["stock_id"], row_date)
        if key in existing_pairs:
            continue

        # --- Numeric parsing ---
        try:
            open_val = float(row["open"])
            high_val = float(row["high"])
            low_val = float(row["low"])
            close_val = float(row["close"])
            volume_val = int(float(row["volume"]))
        except (ValueError, TypeError) as exc:
            logger.warning("Skipping row %d: invalid OHLCV data — %s", idx, exc)
            skipped_bad += 1
            continue

        snapshot = MarketSnapshot(
            stock_id=row["stock_id"],
            date=row_date,
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=volume_val,
            ma_5=_safe_float(row.get("ma_5")),
            ma_20=_safe_float(row.get("ma_20")),
            rsi_14=_safe_float(row.get("rsi_14")),
            volatility_20d=_safe_float(row.get("volatility_20d")),
            trend=str(row["trend"]) if pd.notna(row.get("trend")) else None,
            daily_return=_safe_float(row.get("daily_return")),
        )
        session.add(snapshot)
        existing_pairs.add(key)
        inserted += 1

        # Flush in batches to avoid large memory spikes
        if inserted % 500 == 0:
            session.flush()

    if skipped_bad:
        logger.warning("Skipped %d malformed rows during snapshot seed.", skipped_bad)

    session.flush()
    return inserted


def run_seed() -> None:
    """Initialize DB schema and seed reference data from CSV/JSON files."""
    init_db()
    with get_session() as sess:
        catalog_count = seed_stock_catalog(sess)
        snapshot_count = seed_market_snapshots(sess)
        logger.info(
            "Seed complete — %d stocks, %d snapshots inserted.",
            catalog_count, snapshot_count,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()
