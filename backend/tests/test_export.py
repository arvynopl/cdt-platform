"""
tests/test_export.py — Tests for modules/utils/export.py.

Uses shared db/user fixtures from conftest.py and runs the full pipeline to
produce real BiasMetric and FeedbackHistory records before exporting.
"""

import csv
import uuid
from datetime import date, timedelta
from pathlib import Path

from database.models import MarketSnapshot, UserAction
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.utils.export import (
    export_session_data,
    export_session_to_dict,
    export_user_history_csv,
)

BASE_DATE = date(2024, 4, 2)
STOCK_IDS = ["BBCA.JK", "TLKM.JK", "ANTM.JK", "GOTO.JK", "UNVR.JK", "BBRI.JK"]


def _snap(db, stock_id: str, round_num: int) -> MarketSnapshot:
    return db.query(MarketSnapshot).filter_by(
        stock_id=stock_id, date=BASE_DATE + timedelta(days=round_num - 1)
    ).first()


def _log_full_session(db, user_id: int, session_id: str):
    """Log 14 rounds of hold-only actions."""
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


def _run_pipeline(db, user_id: int, session_id: str):
    _log_full_session(db, user_id, session_id)
    bias_metric = compute_and_save_metrics(db, user_id, session_id)
    profile = update_profile(db, user_id, bias_metric, session_id)
    generate_feedback(db, user_id, session_id, bias_metric, profile)
    return bias_metric


def test_export_session_to_dict_structure(db, user):
    """export_session_to_dict returns dict with all expected keys."""
    sid = str(uuid.uuid4())
    _run_pipeline(db, user.id, sid)

    result = export_session_to_dict(db, user.id, sid)
    assert result["session_id"] == sid
    assert result["user_id"] == user.id
    assert "overconfidence_score" in result
    assert "disposition_dei" in result
    assert "loss_aversion_index" in result
    assert isinstance(result["feedback"], list)


def test_export_session_feedback_list_length(db, user):
    """After pipeline, feedback list has exactly 3 entries (one per bias)."""
    sid = str(uuid.uuid4())
    _run_pipeline(db, user.id, sid)

    result = export_session_to_dict(db, user.id, sid)
    assert len(result["feedback"]) == 3


def test_export_user_history_csv_returns_list(db, user):
    """After 2 sessions, export_user_history_csv returns list of length 2."""
    for _ in range(2):
        sid = str(uuid.uuid4())
        _run_pipeline(db, user.id, sid)

    rows = export_user_history_csv(db, user.id)
    assert len(rows) == 2


def test_export_user_history_csv_session_num_increments(db, user):
    """session_num in returned rows increments from 1."""
    for _ in range(3):
        sid = str(uuid.uuid4())
        _run_pipeline(db, user.id, sid)

    rows = export_user_history_csv(db, user.id)
    nums = [r["session_num"] for r in rows]
    assert nums == [1, 2, 3]


def test_export_session_data_writes_csv_files(db, user, tmp_path):
    """export_session_data writes 5 CSV files to the output directory."""
    sid = str(uuid.uuid4())
    _run_pipeline(db, user.id, sid)

    written = export_session_data(db, user.id, sid, tmp_path)
    assert len(written) == 5
    for path in written:
        assert Path(path).exists()
        assert Path(path).stat().st_size > 0


def test_export_session_data_actions_csv_has_rows(db, user, tmp_path):
    """The actions CSV contains one row per logged UserAction."""
    from config import ROUNDS_PER_SESSION
    sid = str(uuid.uuid4())
    _run_pipeline(db, user.id, sid)

    written = export_session_data(db, user.id, sid, tmp_path)
    actions_file = next(p for p in written if "actions" in Path(p).name)
    with open(actions_file, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == ROUNDS_PER_SESSION * len(STOCK_IDS)
