"""app/services/simulation.py — stateless simulation orchestration for the API.

Port of the Streamlit-era session lifecycle (modules/simulation/ui.py) onto a
request/response model. The server holds no in-memory session state: every
request reconstructs what it needs from the database, which is what makes the
backend horizontally scalable (audit F2) and crash-safe (the old NFR02
"all-or-nothing" property now falls out of one transaction per request).

Key differences from the Streamlit implementation, by design:
  * One request = one transaction. A round's 12 UserAction rows are inserted
    by a single commit (audit F1: 1 network round-trip instead of 12).
  * The post-session pipeline runs as a FastAPI background task after the
    final round's response is sent; clients poll ``analysis_status`` which
    derives truth from the database (BiasMetric row ⇔ pipeline committed) —
    the same DB-truth pattern the thesis build used.
  * Window selection excludes the user's previously played start dates
    (audit F14).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from config import INITIAL_CAPITAL, ROUNDS_PER_SESSION
from database.connection import get_session
from database.models import (
    BiasMetric,
    FeedbackHistory,
    SessionSummary,
    UserAction,
)
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.logger import log_action
from modules.logging_engine.validator import validate_session_completeness
from modules.simulation.engine import SimulationEngine
from modules.simulation.portfolio import Portfolio
from modules.utils.export import log_session_error

logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """Domain-level error with a user-facing Bahasa Indonesia message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_window(engine: SimulationEngine) -> dict[str, list[dict]]:
    return {
        sid: [
            {
                "id": snap.id,
                "date": snap.date.isoformat(),
                "open": snap.open,
                "high": snap.high,
                "low": snap.low,
                "close": snap.close,
                "volume": snap.volume,
                "ma_5": snap.ma_5,
                "ma_20": snap.ma_20,
                "rsi_14": snap.rsi_14,
                "trend": snap.trend,
                "daily_return": snap.daily_return,
            }
            for snap in snaps
        ]
        for sid, snaps in engine._window.items()
    }


def _serialize_portfolio(
    portfolio: Portfolio, current_prices: dict[str, float]
) -> dict:
    return {
        "cash": portfolio.cash,
        "total_value": portfolio.get_total_value(current_prices),
        "realized_pnl": portfolio.get_realized_pnl(),
        "holdings": [
            {
                "stock_id": pos.stock_id,
                "quantity": pos.quantity,
                "avg_price": pos.avg_purchase_price,
                "current_price": current_prices.get(
                    pos.stock_id, pos.avg_purchase_price
                ),
            }
            for pos in portfolio.holdings.values()
        ],
        "sold_trade_count": len(portfolio.get_sold_trades()),
    }


def _replay_portfolio(
    db: Session, session_id: str, window: dict[str, list[dict]]
) -> tuple[Portfolio, int]:
    """Rebuild the Portfolio from logged actions; return (portfolio, next_round).

    Mirrors the thesis build's ``_replay_actions_into_portfolio`` semantics:
    invalid replay steps are skipped (they cannot occur for actions that were
    validated at write time), and next_round is one past the last logged round.
    """
    snap_price = {
        snap["id"]: snap["close"] for snaps in window.values() for snap in snaps
    }
    portfolio = Portfolio(initial_capital=INITIAL_CAPITAL)
    actions = (
        db.query(UserAction)
        .filter_by(session_id=session_id)
        .order_by(UserAction.scenario_round.asc(), UserAction.id.asc())
        .all()
    )
    last_round = 0
    for action in actions:
        price = snap_price.get(action.snapshot_id)
        if price is None:
            continue
        try:
            if action.action_type == "buy" and action.quantity > 0:
                portfolio.buy(action.stock_id, action.quantity, price, action.scenario_round)
            elif action.action_type == "sell" and action.quantity > 0:
                portfolio.sell(action.stock_id, action.quantity, price, action.scenario_round)
        except ValueError:
            logger.exception(
                "session=%s replay rejected at round %s for %s",
                session_id, action.scenario_round, action.stock_id,
            )
        last_round = max(last_round, action.scenario_round)
    return portfolio, last_round + 1


def _load_engine(db: Session, summary: SessionSummary) -> SimulationEngine:
    if summary.window_start_date is None:
        raise SimulationError(
            "Sesi tidak memiliki jendela data. Mulai sesi baru.", status_code=409
        )
    return SimulationEngine(
        user_id=summary.user_id,
        session_id=summary.session_id,
        db_session=db,
        start_date=summary.window_start_date,
    )


def _get_owned_summary(
    db: Session, user_id: int, session_id: str
) -> SessionSummary:
    summary = (
        db.query(SessionSummary)
        .filter_by(session_id=session_id, user_id=user_id)
        .first()
    )
    if summary is None:
        raise SimulationError("Sesi tidak ditemukan.", status_code=404)
    return summary


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_or_resume_session(db: Session, user_id: int) -> dict:
    """Resume the user's in-progress session, or start a fresh one.

    A fresh session picks a window the user has not played before (F14) and
    inserts the SessionSummary row up front so a mid-session crash always
    leaves a resumable trail.
    """
    existing = (
        db.query(SessionSummary)
        .filter_by(user_id=user_id, status="in_progress")
        .order_by(SessionSummary.started_at.desc())
        .first()
    )

    if existing is not None:
        engine = _load_engine(db, existing)
        window = _serialize_window(engine)
        portfolio, next_round = _replay_portfolio(db, existing.session_id, window)
        summary = existing
        resumed = True
    else:
        session_id = str(uuid.uuid4())
        played = (
            db.query(SessionSummary.window_start_date)
            .filter(
                SessionSummary.user_id == user_id,
                SessionSummary.window_start_date.isnot(None),
            )
            .all()
        )
        engine = SimulationEngine(
            user_id=user_id,
            session_id=session_id,
            db_session=db,
            exclude_start_dates={row[0] for row in played},
        )
        meta = engine.get_window_metadata()
        summary = SessionSummary(
            user_id=user_id,
            session_id=session_id,
            started_at=datetime.now(UTC),
            status="in_progress",
            window_start_date=meta["start_date"],
            window_end_date=meta["end_date"],
        )
        db.add(summary)
        db.flush()
        window = _serialize_window(engine)
        portfolio, next_round = Portfolio(initial_capital=INITIAL_CAPITAL), 1
        resumed = False

    # Both branches above guarantee window dates (resume validates them,
    # fresh sessions write them); encode that invariant for the type checker.
    assert summary.window_start_date is not None
    assert summary.window_end_date is not None

    round_idx = min(next_round, ROUNDS_PER_SESSION) - 1
    current_prices = {
        sid: snaps[round_idx]["close"] for sid, snaps in window.items()
    }
    return {
        "session_id": summary.session_id,
        "resumed": resumed,
        "current_round": next_round,
        "rounds_total": ROUNDS_PER_SESSION,
        "rounds_complete": next_round > ROUNDS_PER_SESSION,
        "window_start_date": summary.window_start_date.isoformat(),
        "window_end_date": summary.window_end_date.isoformat(),
        "stock_ids": engine.stock_ids,
        "window": window,
        "pre_window_history": {
            sid: [
                {**row, "date": row["date"].isoformat()}
                for row in rows
            ]
            for sid, rows in engine.get_pre_window_history().items()
        },
        "portfolio": _serialize_portfolio(portfolio, current_prices),
    }


def submit_round(
    db: Session,
    user_id: int,
    session_id: str,
    round_number: int,
    orders: list[dict],
    response_time_ms: int,
) -> dict:
    """Validate and persist one round's decisions in a single transaction.

    Mirrors the thesis build's ``_execute_round``: orders are applied to the
    replayed portfolio; an order the portfolio rejects (insufficient cash /
    holdings) degrades to "hold" and its message is returned in ``errors`` —
    the round always completes. Stocks without an order get the auto-hold row,
    so completeness stays ≥ 95% by construction (FR01).
    """
    summary = _get_owned_summary(db, user_id, session_id)
    if summary.status != "in_progress":
        raise SimulationError(
            f"Sesi berstatus {summary.status!r}; tidak menerima putaran baru.",
            status_code=409,
        )

    engine = _load_engine(db, summary)
    window = _serialize_window(engine)
    portfolio, expected_round = _replay_portfolio(db, session_id, window)

    if expected_round > ROUNDS_PER_SESSION:
        raise SimulationError("Semua putaran sudah selesai.", status_code=409)
    if round_number != expected_round:
        raise SimulationError(
            f"Putaran tidak sesuai: berikutnya adalah putaran {expected_round}.",
            status_code=409,
        )

    by_stock: dict[str, dict] = {}
    for order in orders:
        sid = order["stock_id"]
        if sid not in window:
            raise SimulationError(f"Saham {sid!r} tidak ada dalam sesi ini.")
        if sid in by_stock:
            raise SimulationError(f"Order ganda untuk saham {sid!r}.")
        by_stock[sid] = order

    errors: list[str] = []
    for sid in engine.stock_ids:
        snap = window[sid][round_number - 1]
        price = snap["close"]
        atype, qty = "hold", 0
        if sid in by_stock:
            requested = by_stock[sid]
            r_type, r_qty = requested["action"], int(requested["quantity"])
            try:
                if r_type == "buy" and r_qty > 0:
                    portfolio.buy(sid, r_qty, price, round_number)
                    atype, qty = "buy", r_qty
                elif r_type == "sell" and r_qty > 0:
                    portfolio.sell(sid, r_qty, price, round_number)
                    atype, qty = "sell", r_qty
            except ValueError as exc:
                errors.append(str(exc))

        log_action(
            session=db,
            user_id=user_id,
            session_id=session_id,
            scenario_round=round_number,
            stock_id=sid,
            snapshot_id=snap["id"],
            action_type=atype,
            quantity=qty,
            action_value=qty * price if qty else 0.0,
            response_time_ms=response_time_ms,
        )

    summary.rounds_completed = round_number
    db.flush()

    next_round = round_number + 1
    completed = next_round > ROUNDS_PER_SESSION
    round_idx = min(next_round, ROUNDS_PER_SESSION) - 1
    current_prices = {
        sid: snaps[round_idx]["close"] for sid, snaps in window.items()
    }
    return {
        "session_id": session_id,
        "round_number": round_number,
        "errors": errors,
        "next_round": next_round,
        "rounds_complete": completed,
        "portfolio": _serialize_portfolio(portfolio, current_prices),
    }


def abandon_session(db: Session, user_id: int, session_id: str) -> None:
    summary = _get_owned_summary(db, user_id, session_id)
    if summary.status == "in_progress":
        summary.status = "abandoned"
        summary.completed_at = datetime.now(UTC)
        db.flush()


# ---------------------------------------------------------------------------
# Post-session analytics pipeline (background task)
# ---------------------------------------------------------------------------

def run_post_session_pipeline(user_id: int, session_id: str) -> None:
    """Analytics → CDT update → feedback, in one transaction of its own.

    Runs as a FastAPI background task after the final round's response.
    Failure marks the session "error" and persists a SessionError row —
    the client's status poll then offers a retry (same recovery contract as
    the thesis build, minus the Streamlit rerun gymnastics).
    """
    try:
        with get_session() as sess:
            completeness = validate_session_completeness(sess, user_id, session_id)
            if not completeness["is_complete"]:
                logger.warning(
                    "user=%s session=%s incomplete: %s/%s actions, missing=%s",
                    user_id, session_id,
                    completeness["action_count"], completeness["expected_count"],
                    completeness["missing_rounds"],
                )

            bias_metric = compute_and_save_metrics(sess, user_id, session_id)
            features = extract_session_features(sess, user_id, session_id)
            profile = update_profile(sess, user_id, bias_metric, session_id)
            generate_feedback(
                db_session=sess,
                user_id=user_id,
                session_id=session_id,
                bias_metric=bias_metric,
                profile=profile,
                realized_trades=features.realized_trades,
                open_positions=features.open_positions,
            )
            summary = (
                sess.query(SessionSummary)
                .filter_by(session_id=session_id)
                .first()
            )
            if summary:
                summary.status = "completed"
                summary.completed_at = datetime.now(UTC)
                summary.rounds_completed = ROUNDS_PER_SESSION
                summary.final_portfolio_value = features.final_value
    except Exception as exc:
        logger.exception(
            "user=%s session=%s post-session pipeline failed", user_id, session_id
        )
        try:
            with get_session() as err_sess:
                summary = (
                    err_sess.query(SessionSummary)
                    .filter_by(session_id=session_id)
                    .first()
                )
                if summary and summary.status != "completed":
                    summary.status = "error"
                    summary.completed_at = datetime.now(UTC)
                log_session_error(
                    err_sess,
                    user_id=user_id,
                    session_id=session_id,
                    error_type=type(exc).__name__[:64],
                    message=str(exc)[:2000],
                )
        except Exception:
            logger.exception(
                "user=%s session=%s failed to record pipeline error",
                user_id, session_id,
            )


def analysis_status(db: Session, user_id: int, session_id: str) -> dict:
    """DB-truth status: a BiasMetric row exists iff the pipeline committed."""
    summary = _get_owned_summary(db, user_id, session_id)
    metric_exists = (
        db.query(BiasMetric)
        .filter_by(user_id=user_id, session_id=session_id)
        .first()
        is not None
    )
    if metric_exists:
        status = "completed"
    elif summary.status == "error":
        status = "error"
    elif (summary.rounds_completed or 0) >= ROUNDS_PER_SESSION:
        status = "processing"
    else:
        status = "in_progress"
    return {
        "session_id": session_id,
        "status": status,
        "rounds_completed": summary.rounds_completed or 0,
        "rounds_total": ROUNDS_PER_SESSION,
    }


def session_results(db: Session, user_id: int, session_id: str) -> dict:
    """Metric + delivered feedback for a completed session."""
    summary = _get_owned_summary(db, user_id, session_id)
    metric = (
        db.query(BiasMetric)
        .filter_by(user_id=user_id, session_id=session_id)
        .first()
    )
    if metric is None:
        raise SimulationError(
            "Analisis sesi belum tersedia.", status_code=409
        )
    feedback_rows = (
        db.query(FeedbackHistory)
        .filter_by(user_id=user_id, session_id=session_id)
        .order_by(FeedbackHistory.bias_type)
        .all()
    )
    return {
        "session_id": session_id,
        "final_portfolio_value": summary.final_portfolio_value,
        "initial_capital": INITIAL_CAPITAL,
        "metric": {
            "overconfidence_score": metric.overconfidence_score,
            "disposition_pgr": metric.disposition_pgr,
            "disposition_plr": metric.disposition_plr,
            "disposition_dei": metric.disposition_dei,
            "loss_aversion_index": metric.loss_aversion_index,
            "dei_ci": [metric.dei_ci_lower, metric.dei_ci_upper],
            "ocs_ci": [metric.ocs_ci_lower, metric.ocs_ci_upper],
            "lai_ci": [metric.lai_ci_lower, metric.lai_ci_upper],
            "ci_low_confidence": bool(metric.ci_low_confidence),
        },
        "feedback": [
            {
                "bias_type": f.bias_type,
                "severity": f.severity,
                "explanation_text": f.explanation_text,
                "recommendation_text": f.recommendation_text,
            }
            for f in feedback_rows
        ],
    }
