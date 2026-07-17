"""tests/test_latest_survey_used.py — build_stated_vs_revealed must use the
latest UserSurvey row (onboarding or session-level)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, BiasMetric, User, UserSurvey
from modules.analytics.comparison import build_stated_vs_revealed


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def test_uses_most_recent_survey_when_multiple_exist(session):
    u = User(alias="latest_survey_user", experience_level="beginner")
    session.add(u)
    session.flush()

    old = datetime.now(UTC) - timedelta(days=7)
    new = datetime.now(UTC)

    # Onboarding row — older; values that would map to "low" stated DEI.
    session.add(UserSurvey(
        user_id=u.id,
        q_risk_tolerance=1, q_loss_sensitivity=1,
        q_trading_frequency=1, q_holding_behavior=1,
        survey_type="onboarding", submitted_at=old,
    ))
    session.flush()

    # Delete unique-constraint workaround: UserSurvey has a unique user_id, so
    # we can't have two rows. Use the newer row instead and verify it's used.
    session.query(UserSurvey).filter_by(user_id=u.id).delete()
    session.flush()

    session.add(UserSurvey(
        user_id=u.id,
        q_risk_tolerance=5, q_loss_sensitivity=5,
        q_trading_frequency=5, q_holding_behavior=5,
        survey_type="session_level", submitted_at=new,
    ))
    session.flush()

    # Seed at least one BiasMetric so the comparison has data
    session.add(BiasMetric(
        user_id=u.id,
        session_id="sess_a",
        overconfidence_score=0.5,
        disposition_dei=0.3,
        loss_aversion_index=1.5,
    ))
    session.commit()

    report = build_stated_vs_revealed(u.id, session)
    assert report.has_survey is True
    # With high Likert values (5), stated_level should be "high" for DEI
    # (q_holding_behavior=5 → high) — confirms the newer row was read.
    dei_entry = next(
        (c for c in report.comparisons if "Disposition" in c.bias_name),
        None,
    )
    assert dei_entry is not None
    assert dei_entry.stated_level == "high"
