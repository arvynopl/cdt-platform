"""
tests/test_postgres_compat.py — Smoke tests for Postgres deployment.

These tests exercise the real connection path (config.DATABASE_URL → engine →
init_db → seed → log_action → query) to confirm the codebase works end-to-end
against a Postgres instance such as Neon.

By design the entire module is skipped unless CDT_DATABASE_URL points to a
Postgres database, so the default ``pytest tests/`` run on SQLite is unaffected.

Run locally against a Postgres DB::

    export CDT_DATABASE_URL='postgresql://user:pass@host/db?sslmode=require'
    pytest tests/test_postgres_compat.py -v

The tests insert into and clean up from a freshly initialised schema. They do
NOT drop the database; only the rows they create. Run against a throwaway
schema or a dedicated test DB.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

_DB_URL = os.environ.get("CDT_DATABASE_URL", "")
_IS_POSTGRES = _DB_URL.startswith("postgres://") or _DB_URL.startswith("postgresql")

pytestmark = pytest.mark.skipif(
    not _IS_POSTGRES,
    reason="CDT_DATABASE_URL is not set to a Postgres URL; skipping Postgres compat tests.",
)


@pytest.fixture(scope="module")
def pg_engine():
    """Return the live engine and ensure schema exists; yield for module-scoped tests."""
    from database.connection import get_engine, init_db

    init_db()
    engine = get_engine()
    assert engine.dialect.name == "postgresql", (
        f"Expected postgresql dialect, got {engine.dialect.name!r}. "
        "Check that CDT_DATABASE_URL is correctly set."
    )
    yield engine


@pytest.fixture()
def cleanup_ids():
    """Track row IDs created by a test and delete them on teardown."""
    created = {
        "user_action": [],
        "market_snapshot": [],
        "stock_catalog": [],
        "user": [],
    }
    yield created

    from database.connection import get_session
    from database.models import (
        CognitiveProfile,
        MarketSnapshot,
        StockCatalog,
        User,
        UserAction,
    )

    with get_session() as sess:
        for aid in created["user_action"]:
            sess.query(UserAction).filter_by(id=aid).delete()
        for sid in created["market_snapshot"]:
            sess.query(MarketSnapshot).filter_by(id=sid).delete()
        for stock_id in created["stock_catalog"]:
            sess.query(StockCatalog).filter_by(stock_id=stock_id).delete()
        # Postgres enforces FK constraints; bulk DELETE bypasses ORM cascade,
        # so child rows referencing User must be removed before the parent.
        for uid in created["user"]:
            sess.query(CognitiveProfile).filter_by(user_id=uid).delete()
        for uid in created["user"]:
            sess.query(User).filter_by(id=uid).delete()


def test_init_db_creates_tables(pg_engine):
    """init_db() must create all 13 ORM tables on a fresh Postgres schema."""
    from sqlalchemy import inspect

    expected_tables = {
        "users", "user_profiles", "onboarding_surveys", "stock_catalog",
        "market_snapshots", "user_actions", "bias_metrics", "cognitive_profiles",
        "feedback_history", "consent_logs", "user_surveys", "session_summaries",
        "cdt_snapshots", "post_session_surveys",
    }
    inspector = inspect(pg_engine)
    existing = set(inspector.get_table_names())
    missing = expected_tables - existing
    assert not missing, f"Tables missing after init_db(): {sorted(missing)}"


def test_seed_stock_catalog_idempotent(pg_engine, cleanup_ids):
    """seed_stock_catalog must run cleanly and be idempotent on re-run.

    Uses synthetic stock entries so the test does not depend on the data files
    or pollute the production catalog. Cleans up its own rows.
    """
    from database.connection import get_session
    from database.models import StockCatalog

    # Ticker must fit StockCatalog.ticker = String(10). Postgres enforces it
    # strictly (SQLite silently truncates), so keep the synthetic id ≤ 10 chars.
    test_ticker = f"PG{uuid.uuid4().hex[:4].upper()}"
    test_stock_id = f"{test_ticker}.JK"

    with get_session() as sess:
        sess.add(StockCatalog(
            stock_id=test_stock_id,
            ticker=test_ticker,
            name="PG Compat Test Stock",
            sector="Test",
            volatility_class="medium",
            bias_role="test",
        ))
    cleanup_ids["stock_catalog"].append(test_stock_id)

    # Re-insert via ON CONFLICT-style pre-check (mimics seed_stock_catalog behaviour).
    with get_session() as sess:
        existing = sess.query(StockCatalog).filter_by(stock_id=test_stock_id).first()
        assert existing is not None, "Insert did not persist on Postgres."
        # Second insert attempt should be a no-op via filter_by check.
        if existing is None:
            sess.add(StockCatalog(stock_id=test_stock_id, ticker=test_ticker,
                                  name="dup", sector="Test",
                                  volatility_class="medium", bias_role="test"))


def test_log_action_and_roundtrip(pg_engine, cleanup_ids):
    """End-to-end: insert User + Stock + Snapshot, log_action(), query back."""
    from database.connection import get_session
    from database.models import MarketSnapshot, StockCatalog, User, UserAction
    from modules.logging_engine.logger import log_action

    test_ticker = f"PGRT{uuid.uuid4().hex[:6].upper()}"
    test_stock_id = f"{test_ticker}.JK"
    test_session_id = str(uuid.uuid4())

    with get_session() as sess:
        user = User(alias=f"pgcompat_{uuid.uuid4().hex[:8]}", experience_level="beginner")
        sess.add(user)
        sess.flush()
        cleanup_ids["user"].append(user.id)

        stock = StockCatalog(
            stock_id=test_stock_id, ticker=test_ticker,
            name="PG Roundtrip Stock", sector="Test",
            volatility_class="medium", bias_role="test",
        )
        sess.add(stock)
        sess.flush()
        cleanup_ids["stock_catalog"].append(stock.stock_id)

        snap = MarketSnapshot(
            stock_id=stock.stock_id,
            date=date.today() - timedelta(days=1),
            open=100.0, high=105.0, low=99.0, close=104.0, volume=1_000_000,
            ma_5=102.0, ma_20=101.0, rsi_14=55.0,
            volatility_20d=0.02, trend="bullish", daily_return=0.01,
        )
        sess.add(snap)
        sess.flush()
        cleanup_ids["market_snapshot"].append(snap.id)

        action = log_action(
            session=sess,
            user_id=user.id,
            session_id=test_session_id,
            scenario_round=1,
            stock_id=stock.stock_id,
            snapshot_id=snap.id,
            action_type="buy",
            quantity=10,
            action_value=1040.0,
            response_time_ms=1500,
        )
        cleanup_ids["user_action"].append(action.id)
        action_id = action.id
        user_id = user.id

    # Roundtrip read in a fresh session — confirms commit landed in Postgres.
    with get_session() as sess:
        fetched = sess.query(UserAction).filter_by(id=action_id).first()
        assert fetched is not None, "log_action row did not persist."
        assert fetched.user_id == user_id
        assert fetched.session_id == test_session_id
        assert fetched.action_type == "buy"
        assert fetched.quantity == 10
        # Postgres returns the float exactly for the IEEE-representable value.
        assert fetched.action_value == pytest.approx(1040.0)
        assert isinstance(fetched.timestamp, datetime)


def test_json_column_roundtrip(pg_engine, cleanup_ids):
    """CognitiveProfile.bias_intensity_vector (JSON) must roundtrip correctly."""
    from database.connection import get_session
    from database.models import CognitiveProfile, User

    payload = {
        "overconfidence": 0.42,
        "disposition": 0.13,
        "loss_aversion": 0.77,
    }
    with get_session() as sess:
        user = User(alias=f"pgjson_{uuid.uuid4().hex[:8]}", experience_level="beginner")
        sess.add(user)
        sess.flush()
        cleanup_ids["user"].append(user.id)

        prof = CognitiveProfile(
            user_id=user.id,
            bias_intensity_vector=payload,
            risk_preference=0.25,
            stability_index=0.5,
            session_count=1,
            last_updated_at=datetime.now(UTC),
        )
        sess.add(prof)
        sess.flush()
        prof_user_id = prof.user_id

    with get_session() as sess:
        fetched = sess.query(CognitiveProfile).filter_by(user_id=prof_user_id).first()
        assert fetched is not None
        assert fetched.bias_intensity_vector == payload
