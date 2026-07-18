"""app/routers/researcher.py — cohort inspection + ops summary endpoints.

Replaces the thesis build's hidden Streamlit pages (`?view=researcher`,
`?admin=<token>`) with key-gated JSON/CSV endpoints the Fase 2 researcher
dashboard consumes.

Access model (Fase 1): two static keys supplied per request in headers,
compared in constant time against environment variables —

  * ``X-Researcher-Key``  vs ``CDT_RESEARCHER_PASSWORD`` — cohort data.
  * ``X-Admin-Token``     vs ``CDT_ADMIN_TOKEN``        — ops counters.

An unset variable disables its endpoints (503), mirroring the thesis
behaviour where the researcher view was inactive until configured. True
per-user RBAC is deferred to the account-management pivot the owner has
flagged as a possible later direction.

Every data endpoint accepts ``?format=csv`` to return ``text/csv`` for
direct download (NFR07 interoperability), else JSON rows.
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_db
from database.models import (
    BiasMetric,
    SessionError,
    SessionSummary,
    UATFeedback,
    User,
)
from modules.utils.research_export import (
    compute_cohort_session_progression,
    export_all_sessions_csv,
    export_all_users_csv,
    export_cdt_snapshots_csv,
    export_post_session_surveys_csv,
    export_uat_feedback_csv,
    get_cohort_summary,
    load_model_performance,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/researcher", tags=["researcher"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def _check_key(request: Request, header: str, env_var: str) -> None:
    expected = os.environ.get(env_var)
    if not expected:
        raise HTTPException(
            503,
            f"Endpoint nonaktif: variabel lingkungan {env_var} belum diatur.",
        )
    supplied = request.headers.get(header) or ""
    if not hmac.compare_digest(supplied, expected):
        logger.warning("rejected %s request (bad %s)", request.url.path, header)
        raise HTTPException(401, "Kunci akses tidak valid.")


def require_researcher_key(request: Request) -> None:
    _check_key(request, "x-researcher-key", "CDT_RESEARCHER_PASSWORD")


def require_admin_token(request: Request) -> None:
    _check_key(request, "x-admin-token", "CDT_ADMIN_TOKEN")


# ---------------------------------------------------------------------------
# Row-set endpoints (JSON default, ?format=csv for download)
# ---------------------------------------------------------------------------

def _rows_response(rows: list[dict], fmt: str, filename: str):
    if fmt == "csv":
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "content-disposition": f'attachment; filename="{filename}.csv"'
            },
        )
    return {"rows": rows, "count": len(rows)}


_EXPORTS = {
    "users": (export_all_users_csv, "cohort_users"),
    "sessions": (export_all_sessions_csv, "all_sessions"),
    "cdt-snapshots": (export_cdt_snapshots_csv, "cdt_snapshots"),
    "uat-feedback": (export_uat_feedback_csv, "uat_feedback"),
    "post-session-surveys": (export_post_session_surveys_csv, "post_session_surveys"),
}


@router.get("/summary", dependencies=[Depends(require_researcher_key)])
def cohort_summary(
    participants_only: bool = False, db: Session = Depends(get_db)
) -> dict:
    """Cohort KPIs (total users/sessions, mean DEI/OCS/LAI, completion rate)."""
    return get_cohort_summary(db, participants_only=participants_only)


@router.get("/progression", dependencies=[Depends(require_researcher_key)])
def cohort_progression(db: Session = Depends(get_db)) -> dict:
    """Per-session-number cohort bias progression (longitudinal view)."""
    return {"progression": compute_cohort_session_progression(db)}


@router.get("/ml-performance", dependencies=[Depends(require_researcher_key)])
def ml_performance() -> dict:
    """Persisted output of scripts/run_ml_validation.py, if it has been run.

    The helper already reports ``available: false`` when no reports exist.
    """
    return load_model_performance()


@router.get("/export/{dataset}", dependencies=[Depends(require_researcher_key)])
def export_dataset(
    dataset: str,
    format: str = "json",
    participants_only: bool = False,
    db: Session = Depends(get_db),
):
    """Bulk dataset export. ``dataset`` ∈ users | sessions | cdt-snapshots |
    uat-feedback | post-session-surveys."""
    entry = _EXPORTS.get(dataset)
    if entry is None:
        raise HTTPException(
            404,
            f"Dataset {dataset!r} tidak dikenal. Pilihan: {sorted(_EXPORTS)}.",
        )
    fn, filename = entry
    rows = fn(db, participants_only=participants_only)
    return _rows_response(rows, format, filename)


# ---------------------------------------------------------------------------
# Admin ops summary — SQL aggregation, no row materialisation (audit F10)
# ---------------------------------------------------------------------------

@admin_router.get("/summary", dependencies=[Depends(require_admin_token)])
def admin_summary(db: Session = Depends(get_db)) -> dict:
    """Ops counters previously served by the thesis build's ?admin= page.

    All numbers are computed inside Postgres via aggregates — including the
    mean SUS score, expressed as the standard ((odd−1)+(5−even))×2.5 formula
    — so the endpoint stays O(1) in transferred rows at any cohort size.
    """
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_sessions = db.query(func.count(SessionSummary.id)).scalar() or 0
    by_status: dict[str, int] = {
        status: count
        for status, count in (
            db.query(SessionSummary.status, func.count(SessionSummary.id))
            .group_by(SessionSummary.status)
        )
    }
    total_metrics = db.query(func.count(BiasMetric.id)).scalar() or 0
    total_errors = db.query(func.count(SessionError.id)).scalar() or 0

    sus_expr = (
        (UATFeedback.sus_q1 - 1) + (UATFeedback.sus_q3 - 1)
        + (UATFeedback.sus_q5 - 1) + (UATFeedback.sus_q7 - 1)
        + (UATFeedback.sus_q9 - 1)
        + (5 - UATFeedback.sus_q2) + (5 - UATFeedback.sus_q4)
        + (5 - UATFeedback.sus_q6) + (5 - UATFeedback.sus_q8)
        + (5 - UATFeedback.sus_q10)
    ) * 2.5
    total_uat, avg_sus = (
        db.query(func.count(UATFeedback.id), func.avg(sus_expr)).one()
    )

    completed = by_status.get("completed", 0)
    return {
        "total_users": total_users,
        "total_sessions": total_sessions,
        "sessions_by_status": by_status,
        "completed_sessions": completed,
        "completion_rate": (
            round(completed / total_sessions, 4) if total_sessions else 0.0
        ),
        "total_bias_metrics": total_metrics,
        "total_session_errors": total_errors,
        "error_rate_per_session": (
            round(total_errors / total_sessions, 4) if total_sessions else 0.0
        ),
        "total_uat_feedback": total_uat or 0,
        "avg_sus_score": round(float(avg_sus), 2) if avg_sus is not None else None,
    }
