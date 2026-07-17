"""tests/test_onboarding_survey.py — verify onboarding survey persistence
and UserSurvey.survey_type discrimination."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, OnboardingSurvey, User, UserSurvey
from modules.auth import register_user


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def test_onboarding_survey_is_persisted(session):
    survey = {
        "dei_q1": 5, "dei_q2": 4, "dei_q3": 3,
        "ocs_q1": 2, "ocs_q2": 3, "ocs_q3": 4,
        "lai_q1": 5, "lai_q2": 5, "lai_q3": 4,
    }
    register_user(
        session,
        username="onboard_a",
        password="strongpass123",
        full_name="Onboard A",
        age=30, gender="perempuan",
        risk_profile="agresif",
        investing_capability="menengah",
        onboarding_survey=survey,
    )
    session.commit()

    row = session.query(OnboardingSurvey).one()
    for k, v in survey.items():
        assert getattr(row, k) == v
    assert pytest.approx(row.dei_mean, 0.01) == 4.0
    assert pytest.approx(row.ocs_mean, 0.01) == 3.0
    assert pytest.approx(row.lai_mean, 0.01) == pytest.approx(14 / 3, 0.01)


def test_onboarding_survey_rejects_out_of_range(session):
    from modules.auth.service import AuthError

    bad = {
        "dei_q1": 6, "dei_q2": 4, "dei_q3": 3,
        "ocs_q1": 2, "ocs_q2": 3, "ocs_q3": 4,
        "lai_q1": 5, "lai_q2": 5, "lai_q3": 4,
    }
    with pytest.raises(AuthError):
        register_user(
            session,
            username="bad_onboard",
            password="strongpass123",
            full_name="Bad Onboard",
            age=25, gender="lainnya",
            risk_profile="konservatif",
            investing_capability="pemula",
            onboarding_survey=bad,
        )


def test_user_survey_discriminator_defaults_to_session_level(session):
    # Create a user and an onboarding-style UserSurvey row using the new enum
    u = User(alias="discr_user", experience_level="beginner")
    session.add(u)
    session.flush()

    legacy = UserSurvey(
        user_id=u.id,
        q_risk_tolerance=3,
        q_loss_sensitivity=3,
        q_trading_frequency=3,
        q_holding_behavior=3,
    )
    session.add(legacy)
    session.commit()

    fetched = session.query(UserSurvey).filter_by(user_id=u.id).one()
    assert fetched.survey_type == "session_level"


def test_user_survey_discriminator_onboarding(session):
    u = User(alias="discr_user2", experience_level="beginner")
    session.add(u)
    session.flush()

    row = UserSurvey(
        user_id=u.id,
        q_risk_tolerance=4,
        q_loss_sensitivity=4,
        q_trading_frequency=2,
        q_holding_behavior=5,
        survey_type="onboarding",
    )
    session.add(row)
    session.commit()

    fetched = session.query(UserSurvey).filter_by(user_id=u.id).one()
    assert fetched.survey_type == "onboarding"
