"""
modules/cdt/updater.py — EMA-based CognitiveProfile update logic.

After each simulation session the profile is updated using Exponential Moving
Averages (EMA) so that recent sessions carry more weight than older ones.

Functions:
    update_profile — Apply one EMA step and persist the updated profile.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from config import (
    ALPHA,
    ALPHA_MAX,
    BETA,
    HIGH_VOLATILITY_CLASSES,
    LAI_EMA_CEILING,
    ROUNDS_PER_SESSION,
)
from database.models import BiasMetric, CognitiveProfile, StockCatalog, UserAction
from modules.cdt.interaction import compute_interaction_scores
from modules.cdt.profile import get_or_create_profile
from modules.cdt.snapshot import save_cdt_snapshot
from modules.cdt.stability import compute_stability_index

logger = logging.getLogger(__name__)


def update_profile(
    db_session: Session,
    user_id: int,
    bias_metric: BiasMetric,
    session_id: str,
) -> CognitiveProfile:
    """Apply one EMA step to the user's CognitiveProfile using fresh bias metrics.

    EMA update rules (ALPHA=0.3 base, ALPHA_MAX=0.45 ceiling, BETA=0.2):

        session_activity  = min(buy_sell_count / ROUNDS_PER_SESSION, 1.0)
        effective_alpha   = ALPHA + (ALPHA_MAX − ALPHA) × session_activity

        new_overconfidence = effective_alpha × OCS  + (1 − effective_alpha) × old_overconfidence
        new_disposition    = effective_alpha × |DEI| + (1 − effective_alpha) × old_disposition
        new_loss_aversion  = effective_alpha × min(LAI/LAI_EMA_CEILING, 1)
                             + (1 − effective_alpha) × old_loss_aversion

        observed_risk      = high_vol_trades / max(total_buy_sell_trades, 1)
        # Note: only HIGH_VOLATILITY_CLASSES trades count toward high_vol_count.
        # Trades in "medium" or lower volatility stocks contribute 0 to observed_risk.
        new_risk_pref      = BETA × observed_risk + (1 − BETA) × old_risk_pref

    Args:
        db_session:   Active SQLAlchemy session.
        user_id:      ID of the user to update.
        bias_metric:  BiasMetric computed for the just-completed session.
        session_id:   UUID string of the completed session (to query actions).

    Returns:
        The updated and flushed CognitiveProfile instance.
    """
    profile = get_or_create_profile(db_session, user_id)
    old = dict(profile.bias_intensity_vector)  # copy to avoid mutation issues

    # --- Risk preference EMA update (needed first to get action counts for adaptive alpha) ---
    actions = (
        db_session.query(UserAction)
        .filter_by(user_id=user_id, session_id=session_id)
        .filter(UserAction.action_type.in_(["buy", "sell"]))
        .all()
    )

    high_vol_count = 0
    total_count = len(actions)
    # Batch-fetch all StockCatalog rows needed (eliminates N+1 queries)
    stock_ids_set = {a.stock_id for a in actions}
    stocks_map = {
        s.stock_id: s
        for s in db_session.query(StockCatalog)
        .filter(StockCatalog.stock_id.in_(stock_ids_set))
        .all()
    }
    for action in actions:
        stock = stocks_map.get(action.stock_id)
        if stock and stock.volatility_class in HIGH_VOLATILITY_CLASSES:
            high_vol_count += 1

    observed_risk = high_vol_count / max(total_count, 1)
    profile.risk_preference = BETA * observed_risk + (1 - BETA) * profile.risk_preference

    # --- Adaptive alpha: high-activity sessions update the CDT more aggressively ---
    # Zero-activity sessions use ALPHA unchanged (backward-compatible baseline).
    # Fully-active sessions (buy/sell every round) use ALPHA_MAX.
    session_activity = min(total_count / max(ROUNDS_PER_SESSION, 1), 1.0)
    effective_alpha = ALPHA + (ALPHA_MAX - ALPHA) * session_activity

    # --- Bias intensity EMA update ---
    new_oc = effective_alpha * (bias_metric.overconfidence_score or 0.0) + (1 - effective_alpha) * old.get("overconfidence", 0.0)
    new_disp = effective_alpha * abs(bias_metric.disposition_dei or 0.0) + (1 - effective_alpha) * old.get("disposition", 0.0)
    new_la = (
        effective_alpha * min((bias_metric.loss_aversion_index or 0.0) / LAI_EMA_CEILING, 1.0)
        + (1 - effective_alpha) * old.get("loss_aversion", 0.0)
    )

    profile.bias_intensity_vector = {
        "overconfidence": new_oc,
        "disposition": new_disp,
        "loss_aversion": new_la,
    }
    logger.debug(
        "user=%s EMA update (α=%.3f activity=%.2f): OC %.3f→%.3f  DISP %.3f→%.3f  LA %.3f→%.3f",
        user_id, effective_alpha, session_activity,
        old.get("overconfidence", 0.0), new_oc,
        old.get("disposition", 0.0), new_disp,
        old.get("loss_aversion", 0.0), new_la,
    )

    # --- Session count, stability, and cross-bias interaction scores ---
    profile.session_count += 1
    profile.stability_index = compute_stability_index(db_session, user_id)
    profile.interaction_scores = compute_interaction_scores(db_session, user_id)
    profile.last_updated_at = datetime.now(UTC)

    db_session.flush()
    save_cdt_snapshot(db_session, user_id, session_id, profile)
    return profile
