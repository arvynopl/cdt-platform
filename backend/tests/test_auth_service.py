"""tests/test_auth_service.py — register + authenticate integration tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, OnboardingSurvey, UserProfile
from modules.auth import (
    AuthError,
    DuplicateUsernameError,
    InvalidCredentialsError,
    RateLimitedError,
    WeakPasswordError,
    authenticate,
    rate_limit,
    register_user,
    user_exists,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    rate_limit._attempts.clear()
    yield sess
    sess.close()
    rate_limit._attempts.clear()


REG_BASE = dict(
    password="strongpass123",
    full_name="Jaka Sembung",
    age=24,
    gender="laki-laki",
    risk_profile="moderat",
    investing_capability="pemula",
)


def _survey() -> dict:
    return {
        "dei_q1": 3, "dei_q2": 4, "dei_q3": 2,
        "ocs_q1": 2, "ocs_q2": 3, "ocs_q3": 3,
        "lai_q1": 4, "lai_q2": 3, "lai_q3": 4,
    }


def test_register_creates_user_profile_and_onboarding_survey(session):
    user = register_user(
        session,
        username="jaka",
        onboarding_survey=_survey(),
        **REG_BASE,
    )
    session.commit()

    assert user.id is not None
    assert user.username == "jaka"
    assert user.password_hash and user.password_hash != "strongpass123"
    assert user.alias == "jaka"  # legacy field populated
    assert user.experience_level == "beginner"  # mapped from "pemula"

    profile = session.query(UserProfile).filter_by(user_id=user.id).one()
    assert profile.full_name == "Jaka Sembung"
    assert profile.age == 24
    assert profile.gender == "laki-laki"
    assert profile.risk_profile == "moderat"

    onboard = session.query(OnboardingSurvey).filter_by(user_id=user.id).one()
    assert onboard.dei_q1 == 3
    assert 1 <= onboard.dei_mean <= 5


def test_register_without_survey_still_persists_user(session):
    user = register_user(session, username="tanpa_survei", **REG_BASE)
    session.commit()
    assert user.id is not None
    assert session.query(OnboardingSurvey).filter_by(user_id=user.id).first() is None


def test_duplicate_username_raises(session):
    register_user(session, username="duplikat", **REG_BASE)
    session.commit()
    with pytest.raises(DuplicateUsernameError):
        register_user(session, username="duplikat", **REG_BASE)


def test_weak_password_raises(session):
    with pytest.raises(WeakPasswordError):
        register_user(
            session,
            username="lemah",
            password="abc",
            full_name="User",
            age=20,
            gender="lainnya",
            risk_profile="moderat",
            investing_capability="pemula",
        )


def test_invalid_gender_rejected(session):
    with pytest.raises(AuthError):
        register_user(
            session,
            username="bad_gender",
            password="strongpass123",
            full_name="User",
            age=20,
            gender="male",  # invalid — must use Bahasa Indonesia enum
            risk_profile="moderat",
            investing_capability="pemula",
        )


def test_authenticate_success(session):
    register_user(session, username="alice", **REG_BASE)
    session.commit()

    user = authenticate(session, "alice", "strongpass123")
    assert user.username == "alice"
    assert user.last_login_at is not None


def test_authenticate_wrong_password(session):
    register_user(session, username="alice", **REG_BASE)
    session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "alice", "nopenope")


def test_authenticate_unknown_user(session):
    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "nobody", "whatever12")


def test_authenticate_rate_limit_triggers(session):
    register_user(session, username="alice", **REG_BASE)
    session.commit()

    from config import AUTH_RATE_LIMIT_MAX
    for _ in range(AUTH_RATE_LIMIT_MAX):
        with pytest.raises(InvalidCredentialsError):
            authenticate(session, "alice", "wrong")
    with pytest.raises(RateLimitedError):
        authenticate(session, "alice", "strongpass123")


def test_authenticate_success_resets_attempts(session):
    register_user(session, username="alice", **REG_BASE)
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "alice", "wrong")
    assert rate_limit._debug_failure_count("alice") == 1
    authenticate(session, "alice", "strongpass123")
    assert rate_limit._debug_failure_count("alice") == 0


def test_user_exists(session):
    assert user_exists(session, "charlie") is False
    register_user(session, username="charlie", **REG_BASE)
    session.commit()
    assert user_exists(session, "charlie") is True
    assert user_exists(session, "") is False
