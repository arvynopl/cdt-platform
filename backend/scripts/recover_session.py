"""scripts/recover_session.py — Re-run the post-session analysis pipeline
for a session whose pipeline failed (SessionSummary.status == "error").

Background
----------
The post-session pipeline (bias metrics → CDT update → feedback) runs in a
single transaction. On failure everything is rolled back, so the raw
UserAction rows (committed round-by-round during the simulation) remain
intact and the analysis can be safely re-executed offline.

Safety guards:
    * Refuses to run if a BiasMetric already exists for the session
      (re-running would duplicate metrics and double-apply the EMA step).
    * Refuses to run if the session is not in "error" status,
      unless --force is given (e.g. for sessions stuck "in_progress"
      after a browser crash on the final round — verify completeness first).

Usage:
    python -m scripts.recover_session --session-id bb198838
    python -m scripts.recover_session --session-id bb198838-xxxx-... --force

The session id may be a unique prefix (min 8 chars).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from config import ROUNDS_PER_SESSION
from database.connection import get_session, init_db
from database.models import BiasMetric, SessionSummary
from modules.analytics.bias_metrics import compute_and_save_metrics
from modules.analytics.features import extract_session_features
from modules.cdt.updater import update_profile
from modules.feedback.generator import generate_feedback
from modules.logging_engine.validator import validate_session_completeness

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("recover_session")


def recover(session_id_prefix: str, force: bool = False) -> int:
    """Re-run the analysis pipeline for one failed session. Returns exit code."""
    if len(session_id_prefix) < 8:
        logger.error("Session id prefix must be at least 8 characters.")
        return 2

    with get_session() as sess:
        matches = (
            sess.query(SessionSummary)
            .filter(SessionSummary.session_id.like(f"{session_id_prefix}%"))
            .all()
        )
        if not matches:
            logger.error("No session found matching prefix %r.", session_id_prefix)
            return 2
        if len(matches) > 1:
            logger.error(
                "Prefix %r is ambiguous (%d matches). Provide more characters.",
                session_id_prefix, len(matches),
            )
            return 2

        summary = matches[0]
        session_id = summary.session_id
        user_id = summary.user_id

        # Guard 1: never re-run on a session that already has metrics.
        existing_metric = (
            sess.query(BiasMetric)
            .filter_by(user_id=user_id, session_id=session_id)
            .first()
        )
        if existing_metric:
            logger.error(
                "Session %s already has a BiasMetric (computed_at=%s). "
                "Re-running would duplicate metrics and double-apply the "
                "CDT EMA step. Aborting.",
                session_id[:8], existing_metric.computed_at,
            )
            return 3

        # Guard 2: recover sessions marked as failed ('error') or stuck as
        # 'in_progress' — the latter occurs when the Streamlit script run is
        # interrupted mid-pipeline (RerunException/StopException are
        # BaseException subclasses and bypass the error handler entirely).
        # Completeness is verified below in both cases.
        if summary.status not in ("error", "in_progress") and not force:
            logger.error(
                "Session %s has status=%r (expected 'error' or 'in_progress'). "
                "Use --force only after verifying completeness manually.",
                session_id[:8], summary.status,
            )
            return 3

        completeness = validate_session_completeness(sess, user_id, session_id)
        if not completeness["is_complete"]:
            logger.warning(
                "Session %s incomplete: %d/%d actions logged, missing rounds=%s",
                session_id[:8],
                completeness["action_count"], completeness["expected_count"],
                completeness["missing_rounds"],
            )
            if not force:
                logger.error("Refusing to recover an incomplete session without --force.")
                return 3

        logger.info("Recovering session %s (user_id=%s)…", session_id[:8], user_id)

        # Same orchestration as _run_post_session_pipeline, minus Streamlit.
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

        summary.status = "completed"
        summary.completed_at = datetime.now(UTC)
        summary.rounds_completed = ROUNDS_PER_SESSION
        summary.final_portfolio_value = features.final_value
        # window_start_date / window_end_date are unknown outside the live
        # Streamlit session; left as-is (they are display metadata only).

        logger.info(
            "Recovered session %s — DEI=%.3f OCS=%.3f LAI=%.3f, "
            "final_value=%.0f, status=completed.",
            session_id[:8],
            bias_metric.disposition_dei or 0.0,
            bias_metric.overconfidence_score or 0.0,
            bias_metric.loss_aversion_index or 0.0,
            features.final_value,
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-run the analysis pipeline for a failed session."
    )
    parser.add_argument(
        "--session-id", required=True,
        help="Session UUID or unique prefix (min 8 chars).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Also recover sessions not in 'error' status or incomplete sessions.",
    )
    args = parser.parse_args()

    init_db()  # applies pending schema migrations before touching the DB
    sys.exit(recover(args.session_id, force=args.force))


if __name__ == "__main__":
    main()
