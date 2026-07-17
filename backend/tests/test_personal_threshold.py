"""tests/test_personal_threshold.py — personal watchpoint (μ + σ) computations."""

import math
from datetime import UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import LAI_EMA_CEILING
from database.models import Base, BiasMetric, User
from modules.analytics.personal_baseline import (
    MIN_SESSIONS_FOR_PERSONAL,
    compute_personal_threshold,
    compute_personal_thresholds,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def _seed_metrics(session, user_id: int, dei_vals, ocs_vals, lai_vals):
    from datetime import datetime, timedelta
    base = datetime.now(UTC) - timedelta(hours=len(dei_vals))
    for i, (dei, ocs, lai) in enumerate(zip(dei_vals, ocs_vals, lai_vals)):
        session.add(BiasMetric(
            user_id=user_id,
            session_id=f"s-{i}",
            overconfidence_score=ocs,
            disposition_dei=dei,
            loss_aversion_index=lai,
            computed_at=base + timedelta(hours=i),
        ))
    session.flush()


def test_compute_personal_threshold_returns_mu_plus_sigma(session):
    u = User(alias="pers_user", experience_level="beginner")
    session.add(u)
    session.flush()
    dei = [0.1, 0.2, 0.3, 0.4, 0.5]
    ocs = [0.2, 0.3, 0.4, 0.5, 0.6]
    lai = [1.0, 1.2, 1.4, 1.6, 1.8]  # raw LAI; will be normalised

    _seed_metrics(session, u.id, dei, ocs, lai)
    session.commit()

    mu_dei = sum(dei) / len(dei)
    sd_dei = math.sqrt(sum((x - mu_dei) ** 2 for x in dei) / (len(dei) - 1))
    assert compute_personal_threshold(session, u.id, "dei") == pytest.approx(
        max(0.0, min(1.0, mu_dei + sd_dei))
    )

    lai_norm = [min(v / LAI_EMA_CEILING, 1.0) for v in lai]
    mu_lai = sum(lai_norm) / len(lai_norm)
    sd_lai = math.sqrt(sum((x - mu_lai) ** 2 for x in lai_norm) / (len(lai_norm) - 1))
    assert compute_personal_threshold(session, u.id, "lai") == pytest.approx(
        max(0.0, min(1.0, mu_lai + sd_lai))
    )


def test_personal_threshold_none_when_insufficient(session):
    u = User(alias="pers_user2", experience_level="beginner")
    session.add(u)
    session.flush()
    _seed_metrics(session, u.id, [0.1, 0.2], [0.3, 0.4], [1.0, 1.1])
    session.commit()
    assert MIN_SESSIONS_FOR_PERSONAL == 3
    assert compute_personal_threshold(session, u.id, "dei") is None


def test_personal_threshold_rejects_unknown_key(session):
    u = User(alias="pers_user3", experience_level="beginner")
    session.add(u)
    session.flush()
    with pytest.raises(ValueError):
        compute_personal_threshold(session, u.id, "xxx")


def test_compute_personal_thresholds_falls_back_when_too_few():
    metrics = [
        {"dei": 0.1, "ocs": 0.2, "lai_norm": 0.1},
        {"dei": 0.2, "ocs": 0.3, "lai_norm": 0.2},
    ]
    result = compute_personal_thresholds(metrics)
    assert result["is_fallback"] is True
    # values should equal the scientific thresholds in that case
    from modules.analytics.personal_baseline import normalised_scientific_thresholds
    assert result["values"] == normalised_scientific_thresholds()


def test_compute_personal_thresholds_uses_user_data_when_enough():
    metrics = [
        {"dei": 0.1, "ocs": 0.2, "lai_norm": 0.1},
        {"dei": 0.2, "ocs": 0.3, "lai_norm": 0.2},
        {"dei": 0.3, "ocs": 0.4, "lai_norm": 0.3},
    ]
    result = compute_personal_thresholds(metrics)
    assert result["is_fallback"] is False
    # μ+σ for dei = 0.2 + 0.1 = 0.3
    assert result["values"]["dei"] == pytest.approx(0.3)
