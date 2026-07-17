"""
modules/logging_engine/logger.py — Persist user decisions to the database.

Functions:
    log_action  — Write a buy/sell/hold UserAction row.
    log_hold    — Convenience wrapper for hold actions.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.models import UserAction

logger = logging.getLogger(__name__)


_VALID_ACTIONS = {"buy", "sell", "hold"}


def log_action(
    session: Session,
    user_id: int,
    session_id: str,
    scenario_round: int,
    stock_id: str,
    snapshot_id: int,
    action_type: str,
    quantity: int,
    action_value: float,
    response_time_ms: int,
) -> UserAction:
    """Create and persist a UserAction record.

    Args:
        session:          Active SQLAlchemy session.
        user_id:          ID of the acting user.
        session_id:       UUID string for the simulation session.
        scenario_round:   Round number (1–14).
        stock_id:         StockCatalog.stock_id (e.g. "BBCA.JK").
        snapshot_id:      MarketSnapshot.id for this round/stock.
        action_type:      "buy", "sell", or "hold".
        quantity:         Number of shares (0 for hold).
        action_value:     Total transaction value in IDR (0 for hold).
        response_time_ms: Milliseconds from round display to submission.

    Returns:
        The persisted UserAction instance.

    Raises:
        ValueError: for invalid action_type, negative quantity or response time.
    """
    if action_type not in _VALID_ACTIONS:
        raise ValueError(
            f"action_type must be one of {_VALID_ACTIONS}, got {action_type!r}."
        )
    if quantity < 0:
        raise ValueError(f"quantity must be ≥ 0, got {quantity}.")
    if response_time_ms < 0:
        raise ValueError(f"response_time_ms must be ≥ 0, got {response_time_ms}.")

    action = UserAction(
        user_id=user_id,
        session_id=session_id,
        scenario_round=scenario_round,
        stock_id=stock_id,
        snapshot_id=snapshot_id,
        action_type=action_type,
        quantity=quantity,
        action_value=action_value,
        response_time_ms=response_time_ms,
        timestamp=datetime.now(UTC),
    )
    session.add(action)
    session.flush()   # Assign id without committing the outer transaction
    return action


def log_hold(
    session: Session,
    user_id: int,
    session_id: str,
    scenario_round: int,
    stock_id: str,
    snapshot_id: int,
    response_time_ms: int,
) -> UserAction:
    """Convenience wrapper that logs a hold action (quantity=0, value=0).

    Args:
        session:          Active SQLAlchemy session.
        user_id:          ID of the acting user.
        session_id:       UUID string for the simulation session.
        scenario_round:   Round number (1–14).
        stock_id:         StockCatalog.stock_id.
        snapshot_id:      MarketSnapshot.id for this round/stock.
        response_time_ms: Milliseconds from round display to submission.

    Returns:
        The persisted UserAction instance.
    """
    return log_action(
        session=session,
        user_id=user_id,
        session_id=session_id,
        scenario_round=scenario_round,
        stock_id=stock_id,
        snapshot_id=snapshot_id,
        action_type="hold",
        quantity=0,
        action_value=0.0,
        response_time_ms=response_time_ms,
    )
