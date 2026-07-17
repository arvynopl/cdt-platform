"""
modules/cdt/snapshot.py — CDT state persistence after each session.

Saves a CdtSnapshot record capturing the full CognitiveProfile state at the
end of each simulation session, enabling longitudinal CDT analysis in Bab VI.

Functions:
    save_cdt_snapshot — Persist a point-in-time CDT state snapshot to the DB.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.models import CdtSnapshot, CognitiveProfile

logger = logging.getLogger(__name__)


def save_cdt_snapshot(
    db_session: Session,
    user_id: int,
    session_id: str,
    profile: CognitiveProfile,
) -> CdtSnapshot:
    """Persist the current CognitiveProfile state as a CdtSnapshot.

    Call this immediately after update_profile() so the snapshot captures
    the post-session EMA state.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.
        session_id: UUID string of the just-completed session.
        profile:    The updated CognitiveProfile instance.

    Returns:
        The persisted CdtSnapshot ORM instance.
    """
    biv = profile.bias_intensity_vector or {}
    snapshot = CdtSnapshot(
        user_id=user_id,
        session_id=session_id,
        session_number=profile.session_count,
        cdt_overconfidence=biv.get("overconfidence", 0.0),
        cdt_disposition=biv.get("disposition", 0.0),
        cdt_loss_aversion=biv.get("loss_aversion", 0.0),
        cdt_risk_preference=profile.risk_preference,
        cdt_stability_index=profile.stability_index,
        snapshotted_at=datetime.now(UTC),
    )
    db_session.add(snapshot)
    db_session.flush()
    logger.debug(
        "CdtSnapshot saved: user=%s session=%s #=%d OC=%.3f DISP=%.3f LA=%.3f",
        user_id, session_id[:8], profile.session_count,
        snapshot.cdt_overconfidence, snapshot.cdt_disposition, snapshot.cdt_loss_aversion,
    )
    return snapshot
