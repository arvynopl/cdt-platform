# Run locally: python scripts/idx_data_acquisition.py
"""
idx_data_acquisition.py — Download 2-year daily OHLCV for all 12 IDX tickers
and compute technical indicators for the CDT Bias Detection System.

Requirements:
    pip install yfinance pandas ta

Outputs:
    data/all_market_snapshots.csv     — combined snapshot file loaded by seed.py
    data/{TICKER}_historical.csv      — per-ticker historical files

Run MANUALLY on a machine with internet access:
    python idx_data_acquisition.py

After running, execute `python -m database.seed` to refresh the database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TICKERS = [
    "BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK",
    "ASII.JK", "BMRI.JK", "ICBP.JK", "MDKA.JK", "BRIS.JK", "EMTK.JK",
]

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_CSV = DATA_DIR / "all_market_snapshots.csv"
LOOKBACK_YEARS = 2


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute MA_5, MA_20, RSI_14, volatility_20d, daily_return, trend."""
    df = df.copy()
    df.sort_index(inplace=True)

    # Moving averages
    df["ma_5"] = df["close"].rolling(5).mean().round(4)
    df["ma_20"] = df["close"].rolling(20).mean().round(4)

    # Daily return
    df["daily_return"] = df["close"].pct_change().round(6)

    # Volatility (annualised 20-day rolling std of daily returns)
    df["volatility_20d"] = (
        df["daily_return"].rolling(20).std() * (252 ** 0.5)
    ).round(6)

    # RSI-14 (Wilder's smoothing)
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi_14"] = (100 - 100 / (1 + rs)).round(2)

    # Trend classification based on close vs MA20
    def _trend(row: pd.Series) -> str:
        if pd.isna(row["ma_20"]):
            return "neutral"
        if row["close"] > row["ma_20"] * 1.005:
            return "bullish"
        if row["close"] < row["ma_20"] * 0.995:
            return "bearish"
        return "neutral"

    df["trend"] = df.apply(_trend, axis=1)

    return df


# ---------------------------------------------------------------------------
# Download and process
# ---------------------------------------------------------------------------

def download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Download OHLCV for one ticker via yfinance and compute indicators."""
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance not installed. Run: pip install yfinance")

    logger.info("Downloading %s (%s → %s)…", ticker, start, end)
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)

    if raw.empty:
        logger.warning("No data returned for %s.", ticker)
        return None

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [col[0].lower() for col in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]

    raw.index.name = "date"
    raw = raw.rename(columns={"open": "open", "high": "high", "low": "low",
                               "close": "close", "volume": "volume"})
    raw = raw[["open", "high", "low", "close", "volume"]].dropna()
    raw = _compute_indicators(raw)

    raw["stock_id"] = ticker
    raw["ticker"] = ticker.replace(".JK", "")
    raw["date"] = raw.index.astype(str)

    return raw.reset_index(drop=True)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=LOOKBACK_YEARS * 365)).strftime("%Y-%m-%d")

    all_frames: list[pd.DataFrame] = []
    # Column order matches the format produced by the original 6-stock acquisition script
    columns = [
        "date", "stock_id", "ticker",
        "open", "high", "low", "close", "volume",
        "ma_5", "ma_20", "rsi_14", "volatility_20d",
        "trend", "daily_return",
    ]

    for ticker in TICKERS:
        df = download_ticker(ticker, start_date, end_date)
        if df is None:
            logger.error("Skipping %s — no data.", ticker)
            continue

        # Save individual file
        individual_path = DATA_DIR / f"{ticker.replace('.JK', '')}_historical.csv"
        df[columns].to_csv(individual_path, index=False)
        logger.info("Saved %s (%d rows) → %s", ticker, len(df), individual_path)

        all_frames.append(df[columns])

    if not all_frames:
        logger.error("No data downloaded. Exiting.")
        return

    combined = pd.concat(all_frames, ignore_index=True)
    combined.to_csv(OUTPUT_CSV, index=False)
    logger.info("Combined snapshot file saved: %s (%d rows)", OUTPUT_CSV, len(combined))
    print(f"\nDone! {len(all_frames)}/{len(TICKERS)} tickers downloaded.")
    print(f"Combined CSV: {OUTPUT_CSV}")
    print("Next step: python -m database.seed")


if __name__ == "__main__":
    main()
