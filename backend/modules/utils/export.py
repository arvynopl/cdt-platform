"""
modules/utils/export.py — Session data export helpers for UAT evaluation.

Functions:
    export_session_to_dict   — Serialize one session's metrics + feedback to a dict.
    export_user_history_csv  — Build a CSV-ready list of dicts across all user sessions.
    export_session_data      — Write per-table CSV files for a session to disk.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from database.models import (
    BiasMetric,
    CognitiveProfile,
    FeedbackHistory,
    SessionError,
    SessionSummary,
    UATFeedback,
    UserAction,
    UserSurvey,
)

logger = logging.getLogger(__name__)


def export_session_to_dict(
    db_session: Session, user_id: int, session_id: str
) -> dict:
    """Return a dict with all bias metrics and feedback for one session.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    User whose data to export.
        session_id: UUID string of the target session.

    Returns:
        Dict with keys: session_id, user_id, action_count,
        overconfidence_score, disposition_dei, loss_aversion_index, feedback.
    """
    metric = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id, session_id=session_id)
        .first()
    )
    feedbacks = (
        db_session.query(FeedbackHistory)
        .filter_by(user_id=user_id, session_id=session_id)
        .all()
    )
    action_count = (
        db_session.query(UserAction)
        .filter_by(user_id=user_id, session_id=session_id)
        .count()
    )
    return {
        "session_id": session_id,
        "user_id": user_id,
        "action_count": action_count,
        "overconfidence_score": metric.overconfidence_score if metric else None,
        "disposition_pgr": metric.disposition_pgr if metric else None,
        "disposition_plr": metric.disposition_plr if metric else None,
        "disposition_dei": metric.disposition_dei if metric else None,
        "loss_aversion_index": metric.loss_aversion_index if metric else None,
        "feedback": [
            {
                "bias_type": f.bias_type,
                "severity": f.severity,
                "explanation_text": f.explanation_text,
                "recommendation_text": f.recommendation_text,
            }
            for f in feedbacks
        ],
    }


def export_user_history_csv(
    db_session: Session, user_id: int
) -> list[dict]:
    """Return a list of per-session dicts suitable for CSV export.

    Rows are ordered chronologically (oldest first) and 1-indexed by
    session_num so evaluators can quickly identify session order.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    User whose history to export.

    Returns:
        List of dicts with keys: session_num, session_id, ocs, dei, lai,
        pgr, plr, computed_at.
    """
    metrics = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id)
        .order_by(BiasMetric.computed_at)
        .all()
    )
    survey = (
        db_session.query(UserSurvey)
        .filter_by(user_id=user_id)
        .first()
    )
    rows = []
    for i, m in enumerate(metrics, start=1):
        rows.append({
            "session_num": i,
            "session_id": m.session_id,
            "ocs": m.overconfidence_score,
            "dei": m.disposition_dei,
            "pgr": m.disposition_pgr,
            "plr": m.disposition_plr,
            "lai": m.loss_aversion_index,
            "computed_at": m.computed_at.isoformat() if m.computed_at else None,
            "survey_risk_tolerance": survey.q_risk_tolerance if survey else None,
            "survey_loss_sensitivity": survey.q_loss_sensitivity if survey else None,
            "survey_trading_frequency": survey.q_trading_frequency if survey else None,
            "survey_holding_behavior": survey.q_holding_behavior if survey else None,
        })
    return rows


def export_session_data(
    db_session: Session,
    user_id: int,
    session_id: str,
    output_dir: str | Path,
) -> list[Path]:
    """Write per-table CSV files for a session to disk.

    Exports UserActions, BiasMetrics, FeedbackHistory, and CognitiveProfile
    filtered by user_id + session_id.  One CSV per table.

    Args:
        db_session:  Active SQLAlchemy session.
        user_id:     Filter for this user.
        session_id:  Filter for this session.
        output_dir:  Directory to write CSV files into (created if absent).

    Returns:
        List of Path objects for the files written.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # --- UserActions ---
    actions = (
        db_session.query(UserAction)
        .filter_by(user_id=user_id, session_id=session_id)
        .order_by(UserAction.scenario_round, UserAction.timestamp)
        .all()
    )
    actions_path = output_dir / f"actions_{session_id[:8]}.csv"
    with open(actions_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "scenario_round", "stock_id", "action_type",
                        "quantity", "action_value", "response_time_ms", "timestamp"],
        )
        writer.writeheader()
        for a in actions:
            writer.writerow({
                "id": a.id, "scenario_round": a.scenario_round,
                "stock_id": a.stock_id, "action_type": a.action_type,
                "quantity": a.quantity, "action_value": a.action_value,
                "response_time_ms": a.response_time_ms,
                "timestamp": a.timestamp.isoformat() if a.timestamp else "",
            })
    written.append(actions_path)

    # --- BiasMetrics ---
    metrics = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id, session_id=session_id)
        .all()
    )
    metrics_path = output_dir / f"bias_metrics_{session_id[:8]}.csv"
    with open(metrics_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "session_id", "overconfidence_score",
                        "disposition_pgr", "disposition_plr", "disposition_dei",
                        "loss_aversion_index", "computed_at"],
        )
        writer.writeheader()
        for m in metrics:
            writer.writerow({
                "id": m.id, "session_id": m.session_id,
                "overconfidence_score": m.overconfidence_score,
                "disposition_pgr": m.disposition_pgr,
                "disposition_plr": m.disposition_plr,
                "disposition_dei": m.disposition_dei,
                "loss_aversion_index": m.loss_aversion_index,
                "computed_at": m.computed_at.isoformat() if m.computed_at else "",
            })
    written.append(metrics_path)

    # --- FeedbackHistory ---
    feedbacks = (
        db_session.query(FeedbackHistory)
        .filter_by(user_id=user_id, session_id=session_id)
        .all()
    )
    feedback_path = output_dir / f"feedback_{session_id[:8]}.csv"
    with open(feedback_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "bias_type", "severity",
                        "explanation_text", "recommendation_text", "delivered_at"],
        )
        writer.writeheader()
        for f in feedbacks:
            writer.writerow({
                "id": f.id, "bias_type": f.bias_type, "severity": f.severity,
                "explanation_text": f.explanation_text,
                "recommendation_text": f.recommendation_text,
                "delivered_at": f.delivered_at.isoformat() if f.delivered_at else "",
            })
    written.append(feedback_path)

    # --- CognitiveProfile (user-level, not session-scoped) ---
    profile = (
        db_session.query(CognitiveProfile)
        .filter_by(user_id=user_id)
        .first()
    )
    profile_path = output_dir / f"profile_{user_id}.csv"
    with open(profile_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["user_id", "session_count", "risk_preference",
                        "stability_index", "bias_overconfidence",
                        "bias_disposition", "bias_loss_aversion", "last_updated_at"],
        )
        writer.writeheader()
        if profile:
            bv = profile.bias_intensity_vector or {}
            writer.writerow({
                "user_id": user_id,
                "session_count": profile.session_count,
                "risk_preference": profile.risk_preference,
                "stability_index": profile.stability_index,
                "bias_overconfidence": bv.get("overconfidence"),
                "bias_disposition": bv.get("disposition"),
                "bias_loss_aversion": bv.get("loss_aversion"),
                "last_updated_at": (
                    profile.last_updated_at.isoformat()
                    if profile.last_updated_at else ""
                ),
            })
    written.append(profile_path)

    # --- UserSurvey (user-level, not session-scoped) ---
    survey = (
        db_session.query(UserSurvey)
        .filter_by(user_id=user_id)
        .first()
    )
    survey_path = output_dir / f"survey_{user_id}.csv"
    with open(survey_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["user_id", "q_risk_tolerance", "q_loss_sensitivity",
                        "q_trading_frequency", "q_holding_behavior", "submitted_at"],
        )
        writer.writeheader()
        if survey:
            writer.writerow({
                "user_id": user_id,
                "q_risk_tolerance": survey.q_risk_tolerance,
                "q_loss_sensitivity": survey.q_loss_sensitivity,
                "q_trading_frequency": survey.q_trading_frequency,
                "q_holding_behavior": survey.q_holding_behavior,
                "submitted_at": survey.submitted_at.isoformat() if survey.submitted_at else "",
            })
    written.append(survey_path)

    logger.info(
        "Exported session data for user=%d session=%s to %s (%d files)",
        user_id, session_id[:8], output_dir, len(written),
    )
    return written


def export_uat_summary(db_session: Session) -> list[dict]:
    """Aggregate per-session UAT data: bias metrics, SUS scores, error counts.

    Joins on user_id (and session_id where applicable) so each row represents
    one simulation session enriched with the tester's most recent SUS response
    and the count of session-scoped errors. Designed for post-UAT statistical
    analysis (researcher-only — not exposed to testers).

    Returns:
        List of dicts ordered by user_id then session computed_at.
    """
    metrics = (
        db_session.query(BiasMetric)
        .order_by(BiasMetric.user_id, BiasMetric.computed_at)
        .all()
    )

    rows: list[dict] = []
    for m in metrics:
        # Most recent UAT feedback for this user (SUS scores are user-level, not
        # session-level — testers fill in once after exploring the prototype).
        sus = (
            db_session.query(UATFeedback)
            .filter_by(user_id=m.user_id)
            .order_by(UATFeedback.submitted_at.desc())
            .first()
        )
        summary = (
            db_session.query(SessionSummary)
            .filter_by(user_id=m.user_id, session_id=m.session_id)
            .first()
        )
        error_count = (
            db_session.query(SessionError)
            .filter_by(session_id=m.session_id)
            .count()
        )
        rows.append({
            "user_id": m.user_id,
            "session_id": m.session_id,
            "session_status": summary.status if summary else None,
            "rounds_completed": summary.rounds_completed if summary else None,
            "started_at": summary.started_at.isoformat() if summary and summary.started_at else None,
            "completed_at": (
                summary.completed_at.isoformat()
                if summary and summary.completed_at else None
            ),
            "computed_at": m.computed_at.isoformat() if m.computed_at else None,
            "overconfidence_score": m.overconfidence_score,
            "disposition_pgr": m.disposition_pgr,
            "disposition_plr": m.disposition_plr,
            "disposition_dei": m.disposition_dei,
            "loss_aversion_index": m.loss_aversion_index,
            "sus_score": sus.sus_score if sus else None,
            "sus_submitted_at": (
                sus.submitted_at.isoformat() if sus and sus.submitted_at else None
            ),
            "sus_open_confusing": sus.open_confusing if sus else None,
            "sus_open_useful": sus.open_useful if sus else None,
            "session_error_count": error_count,
        })
    return rows


def log_session_error(
    db_session: Session,
    *,
    user_id: int | None,
    session_id: str | None,
    error_type: str,
    message: str | None = None,
) -> SessionError:
    """Persist one SessionError row. Lightweight DB-backed counter."""
    err = SessionError(
        user_id=user_id,
        session_id=session_id,
        error_type=error_type,
        message=message,
    )
    db_session.add(err)
    db_session.flush()
    return err
