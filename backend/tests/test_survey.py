"""tests/test_survey.py — UserSurvey model and export integration tests."""


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, User, UserSurvey


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
    u = User(alias="survey_tester", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


class TestUserSurveyModel:
    """CRUD and constraint tests for UserSurvey."""

    def test_create_survey(self, db, user):
        survey = UserSurvey(
            user_id=user.id,
            q_risk_tolerance=4,
            q_loss_sensitivity=2,
            q_trading_frequency=3,
            q_holding_behavior=5,
        )
        db.add(survey)
        db.flush()
        assert survey.id is not None
        assert survey.submitted_at is not None

    def test_multiple_surveys_per_user_allowed(self, db, user):
        # cdt-platform baseline drops the legacy one-survey-per-user UNIQUE
        # constraint: survey_type="session_level" rows are repeatable by
        # design (one per completed session), so a user accumulates history.
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=3,
            q_loss_sensitivity=3, q_trading_frequency=3, q_holding_behavior=3,
        ))
        db.flush()
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=4,
            q_loss_sensitivity=4, q_trading_frequency=4, q_holding_behavior=4,
        ))
        db.flush()
        rows = db.query(UserSurvey).filter_by(user_id=user.id).all()
        assert len(rows) == 2

    def test_cascade_delete(self, db, user):
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=1,
            q_loss_sensitivity=1, q_trading_frequency=1, q_holding_behavior=1,
        ))
        db.flush()
        db.delete(user)
        db.flush()
        assert db.query(UserSurvey).filter_by(user_id=user.id).first() is None

    def test_user_survey_relationship(self, db, user):
        survey = UserSurvey(
            user_id=user.id, q_risk_tolerance=5,
            q_loss_sensitivity=5, q_trading_frequency=5, q_holding_behavior=5,
        )
        db.add(survey)
        db.flush()
        # Access via relationship
        assert user.survey is not None
        assert user.survey.q_risk_tolerance == 5

    def test_no_survey_returns_none(self, db, user):
        assert user.survey is None


class TestSurveyExport:
    """Verify export functions include survey data."""

    def test_export_user_history_includes_survey(self, db, user):
        from modules.utils.export import export_user_history_csv
        # Add a survey
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=4,
            q_loss_sensitivity=2, q_trading_frequency=3, q_holding_behavior=5,
        ))
        db.flush()
        rows = export_user_history_csv(db, user.id)
        # No sessions yet, so rows is empty — but function should not crash
        assert isinstance(rows, list)

    def test_export_session_data_includes_survey_file(self, db, user, tmp_path):
        from modules.utils.export import export_session_data
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=2,
            q_loss_sensitivity=4, q_trading_frequency=1, q_holding_behavior=3,
        ))
        db.flush()
        files = export_session_data(db, user.id, "fake-session-id", tmp_path)
        survey_files = [f for f in files if "survey_" in f.name]
        assert len(survey_files) == 1
