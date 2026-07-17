"""
tests/test_v5_features.py — Tests for V5 features:
  - Cross-bias interaction scores (N-01)
  - Isolation Forest ML validation (N-02)
  - Post-session survey model (N-03)
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, BiasMetric, PostSessionSurvey, User
from modules.cdt.interaction import _pearson, compute_interaction_scores

# ---------------------------------------------------------------------------
# Shared fixture
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
    u = User(alias="v5_test_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _add_metric(db, user_id, ocs, dei, lai):
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
# N-01: Cross-bias interaction scores
# ---------------------------------------------------------------------------

class TestPearsonHelper:
    def test_perfect_positive_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = _pearson(xs, ys)
        assert r == pytest.approx(1.0)

    def test_perfect_negative_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        r = _pearson(xs, ys)
        assert r == pytest.approx(-1.0)

    def test_zero_variance_returns_none(self):
        xs = [1.0, 1.0, 1.0]
        ys = [1.0, 2.0, 3.0]
        assert _pearson(xs, ys) is None

    def test_single_element_returns_none(self):
        assert _pearson([1.0], [1.0]) is None


class TestComputeInteractionScores:
    def test_returns_none_below_min_sessions(self, db, user):
        for _ in range(2):
            _add_metric(db, user.id, ocs=0.5, dei=0.3, lai=1.5)
        result = compute_interaction_scores(db, user.id)
        assert result is None

    def test_returns_dict_with_three_sessions(self, db, user):
        for i in range(3):
            _add_metric(db, user.id, ocs=0.3 * (i + 1), dei=0.1 * i, lai=1.0)
        result = compute_interaction_scores(db, user.id)
        assert result is not None
        assert set(result.keys()) == {"ocs_dei", "ocs_lai", "dei_lai"}

    def test_correlated_ocs_lai_detected(self, db, user):
        """Sessions where OCS and LAI rise together → positive ocs_lai correlation."""
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _add_metric(db, user.id, ocs=v, dei=0.1, lai=v * 3)
        result = compute_interaction_scores(db, user.id)
        assert result["ocs_lai"] is not None
        assert result["ocs_lai"] > 0.8, (
            f"Expected strong positive ocs_lai correlation, got {result['ocs_lai']:.4f}"
        )

    def test_all_none_when_constant_bias(self, db, user):
        """Zero-variance series → all correlations return None."""
        for _ in range(5):
            _add_metric(db, user.id, ocs=0.5, dei=0.3, lai=1.5)
        result = compute_interaction_scores(db, user.id)
        # All series are constant → all correlations undefined
        assert result is not None  # dict is returned, but values are None
        assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# N-02: Isolation Forest (graceful degradation only; full test requires sklearn)
# ---------------------------------------------------------------------------

class TestMLValidator:
    def test_returns_none_below_min_sessions(self, db, user):
        from modules.cdt.ml_validator import compute_anomaly_flags
        for _ in range(3):
            _add_metric(db, user.id, ocs=0.5, dei=0.3, lai=1.5)
        result = compute_anomaly_flags(db, user.id)
        assert result is None

    def test_returns_result_with_five_sessions_if_sklearn_available(self, db, user):
        """If sklearn is installed, returns structured dict with 5 sessions."""
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pytest.skip("scikit-learn not installed")

        from modules.cdt.ml_validator import compute_anomaly_flags
        for i in range(5):
            _add_metric(db, user.id, ocs=0.2 * i, dei=0.1, lai=1.0)
        result = compute_anomaly_flags(db, user.id)
        assert result is not None
        assert result["n_sessions"] == 5
        assert len(result["session_ids"]) == 5
        assert len(result["anomaly_scores"]) == 5
        assert len(result["is_anomaly"]) == 5

    def test_returns_none_gracefully_when_sklearn_missing(self, db, user, monkeypatch):
        """Simulate sklearn ImportError → function returns None without raising."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sklearn.ensemble":
                raise ImportError("sklearn not available (mocked)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from modules.cdt.ml_validator import compute_anomaly_flags
        for i in range(6):
            _add_metric(db, user.id, ocs=0.1 * i, dei=0.0, lai=1.0)

        # Should not raise, should return None
        result = compute_anomaly_flags(db, user.id)
        assert result is None


# ---------------------------------------------------------------------------
# N-03: Post-session survey model
# ---------------------------------------------------------------------------

class TestPostSessionSurvey:
    def test_can_create_survey_record(self, db, user):
        sid = str(uuid.uuid4())
        survey = PostSessionSurvey(
            user_id=user.id,
            session_id=sid,
            self_overconfidence=3,
            self_disposition=4,
            self_loss_aversion=2,
            feedback_usefulness=5,
        )
        db.add(survey)
        db.flush()
        loaded = db.query(PostSessionSurvey).filter_by(user_id=user.id).first()
        assert loaded is not None
        assert loaded.self_overconfidence == 3
        assert loaded.self_disposition == 4
        assert loaded.self_loss_aversion == 2
        assert loaded.feedback_usefulness == 5

    def test_unique_constraint_per_user_session(self, db, user):
        """Cannot submit two surveys for the same user+session."""
        from sqlalchemy.exc import IntegrityError
        sid = str(uuid.uuid4())
        db.add(PostSessionSurvey(
            user_id=user.id, session_id=sid,
            self_overconfidence=3, self_disposition=3,
            self_loss_aversion=3, feedback_usefulness=3,
        ))
        db.flush()
        db.add(PostSessionSurvey(
            user_id=user.id, session_id=sid,
            self_overconfidence=4, self_disposition=4,
            self_loss_aversion=4, feedback_usefulness=4,
        ))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_different_sessions_allowed(self, db, user):
        """Same user can submit surveys for different sessions."""
        for _ in range(3):
            db.add(PostSessionSurvey(
                user_id=user.id, session_id=str(uuid.uuid4()),
                self_overconfidence=3, self_disposition=3,
                self_loss_aversion=3, feedback_usefulness=4,
            ))
        db.flush()
        count = db.query(PostSessionSurvey).filter_by(user_id=user.id).count()
        assert count == 3
