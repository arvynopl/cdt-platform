"""
tests/test_cdt_elevation.py — Tests for CDT elevation features.

Covers:
    - _get_interaction_modifier() — cross-bias coupling insights
    - _classify_bias_trajectory() — 3-session trend classifier
    - _get_cdt_modifier() — upgraded trajectory-aware modifier
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base,
    BiasMetric,
    FeedbackHistory,
    User,
)
from modules.cdt.profile import get_or_create_profile
from modules.feedback.generator import (
    _classify_bias_trajectory,
    _get_cdt_modifier,
    _get_interaction_modifier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture()
def user(db):
    u = User(alias="elevation_test_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _add_bias_metric(db, user_id, ocs=0.0, dei=0.0, lai=1.0, days_ago=0):
    """Helper: insert a BiasMetric with a backdated computed_at."""
    sid = str(uuid.uuid4())
    m = BiasMetric(
        user_id=user_id,
        session_id=sid,
        overconfidence_score=ocs,
        disposition_pgr=max(dei, 0.0),
        disposition_plr=0.0,
        disposition_dei=dei,
        loss_aversion_index=lai,
        computed_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(m)
    db.flush()
    return m


def _add_feedback(db, user_id, session_id, bias_type, severity, days_ago=0):
    """Helper: insert a FeedbackHistory record."""
    fh = FeedbackHistory(
        user_id=user_id,
        session_id=session_id,
        bias_type=bias_type,
        severity=severity,
        explanation_text=f"Test explanation for {bias_type}",
        recommendation_text="Test recommendation",
        delivered_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(fh)
    db.flush()
    return fh


# ---------------------------------------------------------------------------
# Tests: _get_interaction_modifier()
# ---------------------------------------------------------------------------

class _FakeProfile:
    """Minimal profile-like object for testing _get_interaction_modifier."""
    def __init__(self, session_count, interaction_scores):
        self.session_count = session_count
        self.interaction_scores = interaction_scores
        self.stability_index = 0.5


def test_interaction_modifier_returns_empty_below_session_threshold():
    """Fewer than 3 sessions → no insights regardless of correlation."""
    profile = _FakeProfile(
        session_count=2,
        interaction_scores={"ocs_dei": 0.9, "ocs_lai": 0.8, "dei_lai": 0.7},
    )
    result = _get_interaction_modifier(profile)
    assert result == []


def test_interaction_modifier_returns_empty_when_no_scores():
    """interaction_scores is None → no insights."""
    profile = _FakeProfile(session_count=6, interaction_scores=None)
    assert _get_interaction_modifier(profile) == []


def test_interaction_modifier_returns_empty_below_threshold():
    """All correlations below 0.65 → no insights."""
    profile = _FakeProfile(
        session_count=6,
        interaction_scores={"ocs_dei": 0.4, "ocs_lai": 0.3, "dei_lai": 0.5},
    )
    assert _get_interaction_modifier(profile) == []


def test_interaction_modifier_high_ocs_dei():
    """OCS-DEI r = 0.80 → insight about overtrading + premature winner selling."""
    profile = _FakeProfile(
        session_count=6,
        interaction_scores={"ocs_dei": 0.80, "ocs_lai": None, "dei_lai": None},
    )
    insights = _get_interaction_modifier(profile)
    assert len(insights) == 1
    assert "overconfidence" in insights[0].lower() or "disposisi" in insights[0].lower()


def test_interaction_modifier_high_dei_lai_positive():
    """DEI-LAI r = 0.70 → insight about dual reinforcing biases."""
    profile = _FakeProfile(
        session_count=7,
        interaction_scores={"ocs_dei": None, "ocs_lai": None, "dei_lai": 0.70},
    )
    insights = _get_interaction_modifier(profile)
    assert len(insights) == 1
    # Should mention both biases reinforcing each other
    text = insights[0].lower()
    assert "memperkuat" in text or "bersamaan" in text


def test_interaction_modifier_negative_correlation_compensatory():
    """OCS-LAI r = -0.70 → compensatory pattern insight."""
    profile = _FakeProfile(
        session_count=6,
        interaction_scores={"ocs_dei": None, "ocs_lai": -0.70, "dei_lai": None},
    )
    insights = _get_interaction_modifier(profile)
    assert len(insights) == 1
    assert "kompensasi" in insights[0].lower()


def test_interaction_modifier_multiple_strong_correlations():
    """Two strong correlations → two separate insights."""
    profile = _FakeProfile(
        session_count=6,
        interaction_scores={"ocs_dei": 0.75, "ocs_lai": None, "dei_lai": 0.80},
    )
    insights = _get_interaction_modifier(profile)
    assert len(insights) == 2


def test_interaction_modifier_exactly_at_threshold():
    """OCS-DEI r = 0.65 (boundary) → insight IS returned (>= threshold)."""
    profile = _FakeProfile(
        session_count=5,
        interaction_scores={"ocs_dei": 0.65, "ocs_lai": None, "dei_lai": None},
    )
    insights = _get_interaction_modifier(profile)
    assert len(insights) == 1


def test_interaction_modifier_just_below_threshold():
    """OCS-DEI r = 0.64 (just below boundary) → no insight."""
    profile = _FakeProfile(
        session_count=5,
        interaction_scores={"ocs_dei": 0.64, "ocs_lai": None, "dei_lai": None},
    )
    assert _get_interaction_modifier(profile) == []


# ---------------------------------------------------------------------------
# Tests: _classify_bias_trajectory()
# ---------------------------------------------------------------------------

def test_trajectory_improving_overconfidence(db, user):
    """3 prior sessions with strictly decreasing OCS → 'improving'."""
    # oldest → newest: 0.8 → 0.5 → 0.3 (strictly decreasing)
    _add_bias_metric(db, user.id, ocs=0.8, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.5, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "overconfidence")
    assert result == "improving"


def test_trajectory_worsening_disposition(db, user):
    """3 prior sessions with strictly increasing |DEI| → 'worsening'."""
    _add_bias_metric(db, user.id, dei=0.1, days_ago=4)
    _add_bias_metric(db, user.id, dei=0.2, days_ago=3)
    _add_bias_metric(db, user.id, dei=0.4, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "disposition_effect")
    assert result == "worsening"


def test_trajectory_stable_loss_aversion(db, user):
    """3 prior sessions with LAI within 0.05 band → 'stable'."""
    # normalized: min(1.5/3, 1) = 0.5, min(1.52/3, 1) ≈ 0.507, min(1.48/3, 1) ≈ 0.493
    _add_bias_metric(db, user.id, lai=1.5, days_ago=4)
    _add_bias_metric(db, user.id, lai=1.52, days_ago=3)
    _add_bias_metric(db, user.id, lai=1.48, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "loss_aversion")
    assert result == "stable"


def test_trajectory_volatile_pattern(db, user):
    """Non-monotonic pattern → 'volatile'."""
    # 0.2 → 0.6 → 0.3 (up then down, not monotonic)
    _add_bias_metric(db, user.id, ocs=0.2, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.6, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "overconfidence")
    assert result == "volatile"


def test_trajectory_insufficient_two_prior(db, user):
    """Only 2 prior sessions → 'insufficient'."""
    _add_bias_metric(db, user.id, ocs=0.5, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "overconfidence")
    assert result == "insufficient"


def test_trajectory_insufficient_zero_prior(db, user):
    """No prior sessions → 'insufficient'."""
    current_sid = str(uuid.uuid4())
    result = _classify_bias_trajectory(db, user.id, current_sid, "overconfidence")
    assert result == "insufficient"


def test_trajectory_excludes_current_session(db, user):
    """Current session metrics must NOT be counted as prior sessions."""
    _add_bias_metric(db, user.id, ocs=0.8, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.6, days_ago=3)

    # Third metric IS the current session — should be excluded
    current_metric = _add_bias_metric(db, user.id, ocs=0.1, days_ago=0)

    result = _classify_bias_trajectory(
        db, user.id, current_metric.session_id, "overconfidence"
    )
    # Only 2 prior sessions available after excluding current → insufficient
    assert result == "insufficient"


def test_trajectory_uses_last_three_of_many(db, user):
    """When 5 prior sessions exist, only the most recent 3 should be used."""
    # Sessions (oldest→newest): 0.9, 0.8, 0.7, 0.5, 0.3 — last 3 are 0.7→0.5→0.3 (improving)
    _add_bias_metric(db, user.id, ocs=0.9, days_ago=6)
    _add_bias_metric(db, user.id, ocs=0.8, days_ago=5)
    _add_bias_metric(db, user.id, ocs=0.7, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.5, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=2)
    current_sid = str(uuid.uuid4())

    result = _classify_bias_trajectory(db, user.id, current_sid, "overconfidence")
    assert result == "improving"


# ---------------------------------------------------------------------------
# Tests: _get_cdt_modifier() integration
# ---------------------------------------------------------------------------

def test_cdt_modifier_improving_trajectory_generates_positive_text(db, user):
    """Improving trajectory → modifier contains positive Bahasa Indonesia text."""
    _add_bias_metric(db, user.id, ocs=0.8, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.5, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=2)

    profile = get_or_create_profile(db, user.id)
    profile.session_count = 4  # simulate 4+ sessions
    db.flush()

    current_sid = str(uuid.uuid4())
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "mild", profile)

    assert result != ""
    assert "positif" in result.lower() or "menurun" in result.lower()


def test_cdt_modifier_worsening_trajectory_generates_warning(db, user):
    """Worsening trajectory → modifier contains warning text."""
    _add_bias_metric(db, user.id, ocs=0.2, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.4, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.7, days_ago=2)

    profile = get_or_create_profile(db, user.id)
    profile.session_count = 4
    db.flush()

    current_sid = str(uuid.uuid4())
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "severe", profile)

    assert result != ""
    assert "perhatian" in result.lower() or "meningkat" in result.lower()


def test_cdt_modifier_below_session_threshold_returns_empty(db, user):
    """session_count < 3 → always returns empty string."""
    profile = get_or_create_profile(db, user.id)
    profile.session_count = 2
    db.flush()

    current_sid = str(uuid.uuid4())
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "moderate", profile)
    assert result == ""


def test_cdt_modifier_stable_trajectory_returns_empty_for_mild(db, user):
    """Stable trajectory + mild severity → no modifier (nothing actionable)."""
    _add_bias_metric(db, user.id, ocs=0.3, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.31, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.29, days_ago=2)

    profile = get_or_create_profile(db, user.id)
    profile.session_count = 4
    db.flush()

    current_sid = str(uuid.uuid4())
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "mild", profile)
    # Stable + mild → no trajectory modifier; no stability warning (stability_index = 0.0 < 0.75)
    assert result == ""


def test_cdt_modifier_stability_warning_appended(db, user):
    """High stability_index + moderate severity → stability warning appended."""
    _add_bias_metric(db, user.id, ocs=0.5, days_ago=4)
    _add_bias_metric(db, user.id, ocs=0.52, days_ago=3)
    _add_bias_metric(db, user.id, ocs=0.49, days_ago=2)

    profile = get_or_create_profile(db, user.id)
    profile.session_count = 5
    profile.stability_index = 0.85  # above CDT_MODIFIER_STABILITY_THRESHOLD (0.75)
    db.flush()

    current_sid = str(uuid.uuid4())
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "moderate", profile)
    # Stable trajectory + high stability + moderate severity → stability warning
    assert "konsisten" in result.lower() or "strategi" in result.lower()


def test_cdt_modifier_insufficient_falls_back_to_single_lag(db, user):
    """With only 2 prior sessions, falls back to single-lag FeedbackHistory comparison."""
    m1 = _add_bias_metric(db, user.id, ocs=0.6, days_ago=3)
    _add_feedback(db, user.id, m1.session_id, "overconfidence", "moderate", days_ago=3)

    profile = get_or_create_profile(db, user.id)
    profile.session_count = 3  # 3 total, but only 1 prior BiasMetric
    db.flush()

    current_sid = str(uuid.uuid4())
    # Current severity "mild" < previous "moderate" → positive feedback
    result = _get_cdt_modifier(db, user.id, current_sid, "overconfidence", "mild", profile)
    assert "positif" in result.lower() or "menurun" in result.lower()
