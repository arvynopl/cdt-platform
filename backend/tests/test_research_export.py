"""
tests/test_research_export.py — Tests for modules/utils/research_export.py.

Uses the shared in-memory ``db`` fixture from conftest.py. Seeds users,
onboarding surveys, bias metrics, CDT snapshots, and consent rows directly
without invoking the full simulation pipeline so the tests stay fast and
focused on the export logic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from database.models import (
    BiasMetric,
    CdtSnapshot,
    CognitiveProfile,
    ConsentLog,
    OnboardingSurvey,
    PostSessionSurvey,
    UATFeedback,
    User,
    UserAction,
    UserProfile,
)
from modules.utils.research_export import (
    export_all_sessions_csv,
    export_all_users_csv,
    export_cdt_snapshots_csv,
    export_post_session_surveys_csv,
    export_uat_feedback_csv,
    get_cohort_summary,
    load_model_performance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_user(db, username: str) -> User:
    u = User(username=username, alias=username, experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _make_profile(db, user_id: int) -> UserProfile:
    prof = UserProfile(
        user_id=user_id,
        full_name=f"User {user_id}",
        age=25,
        gender="laki-laki",
        risk_profile="moderat",
        investing_capability="pemula",
    )
    db.add(prof)
    db.flush()
    return prof


def _make_onboarding(db, user_id: int) -> OnboardingSurvey:
    onb = OnboardingSurvey(
        user_id=user_id,
        dei_q1=4, dei_q2=3, dei_q3=4,
        ocs_q1=2, ocs_q2=3, ocs_q3=2,
        lai_q1=5, lai_q2=4, lai_q3=5,
    )
    db.add(onb)
    db.flush()
    return onb


def _make_metric(
    db, user_id: int, computed_at: datetime,
    *, dei: float = 0.2, ocs: float = 0.4, lai: float = 1.5,
) -> BiasMetric:
    sid = str(uuid.uuid4())
    m = BiasMetric(
        user_id=user_id,
        session_id=sid,
        overconfidence_score=ocs,
        disposition_pgr=0.6,
        disposition_plr=0.3,
        disposition_dei=dei,
        loss_aversion_index=lai,
        computed_at=computed_at,
    )
    db.add(m)
    db.flush()
    return m


def _make_cdt(db, user_id: int) -> CognitiveProfile:
    cdt = CognitiveProfile(
        user_id=user_id,
        bias_intensity_vector={
            "overconfidence": 0.4,
            "disposition": 0.2,
            "loss_aversion": 0.5,
        },
        risk_preference=0.4,
        stability_index=0.7,
        session_count=2,
        last_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add(cdt)
    db.flush()
    return cdt


# ---------------------------------------------------------------------------
# Tests — get_cohort_summary
# ---------------------------------------------------------------------------
def test_get_cohort_summary_empty(db):
    summary = get_cohort_summary(db)
    assert summary["total_users"] == 0
    assert summary["total_sessions"] == 0
    assert summary["users_with_consent"] == 0
    assert summary["users_with_survey"] == 0
    assert summary["users_with_min_3_sessions"] == 0
    assert summary["completion_rate"] == 0.0
    assert summary["mean_dei"] == 0.0
    assert summary["sd_dei"] == 0.0
    assert summary["mean_stability_index"] == 0.0


def test_get_cohort_summary_basic(db):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    u1 = _make_user(db, "alpha")
    u2 = _make_user(db, "beta")
    u3 = _make_user(db, "gamma")
    _make_metric(db, u1.id, base, dei=0.1, ocs=0.2, lai=1.0)
    _make_metric(db, u2.id, base, dei=0.2, ocs=0.4, lai=1.5)
    _make_metric(db, u2.id, base + timedelta(hours=1), dei=0.3, ocs=0.5, lai=1.8)
    _make_metric(db, u3.id, base, dei=0.4, ocs=0.3, lai=2.0)
    _make_metric(db, u3.id, base + timedelta(hours=1), dei=0.2, ocs=0.3, lai=1.5)
    _make_metric(db, u3.id, base + timedelta(hours=2), dei=0.3, ocs=0.4, lai=1.7)

    summary = get_cohort_summary(db)
    assert summary["total_users"] == 3
    assert summary["total_sessions"] == 6
    assert summary["users_with_min_3_sessions"] == 1
    assert summary["completion_rate"] == pytest.approx(1 / 3, rel=1e-3)
    expected_mean_dei = (0.1 + 0.2 + 0.3 + 0.4 + 0.2 + 0.3) / 6
    assert summary["mean_dei"] == pytest.approx(expected_mean_dei, abs=1e-3)


def test_cohort_excludes_denylisted_username(db):
    """Denylisted dev/test accounts (e.g. "test1") must be dropped from
    participant stats even when they hold consent/profile/auth credentials."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    real = _make_user(db, "real_participant")
    _make_profile(db, real.id)
    db.add(ConsentLog(user_id=real.id, consent_given=True))
    test1 = _make_user(db, "test1")
    _make_profile(db, test1.id)
    db.add(ConsentLog(user_id=test1.id, consent_given=True))
    db.flush()
    _make_metric(db, real.id, base, dei=0.1)
    _make_metric(db, test1.id, base, dei=0.9)

    summary = get_cohort_summary(db, participants_only=True)
    assert summary["total_users"] == 1
    assert summary["excluded_non_participants"] == 1
    # test1's dei=0.9 must not leak into the cohort mean.
    assert summary["mean_dei"] == pytest.approx(0.1, abs=1e-6)


# ---------------------------------------------------------------------------
# Tests — export_all_users_csv
# ---------------------------------------------------------------------------
def test_export_all_users_csv_columns(db):
    u = _make_user(db, "schema_check")
    _make_profile(db, u.id)
    rows = export_all_users_csv(db)
    assert len(rows) == 1
    expected = {
        "user_id", "username", "age", "gender", "risk_profile",
        "investing_capability", "consent_given", "registered_at",
        "session_count",
        "onboarding_dei_q1", "onboarding_dei_q2", "onboarding_dei_q3",
        "onboarding_ocs_q1", "onboarding_ocs_q2", "onboarding_ocs_q3",
        "onboarding_lai_q1", "onboarding_lai_q2", "onboarding_lai_q3",
        "survey_risk_tolerance", "survey_loss_sensitivity",
        "survey_trading_frequency", "survey_holding_behavior",
        "cdt_overconfidence", "cdt_disposition", "cdt_loss_aversion",
        "risk_preference", "stability_index", "last_updated_at",
    }
    assert expected.issubset(set(rows[0].keys()))


def test_export_all_users_csv_includes_onboarding(db):
    u = _make_user(db, "with_onboard")
    _make_profile(db, u.id)
    _make_onboarding(db, u.id)
    db.add(ConsentLog(user_id=u.id, consent_given=True))
    db.flush()

    rows = export_all_users_csv(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["onboarding_dei_q1"] == 4
    assert row["onboarding_dei_q2"] == 3
    assert row["onboarding_dei_q3"] == 4
    assert row["onboarding_ocs_q1"] == 2
    assert row["onboarding_ocs_q2"] == 3
    assert row["onboarding_ocs_q3"] == 2
    assert row["onboarding_lai_q1"] == 5
    assert row["onboarding_lai_q2"] == 4
    assert row["onboarding_lai_q3"] == 5
    assert row["consent_given"] is True


def test_export_all_users_csv_handles_missing_survey(db):
    u = _make_user(db, "no_survey")
    rows = export_all_users_csv(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["onboarding_dei_q1"] is None
    assert row["onboarding_ocs_q2"] is None
    assert row["onboarding_lai_q3"] is None
    assert row["survey_risk_tolerance"] is None
    assert row["consent_given"] is False
    assert row["cdt_overconfidence"] is None


# ---------------------------------------------------------------------------
# Tests — export_all_sessions_csv
# ---------------------------------------------------------------------------
def test_export_all_sessions_csv_session_num_ordering(db):
    base = datetime(2026, 2, 1, tzinfo=UTC)
    u = _make_user(db, "sess_order")
    m1 = _make_metric(db, u.id, base + timedelta(hours=2))
    m2 = _make_metric(db, u.id, base + timedelta(hours=0))
    m3 = _make_metric(db, u.id, base + timedelta(hours=1))

    rows = export_all_sessions_csv(db)
    assert [r["session_num"] for r in rows] == [1, 2, 3]
    assert rows[0]["session_id"] == m2.session_id  # earliest first
    assert rows[1]["session_id"] == m3.session_id
    assert rows[2]["session_id"] == m1.session_id


def test_export_all_sessions_csv_action_count(db):
    """action_count column reflects the number of UserAction rows in the session."""
    base = datetime(2026, 3, 1, tzinfo=UTC)
    u = _make_user(db, "sess_actions")
    m = _make_metric(db, u.id, base)

    snap = db.query(__import__("database.models", fromlist=["MarketSnapshot"]).MarketSnapshot).first()
    for _ in range(5):
        db.add(UserAction(
            user_id=u.id, session_id=m.session_id, scenario_round=1,
            stock_id=snap.stock_id, snapshot_id=snap.id,
            action_type="hold", quantity=0, action_value=0.0,
            response_time_ms=100,
        ))
    db.flush()

    rows = export_all_sessions_csv(db)
    assert rows[0]["action_count"] == 5


# ---------------------------------------------------------------------------
# Tests — export_cdt_snapshots_csv
# ---------------------------------------------------------------------------
def test_export_cdt_snapshots_csv_ordering(db):
    base = datetime(2026, 4, 1, tzinfo=UTC)
    u_a = _make_user(db, "snap_a")
    u_b = _make_user(db, "snap_b")
    # Insert in a non-sorted order to verify ORDER BY clauses.
    for uid, sn in [
        (u_b.id, 2), (u_a.id, 2), (u_b.id, 1), (u_a.id, 1), (u_a.id, 3),
    ]:
        db.add(CdtSnapshot(
            user_id=uid,
            session_id=str(uuid.uuid4()),
            session_number=sn,
            cdt_overconfidence=0.1 * sn,
            cdt_disposition=0.05 * sn,
            cdt_loss_aversion=0.2 * sn,
            cdt_risk_preference=0.3,
            cdt_stability_index=0.5,
            snapshotted_at=base + timedelta(hours=sn),
        ))
    db.flush()

    rows = export_cdt_snapshots_csv(db)
    keys = [(r["user_id"], r["session_number"]) for r in rows]
    assert keys == [
        (u_a.id, 1), (u_a.id, 2), (u_a.id, 3),
        (u_b.id, 1), (u_b.id, 2),
    ]


# ---------------------------------------------------------------------------
# Tests — load_model_performance
# ---------------------------------------------------------------------------
def test_load_model_performance_missing_dir(tmp_path):
    perf = load_model_performance(tmp_path / "does-not-exist")
    assert perf["available"] is False
    assert perf["summary"] is None
    assert perf["classification_report"] is None
    assert perf["feature_importance_path"] is None
    assert perf["decision_tree_path"] is None
    assert perf["generated_at"] is None


# ---------------------------------------------------------------------------
# Tests — participants_only filter (excludes admin/legacy/test residuals)
# ---------------------------------------------------------------------------
def test_cohort_summary_excludes_non_participants(db):
    """A user without consent / profile / password_hash must be excluded
    from cohort means when participants_only=True is set, otherwise their
    rows would distort the UAT statistics shown to the researcher."""
    base = datetime(2026, 5, 1, tzinfo=UTC)

    # Real participant: registered through auth + consent + profile.
    real = User(
        username="real_user",
        password_hash="$2b$12$xxxxxxxxxxxxxxxxxxxxxx",
        alias="real_user",
        experience_level="beginner",
    )
    db.add(real); db.flush()
    _make_profile(db, real.id)
    db.add(ConsentLog(user_id=real.id, consent_given=True))
    _make_metric(db, real.id, base, dei=0.10, ocs=0.20, lai=1.10)

    # Admin/legacy artifact: alias-only, no consent, no profile, no auth.
    ghost = User(alias="pgjson_a2923b81", experience_level="beginner")
    db.add(ghost); db.flush()
    _make_metric(db, ghost.id, base, dei=0.90, ocs=0.90, lai=2.50)
    _make_cdt(db, ghost.id)

    summary_all = get_cohort_summary(db)
    summary_filt = get_cohort_summary(db, participants_only=True)

    assert summary_all["total_users"] == 2
    assert summary_filt["total_users"] == 1
    assert summary_filt["excluded_non_participants"] == 1

    # Means must reflect only the real participant's metrics.
    assert summary_filt["mean_dei"] == pytest.approx(0.10, abs=1e-3)
    assert summary_filt["mean_ocs"] == pytest.approx(0.20, abs=1e-3)
    assert summary_filt["mean_lai"] == pytest.approx(1.10, abs=1e-3)
    # Stability index from the ghost's CDT must NOT contaminate the mean.
    assert summary_filt["mean_stability_index"] == 0.0


def test_export_users_excludes_non_participants(db):
    real = User(
        username="real_export",
        password_hash="$2b$12$realhash",
        alias="real_export",
        experience_level="beginner",
    )
    db.add(real); db.flush()
    _make_profile(db, real.id)
    db.add(ConsentLog(user_id=real.id, consent_given=True))

    ghost = User(alias="pgjson_legacy", experience_level="beginner")
    db.add(ghost); db.flush()
    db.flush()

    rows_all = export_all_users_csv(db)
    rows_filt = export_all_users_csv(db, participants_only=True)
    assert len(rows_all) == 2
    assert len(rows_filt) == 1
    assert rows_filt[0]["username"] == "real_export"


def test_export_sessions_and_snapshots_exclude_non_participants(db):
    base = datetime(2026, 6, 1, tzinfo=UTC)

    real = User(
        username="real_sessions",
        password_hash="$2b$12$realhash",
        alias="real_sessions",
        experience_level="beginner",
    )
    db.add(real); db.flush()
    _make_profile(db, real.id)
    _make_metric(db, real.id, base, dei=0.1)

    ghost = User(alias="pgjson_ghost", experience_level="beginner")
    db.add(ghost); db.flush()
    _make_metric(db, ghost.id, base, dei=0.9)
    db.add(CdtSnapshot(
        user_id=ghost.id, session_id=str(uuid.uuid4()), session_number=1,
        cdt_overconfidence=0.5, cdt_disposition=0.5, cdt_loss_aversion=0.5,
        cdt_risk_preference=0.3, cdt_stability_index=0.5, snapshotted_at=base,
    ))
    db.flush()

    sessions = export_all_sessions_csv(db, participants_only=True)
    snapshots = export_cdt_snapshots_csv(db, participants_only=True)
    assert all(r["user_id"] == real.id for r in sessions)
    assert snapshots == []  # ghost's snapshot must be filtered out


def test_consent_only_user_qualifies_as_participant(db):
    """A user whose only signal is an affirmative ConsentLog should still
    qualify (e.g., consented but not yet completed any session)."""
    consenting = User(alias="just_consented", experience_level="beginner")
    db.add(consenting); db.flush()
    db.add(ConsentLog(user_id=consenting.id, consent_given=True))
    db.flush()

    rows = export_all_users_csv(db, participants_only=True)
    assert any(r["user_id"] == consenting.id for r in rows)


# ---------------------------------------------------------------------------
# Tests — export_uat_feedback_csv (append-only history)
# ---------------------------------------------------------------------------
def _make_uat_feedback(
    db, user_id: int, submitted_at: datetime,
    *, sus_values: list[int] | None = None,
    confusing: str | None = None, useful: str | None = None,
    session_id: str | None = None,
) -> UATFeedback:
    """Insert a UATFeedback row. ``sus_values`` is a 10-int list mapped to
    sus_q1..sus_q10; defaults to all-3 (neutral) which scores 50."""
    if sus_values is None:
        sus_values = [3] * 10
    fb = UATFeedback(
        user_id=user_id,
        session_id=session_id,
        sus_q1=sus_values[0], sus_q2=sus_values[1], sus_q3=sus_values[2],
        sus_q4=sus_values[3], sus_q5=sus_values[4], sus_q6=sus_values[5],
        sus_q7=sus_values[6], sus_q8=sus_values[7], sus_q9=sus_values[8],
        sus_q10=sus_values[9],
        open_confusing=confusing,
        open_useful=useful,
        submitted_at=submitted_at,
    )
    db.add(fb)
    db.flush()
    return fb


def test_export_uat_feedback_csv_empty(db):
    """No feedback rows → empty list, never an error."""
    rows = export_uat_feedback_csv(db)
    assert rows == []


def test_export_uat_feedback_csv_columns(db):
    u = _make_user(db, "uat_schema")
    base = datetime(2026, 7, 1, tzinfo=UTC)
    _make_uat_feedback(db, u.id, base)
    rows = export_uat_feedback_csv(db)
    expected = {
        "user_id", "username", "session_id", "submitted_at",
        "submission_index",
        "sus_q1", "sus_q2", "sus_q3", "sus_q4", "sus_q5",
        "sus_q6", "sus_q7", "sus_q8", "sus_q9", "sus_q10",
        "sus_score", "open_confusing", "open_useful",
    }
    assert expected.issubset(set(rows[0].keys()))


def test_export_uat_feedback_csv_preserves_all_resubmissions(db):
    """Critical UAT contract: re-submissions must NOT overwrite. Every
    submission appears as its own row, ordered chronologically per user.
    Submission index is 1-based per user."""
    u = _make_user(db, "uat_resubmit")
    base = datetime(2026, 7, 1, tzinfo=UTC)
    # Three submissions inserted out-of-order to verify ORDER BY clause.
    _make_uat_feedback(db, u.id, base + timedelta(hours=2),
                       sus_values=[5] * 10, useful="third")
    _make_uat_feedback(db, u.id, base + timedelta(hours=0),
                       sus_values=[1] * 10, useful="first")
    _make_uat_feedback(db, u.id, base + timedelta(hours=1),
                       sus_values=[3] * 10, useful="second")

    rows = export_uat_feedback_csv(db)
    assert len(rows) == 3, "history must be preserved (no upsert/overwrite)"
    indices = [r["submission_index"] for r in rows]
    usefuls = [r["open_useful"] for r in rows]
    assert indices == [1, 2, 3]
    assert usefuls == ["first", "second", "third"]


def test_export_uat_feedback_csv_sus_score_computed(db):
    """The exported sus_score must match the model's computed property."""
    u = _make_user(db, "uat_score")
    base = datetime(2026, 8, 1, tzinfo=UTC)
    # Strong positive: all odd=5, all even=1 → SUS 100
    _make_uat_feedback(
        db, u.id, base, sus_values=[5, 1, 5, 1, 5, 1, 5, 1, 5, 1],
    )
    rows = export_uat_feedback_csv(db)
    assert rows[0]["sus_score"] == pytest.approx(100.0)


def test_export_uat_feedback_csv_orders_across_users(db):
    """Rows are grouped by user_id, then by submitted_at within each user."""
    u_a = _make_user(db, "uat_order_a")
    u_b = _make_user(db, "uat_order_b")
    base = datetime(2026, 9, 1, tzinfo=UTC)
    _make_uat_feedback(db, u_b.id, base + timedelta(hours=1))
    _make_uat_feedback(db, u_a.id, base + timedelta(hours=2))
    _make_uat_feedback(db, u_a.id, base + timedelta(hours=0))
    _make_uat_feedback(db, u_b.id, base + timedelta(hours=3))

    rows = export_uat_feedback_csv(db)
    keys = [(r["user_id"], r["submission_index"]) for r in rows]
    # User A's two rows come first (lower id), each indexed 1..2 by time;
    # User B's two rows next, each indexed 1..2 by time.
    assert keys == [
        (u_a.id, 1), (u_a.id, 2),
        (u_b.id, 1), (u_b.id, 2),
    ]


def test_export_uat_feedback_csv_excludes_non_participants(db):
    """A ghost user (no consent / profile / auth) must be filtered out when
    participants_only=True."""
    base = datetime(2026, 10, 1, tzinfo=UTC)
    real = User(
        username="real_uat",
        password_hash="$2b$12$realhash",
        alias="real_uat",
        experience_level="beginner",
    )
    db.add(real); db.flush()
    _make_profile(db, real.id)
    _make_uat_feedback(db, real.id, base, useful="real")

    ghost = User(alias="pgjson_ghost_uat", experience_level="beginner")
    db.add(ghost); db.flush()
    _make_uat_feedback(db, ghost.id, base, useful="ghost")

    rows_all = export_uat_feedback_csv(db)
    rows_filt = export_uat_feedback_csv(db, participants_only=True)
    assert len(rows_all) == 2
    assert len(rows_filt) == 1
    assert rows_filt[0]["open_useful"] == "real"


# ---------------------------------------------------------------------------
# Tests — export_post_session_surveys_csv
# ---------------------------------------------------------------------------
def _make_post_session(
    db, user_id: int, session_id: str, submitted_at: datetime,
    *, oc: int = 3, dei: int = 3, lai: int = 3, useful: int = 4,
) -> PostSessionSurvey:
    s = PostSessionSurvey(
        user_id=user_id,
        session_id=session_id,
        self_overconfidence=oc,
        self_disposition=dei,
        self_loss_aversion=lai,
        feedback_usefulness=useful,
        submitted_at=submitted_at,
    )
    db.add(s)
    db.flush()
    return s


def test_export_post_session_surveys_csv_empty(db):
    rows = export_post_session_surveys_csv(db)
    assert rows == []


def test_export_post_session_surveys_csv_columns(db):
    u = _make_user(db, "pss_schema")
    base = datetime(2026, 11, 1, tzinfo=UTC)
    _make_post_session(db, u.id, str(uuid.uuid4()), base)
    rows = export_post_session_surveys_csv(db)
    expected = {
        "user_id", "username", "session_id", "submitted_at",
        "self_overconfidence", "self_disposition", "self_loss_aversion",
        "feedback_usefulness",
    }
    assert expected.issubset(set(rows[0].keys()))


def test_export_post_session_surveys_csv_one_per_session(db):
    """Each session yields one row; multiple sessions per user yield
    multiple rows ordered by submitted_at."""
    u = _make_user(db, "pss_multi")
    base = datetime(2026, 11, 1, tzinfo=UTC)
    sid_a, sid_b = str(uuid.uuid4()), str(uuid.uuid4())
    # Insert in reverse to verify ORDER BY.
    _make_post_session(
        db, u.id, sid_b, base + timedelta(hours=1),
        oc=4, dei=2, lai=5, useful=3,
    )
    _make_post_session(
        db, u.id, sid_a, base + timedelta(hours=0),
        oc=2, dei=4, lai=2, useful=5,
    )

    rows = export_post_session_surveys_csv(db)
    assert len(rows) == 2
    assert rows[0]["session_id"] == sid_a
    assert rows[1]["session_id"] == sid_b
    assert rows[0]["feedback_usefulness"] == 5
    assert rows[1]["feedback_usefulness"] == 3


def test_export_post_session_surveys_csv_excludes_non_participants(db):
    base = datetime(2026, 12, 1, tzinfo=UTC)
    real = User(
        username="real_pss",
        password_hash="$2b$12$realhash",
        alias="real_pss",
        experience_level="beginner",
    )
    db.add(real); db.flush()
    _make_profile(db, real.id)
    _make_post_session(db, real.id, str(uuid.uuid4()), base, useful=5)

    ghost = User(alias="pgjson_ghost_pss", experience_level="beginner")
    db.add(ghost); db.flush()
    _make_post_session(db, ghost.id, str(uuid.uuid4()), base, useful=1)

    rows_filt = export_post_session_surveys_csv(db, participants_only=True)
    assert len(rows_filt) == 1
    assert rows_filt[0]["feedback_usefulness"] == 5


def test_load_model_performance_with_files(tmp_path):
    summary_payload = {
        "generated_at": "2026-04-23T19:41:57.334641+00:00",
        "overall_accuracy": 0.95,
        "n_training_samples": 50,
        "used_synthetic_data": False,
    }
    (tmp_path / "ml_summary.json").write_text(
        json.dumps(summary_payload), encoding="utf-8",
    )
    (tmp_path / "ml_classification_report.csv").write_text(
        "kelas,precision,recall,f1_score,support\n"
        "Tidak Ada Bias,1.0,1.0,1.0,5\n"
        "Rata-rata Makro,0.98,0.97,0.97,5\n",
        encoding="utf-8",
    )
    (tmp_path / "ml_feature_importance.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "ml_decision_tree.png").write_bytes(b"\x89PNG fake")

    perf = load_model_performance(tmp_path)
    assert perf["available"] is True
    assert perf["summary"]["overall_accuracy"] == 0.95
    assert perf["generated_at"] == summary_payload["generated_at"]
    assert isinstance(perf["classification_report"], list)
    assert perf["classification_report"][0]["kelas"] == "Tidak Ada Bias"
    assert perf["feature_importance_path"].endswith("ml_feature_importance.png")
    assert perf["decision_tree_path"].endswith("ml_decision_tree.png")
