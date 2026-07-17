"""tests/test_uat_feedback.py — UAT instrumentation: UATFeedback model,
SessionError logging, and export_uat_summary CSV-readiness.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from database.models import (
    MarketSnapshot,
    SessionError,
    SessionSummary,
    UATFeedback,
    UserAction,
)
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.utils.export import export_uat_summary, log_session_error

BASE_DATE = date(2024, 4, 2)
STOCK_IDS = ["BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK"]


def _snap(db, stock_id: str, round_num: int) -> MarketSnapshot:
    return db.query(MarketSnapshot).filter_by(
        stock_id=stock_id, date=BASE_DATE + timedelta(days=round_num - 1)
    ).first()


def _log_full_session(db, user_id: int, session_id: str) -> None:
    from config import ROUNDS_PER_SESSION
    for r in range(1, ROUNDS_PER_SESSION + 1):
        for sid in STOCK_IDS:
            snap = _snap(db, sid, r)
            db.add(UserAction(
                user_id=user_id, session_id=session_id,
                scenario_round=r, stock_id=sid, snapshot_id=snap.id,
                action_type="hold", quantity=0, action_value=0.0,
                response_time_ms=300,
            ))
    db.flush()


def _seed_session(db, user_id: int) -> str:
    sid = str(uuid.uuid4())
    _log_full_session(db, user_id, sid)
    compute_and_save_metrics(db, user_id, sid)
    db.add(SessionSummary(
        user_id=user_id,
        session_id=sid,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        rounds_completed=14,
        status="completed",
    ))
    db.flush()
    return sid


# ---------------------------------------------------------------------------
# Model-level tests
# ---------------------------------------------------------------------------

def test_uat_feedback_persists_and_round_trips(db, user):
    fb = UATFeedback(
        user_id=user.id, session_id=None,
        sus_q1=4, sus_q2=2, sus_q3=4, sus_q4=2, sus_q5=4,
        sus_q6=2, sus_q7=4, sus_q8=2, sus_q9=4, sus_q10=2,
        open_confusing="x", open_useful="y",
    )
    db.add(fb)
    db.flush()

    fetched = db.query(UATFeedback).filter_by(user_id=user.id).one()
    assert fetched.id is not None
    assert fetched.open_confusing == "x"
    assert fetched.open_useful == "y"


def test_sus_score_perfect_response(db, user):
    """Strong-agree odd + strong-disagree even = SUS 100."""
    fb = UATFeedback(
        user_id=user.id,
        sus_q1=5, sus_q2=1, sus_q3=5, sus_q4=1, sus_q5=5,
        sus_q6=1, sus_q7=5, sus_q8=1, sus_q9=5, sus_q10=1,
    )
    db.add(fb)
    db.flush()
    assert fb.sus_score == pytest.approx(100.0)


def test_sus_score_neutral_response(db, user):
    """All threes → midpoint score 50."""
    fb = UATFeedback(
        user_id=user.id,
        sus_q1=3, sus_q2=3, sus_q3=3, sus_q4=3, sus_q5=3,
        sus_q6=3, sus_q7=3, sus_q8=3, sus_q9=3, sus_q10=3,
    )
    db.add(fb)
    db.flush()
    assert fb.sus_score == pytest.approx(50.0)


def test_sus_score_worst_response(db, user):
    """Strong-disagree odd + strong-agree even = SUS 0."""
    fb = UATFeedback(
        user_id=user.id,
        sus_q1=1, sus_q2=5, sus_q3=1, sus_q4=5, sus_q5=1,
        sus_q6=5, sus_q7=1, sus_q8=5, sus_q9=1, sus_q10=5,
    )
    db.add(fb)
    db.flush()
    assert fb.sus_score == pytest.approx(0.0)


def test_session_error_persists(db, user):
    err = log_session_error(
        db, user_id=user.id, session_id="abc", error_type="boom", message="kaboom"
    )
    assert err.id is not None
    assert db.query(SessionError).count() == 1


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

def test_export_uat_summary_empty(db):
    """No metrics → empty list (not an error)."""
    rows = export_uat_summary(db)
    assert rows == []


def test_export_uat_summary_includes_sus_and_errors(db, user):
    sid = _seed_session(db, user.id)
    db.add(UATFeedback(
        user_id=user.id, session_id=sid,
        sus_q1=5, sus_q2=1, sus_q3=5, sus_q4=1, sus_q5=5,
        sus_q6=1, sus_q7=5, sus_q8=1, sus_q9=5, sus_q10=1,
        open_confusing="nothing", open_useful="dashboard",
    ))
    log_session_error(db, user_id=user.id, session_id=sid, error_type="x")
    log_session_error(db, user_id=user.id, session_id=sid, error_type="y")
    db.flush()

    rows = export_uat_summary(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user.id
    assert row["session_id"] == sid
    assert row["sus_score"] == pytest.approx(100.0)
    assert row["sus_open_useful"] == "dashboard"
    assert row["session_error_count"] == 2
    assert row["session_status"] == "completed"
    assert row["rounds_completed"] == 14


def test_export_uat_summary_handles_missing_sus(db, user):
    """A session without a UAT feedback row exports cleanly with sus_score=None."""
    _seed_session(db, user.id)
    rows = export_uat_summary(db)
    assert len(rows) == 1
    assert rows[0]["sus_score"] is None
    assert rows[0]["sus_open_useful"] is None


def test_export_uat_summary_uses_latest_sus(db, user):
    """If multiple UATFeedback rows exist, the latest is used."""
    _seed_session(db, user.id)
    older = UATFeedback(
        user_id=user.id,
        sus_q1=1, sus_q2=5, sus_q3=1, sus_q4=5, sus_q5=1,
        sus_q6=5, sus_q7=1, sus_q8=5, sus_q9=1, sus_q10=5,
        submitted_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    newer = UATFeedback(
        user_id=user.id,
        sus_q1=5, sus_q2=1, sus_q3=5, sus_q4=1, sus_q5=5,
        sus_q6=1, sus_q7=5, sus_q8=1, sus_q9=5, sus_q10=1,
        submitted_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    db.add_all([older, newer])
    db.flush()

    rows = export_uat_summary(db)
    assert rows[0]["sus_score"] == pytest.approx(100.0)


def test_export_uat_summary_csv_writable(db, user):
    """Output is CSV-ready: DictWriter round-trips without errors."""
    _seed_session(db, user.id)
    db.add(UATFeedback(
        user_id=user.id,
        sus_q1=4, sus_q2=2, sus_q3=4, sus_q4=2, sus_q5=4,
        sus_q6=2, sus_q7=4, sus_q8=2, sus_q9=4, sus_q10=2,
    ))
    db.flush()

    rows = export_uat_summary(db)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    buf.seek(0)
    parsed = list(csv.DictReader(buf))
    assert len(parsed) == 1
    assert parsed[0]["user_id"] == str(user.id)
    assert float(parsed[0]["sus_score"]) == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# Form-submission emulation: insert via the same code path the page uses
# ---------------------------------------------------------------------------

def test_form_submission_emulation_creates_row(db, user):
    """The Streamlit form's submission path is a plain SQLAlchemy add — verify
    that an equivalent direct insert with the same field names persists.
    """
    responses = {f"sus_q{i}": 3 for i in range(1, 11)}
    fb = UATFeedback(
        user_id=user.id,
        session_id=None,
        open_confusing="bagian onboarding",
        open_useful="grafik radar",
        **responses,
    )
    db.add(fb)
    db.flush()

    persisted = db.query(UATFeedback).filter_by(user_id=user.id).one()
    assert persisted.sus_score == pytest.approx(50.0)
    assert persisted.open_useful == "grafik radar"
