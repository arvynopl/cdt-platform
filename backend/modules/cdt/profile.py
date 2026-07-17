"""
modules/cdt/profile.py — CognitiveProfile CRUD helpers.

Functions:
    compute_survey_priors  — Convert UserSurvey Likert responses to damped initial priors.
    get_or_create_profile  — Fetch or initialise a user's CDT profile.
    get_profile            — Fetch (or None) for read-only access.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from config import SURVEY_PRIOR_WEIGHT
from database.models import CognitiveProfile, UserSurvey

logger = logging.getLogger(__name__)


def compute_survey_priors(survey: UserSurvey) -> dict:
    """Convert Likert 1-5 survey responses to damped initial bias_intensity_vector.

    Normalization: (q - 1) / 4.0  →  1→0.0, 5→1.0
    Damping: multiply normalized value by SURVEY_PRIOR_WEIGHT (default 0.15)

    Mapping:
        overconfidence ← average of q_risk_tolerance and q_trading_frequency
        disposition    ← q_holding_behavior
        loss_aversion  ← q_loss_sensitivity

    Args:
        survey: UserSurvey ORM instance with Likert 1-5 responses.

    Returns:
        dict with keys "overconfidence", "disposition", "loss_aversion".
    """
    norm_risk = (survey.q_risk_tolerance - 1) / 4.0
    norm_freq = (survey.q_trading_frequency - 1) / 4.0
    norm_hold = (survey.q_holding_behavior - 1) / 4.0
    norm_loss = (survey.q_loss_sensitivity - 1) / 4.0

    return {
        "overconfidence": ((norm_risk + norm_freq) / 2.0) * SURVEY_PRIOR_WEIGHT,
        "disposition":    norm_hold * SURVEY_PRIOR_WEIGHT,
        "loss_aversion":  norm_loss * SURVEY_PRIOR_WEIGHT,
    }


def get_or_create_profile(db_session: Session, user_id: int) -> CognitiveProfile:
    """Return the CognitiveProfile for *user_id*, creating a default one if absent.

    If a UserSurvey exists for the user, the initial bias_intensity_vector is
    set via compute_survey_priors() with SURVEY_PRIOR_WEIGHT damping.
    Otherwise, all bias intensities default to 0.0.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.

    Returns:
        CognitiveProfile ORM instance (already added to session but not committed).
    """
    profile = (
        db_session.query(CognitiveProfile)
        .filter_by(user_id=user_id)
        .first()
    )
    if profile is None:
        survey = db_session.query(UserSurvey).filter_by(user_id=user_id).first()
        if survey is not None:
            initial_vector = compute_survey_priors(survey)
            logger.info(
                "Initialising profile for user %d with survey priors %s",
                user_id,
                initial_vector,
            )
        else:
            initial_vector = {"overconfidence": 0.0, "disposition": 0.0, "loss_aversion": 0.0}
            logger.info(
                "Initialising profile for user %d with zero priors (no survey)",
                user_id,
            )
        profile = CognitiveProfile(
            user_id=user_id,
            bias_intensity_vector=initial_vector,
            risk_preference=0.0,
            stability_index=0.0,
            session_count=0,
        )
        db_session.add(profile)
        db_session.flush()
    return profile


def get_profile(db_session: Session, user_id: int) -> CognitiveProfile | None:
    """Return the CognitiveProfile for *user_id*, or None if it does not exist.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.

    Returns:
        CognitiveProfile instance or None.
    """
    return (
        db_session.query(CognitiveProfile)
        .filter_by(user_id=user_id)
        .first()
    )
