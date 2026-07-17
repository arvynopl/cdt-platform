"""
tests/conftest.py — Shared pytest fixtures for the CDT Bias Detection test suite.

These fixtures are available to all test files. File-local fixtures of the same
name take precedence (pytest nearest-scope rule), so existing test files are
unaffected.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, MarketSnapshot, StockCatalog, User

STOCKS = [
    ("BBCA.JK", "BBCA", "Bank Central Asia", "Finance", "low"),
    ("TLKM.JK", "TLKM", "Telkom Indonesia", "Telecom", "low_medium"),
    ("ANTM.JK", "ANTM", "Aneka Tambang", "Mining", "high"),
    ("GOTO.JK", "GOTO", "GoTo Gojek Tokopedia", "Technology", "high"),
    ("UNVR.JK", "UNVR", "Unilever Indonesia", "Consumer", "medium"),
    ("BBRI.JK", "BBRI", "Bank Rakyat Indonesia", "Finance", "medium"),
    ("ASII.JK", "ASII", "Astra International", "Conglomerate", "medium"),
    ("BMRI.JK", "BMRI", "Bank Mandiri", "Finance", "low_medium"),
    ("ICBP.JK", "ICBP", "Indofood CBP", "Consumer", "low"),
    ("MDKA.JK", "MDKA", "Merdeka Copper Gold", "Mining", "high"),
    ("BRIS.JK", "BRIS", "Bank Syariah Indonesia", "Finance", "medium"),
    ("EMTK.JK", "EMTK", "Elang Mahkota Teknologi", "Media & Tech", "high"),
]

BASE_PRICES = {
    "BBCA.JK": 9000.0,
    "TLKM.JK": 3000.0,
    "ANTM.JK": 2000.0,
    "GOTO.JK": 70.0,
    "UNVR.JK": 2000.0,
    "BBRI.JK": 4000.0,
    "ASII.JK": 5000.0,
    "BMRI.JK": 5500.0,
    "ICBP.JK": 10000.0,
    "MDKA.JK": 3000.0,
    "BRIS.JK": 2000.0,
    "EMTK.JK": 1500.0,
}

BASE_DATE = date(2024, 4, 2)


@pytest.fixture()
def db():
    """Fresh in-memory SQLite database with 12 stocks and 50 days of snapshots.

    50 days ensures the SimulationEngine can always find a 14-day trading window
    with at least 30 days of pre-window history available.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    # Seed 12 stocks
    for stock_id, ticker, name, sector, vol in STOCKS:
        sess.add(StockCatalog(
            stock_id=stock_id, ticker=ticker, name=name,
            sector=sector, volatility_class=vol, bias_role="test",
        ))
    sess.flush()

    # Seed 50 days of market snapshots per stock
    for stock_id, _, _, _, _ in STOCKS:
        price = BASE_PRICES[stock_id]
        for day in range(50):
            sess.add(MarketSnapshot(
                stock_id=stock_id,
                date=BASE_DATE + timedelta(days=day),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000_000,
                ma_5=price, ma_20=price, rsi_14=50.0,
                volatility_20d=0.02, trend="neutral", daily_return=0.0,
            ))
    sess.flush()

    yield sess
    sess.close()


@pytest.fixture()
def user(db):
    """A persisted beginner User bound to the shared db fixture."""
    u = User(alias="conftest_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u
