"""
tests/test_comparison.py — Unit tests for the stated-vs-revealed comparison module.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, BiasMetric, User, UserSurvey
from modules.analytics.comparison import (
    StatedVsRevealedReport,
    build_stated_vs_revealed,
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
    u = User(alias="comparison_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _add_survey(db, user_id, risk_tolerance, loss_sensitivity, trading_frequency, holding_behavior):
    s = UserSurvey(
        user_id=user_id,
        q_risk_tolerance=risk_tolerance,
        q_loss_sensitivity=loss_sensitivity,
        q_trading_frequency=trading_frequency,
        q_holding_behavior=holding_behavior,
    )
    db.add(s)
    db.flush()
    return s


def _add_metric(db, user_id, ocs=0.0, dei=0.0, lai=1.0):
    m = BiasMetric(
        user_id=user_id,
        session_id=str(uuid.uuid4()),
        overconfidence_score=ocs,
        disposition_pgr=max(dei, 0.0),
        disposition_plr=0.0,
        disposition_dei=dei,
        loss_aversion_index=lai,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_survey_returns_no_survey(db, user):
    """User without a survey → has_survey=False, overall_alignment='no_survey'."""
    report = build_stated_vs_revealed(user.id, db)
    assert isinstance(report, StatedVsRevealedReport)
    assert report.has_survey is False
    assert report.overall_alignment == "no_survey"
    assert report.comparisons == []


def test_survey_present_no_metric_returns_report(db, user):
    """User with survey but no BiasMetric → has_survey=True, comparisons populated."""
    _add_survey(db, user.id,
                risk_tolerance=3, loss_sensitivity=3,
                trading_frequency=3, holding_behavior=3)
    report = build_stated_vs_revealed(user.id, db)
    assert report.has_survey is True
    assert len(report.comparisons) == 3
    assert report.overall_alignment in ("aligned", "discrepant", "no_survey")


def test_underestimates_bias_severe_dei_stated_low(db, user):
    """Severe DEI detected but user stated 'rarely rush to sell' (q_holding_behavior=1).

    stated DEI = low (q_holding_behavior=1 → 'low')
    revealed DEI = high (DEI=0.65 → severe → 'high')
    → discrepancy = 'underestimates_bias'
    """
    _add_survey(db, user.id,
                risk_tolerance=3, loss_sensitivity=3,
                trading_frequency=3, holding_behavior=1)  # q_holding_behavior=1 → low DEI stated
    _add_metric(db, user.id, dei=0.65)  # severe DEI

    report = build_stated_vs_revealed(user.id, db)
    assert report.has_survey is True

    dei_comp = next(c for c in report.comparisons if c.bias_name == "Disposition Effect")
    assert dei_comp.stated_level == "low"
    assert dei_comp.revealed_level == "high"
    assert dei_comp.discrepancy == "underestimates_bias"
    assert report.overall_alignment == "discrepant"


def test_overestimates_discipline_none_dei_stated_high(db, user):
    """No DEI detected but user stated 'often rush to sell' (q_holding_behavior=5).

    stated DEI = high (q_holding_behavior=5 → 'high')
    revealed DEI = low (DEI=0.0 → none → 'low')
    → discrepancy = 'overestimates_discipline'
    (user's actual behavior shows more discipline than stated)
    """
    _add_survey(db, user.id,
                risk_tolerance=3, loss_sensitivity=3,
                trading_frequency=3, holding_behavior=5)  # high DEI stated
    _add_metric(db, user.id, dei=0.0)  # no DEI revealed

    report = build_stated_vs_revealed(user.id, db)
    dei_comp = next(c for c in report.comparisons if c.bias_name == "Disposition Effect")
    assert dei_comp.stated_level == "high"
    assert dei_comp.revealed_level == "low"
    assert dei_comp.discrepancy == "overestimates_discipline"


def test_aligned_when_stated_matches_revealed(db, user):
    """Medium stated and moderate (medium) revealed → aligned."""
    _add_survey(db, user.id,
                risk_tolerance=3, loss_sensitivity=3,
                trading_frequency=3, holding_behavior=3)  # all medium
    # OCS moderate → revealed medium
    _add_metric(db, user.id, ocs=0.5, dei=0.0, lai=1.0)

    report = build_stated_vs_revealed(user.id, db)
    ocs_comp = next(c for c in report.comparisons if c.bias_name == "Overconfidence")
    assert ocs_comp.stated_level == "medium"
    assert ocs_comp.revealed_level == "medium"
    assert ocs_comp.discrepancy == "aligned"


def test_interpretation_text_populated(db, user):
    """interpretation_id should be a non-empty Bahasa Indonesia string."""
    _add_survey(db, user.id,
                risk_tolerance=3, loss_sensitivity=3,
                trading_frequency=3, holding_behavior=1)
    _add_metric(db, user.id, dei=0.65)

    report = build_stated_vs_revealed(user.id, db)
    for comp in report.comparisons:
        assert isinstance(comp.interpretation_id, str)
        assert len(comp.interpretation_id) > 0
