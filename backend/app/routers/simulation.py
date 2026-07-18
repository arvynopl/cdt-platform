"""app/routers/simulation.py — session lifecycle, rounds, analysis, results."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.deps import current_user, get_db, require_csrf
from app.services import simulation as svc
from database.models import User

router = APIRouter(prefix="/api/sessions", tags=["simulation"])


def _translate(exc: svc.SimulationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("", dependencies=[Depends(require_csrf)])
def start_or_resume(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    try:
        return svc.start_or_resume_session(db, user.id)
    except svc.SimulationError as exc:
        raise _translate(exc) from None


@router.post("/{session_id}/rounds/{round_number}", dependencies=[Depends(require_csrf)])
def submit_round(
    session_id: str,
    round_number: int,
    payload: schemas.RoundSubmitIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = svc.submit_round(
            db,
            user_id=user.id,
            session_id=session_id,
            round_number=round_number,
            orders=[o.model_dump() for o in payload.orders],
            response_time_ms=payload.response_time_ms,
        )
    except svc.SimulationError as exc:
        raise _translate(exc) from None

    if result["rounds_complete"]:
        # The response returns immediately; analytics runs after it is sent.
        # Clients poll GET /{session_id}/analysis (DB-truth status).
        background.add_task(svc.run_post_session_pipeline, user.id, session_id)
    return result


@router.post("/{session_id}/analysis/retry", dependencies=[Depends(require_csrf)])
def retry_analysis(
    session_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run a failed pipeline (decisions are already safely stored)."""
    try:
        status = svc.analysis_status(db, user.id, session_id)
    except svc.SimulationError as exc:
        raise _translate(exc) from None
    if status["status"] == "completed":
        return status
    if status["status"] == "in_progress":
        raise HTTPException(409, "Sesi belum menyelesaikan seluruh putaran.")
    background.add_task(svc.run_post_session_pipeline, user.id, session_id)
    return {**status, "status": "processing"}


@router.get("/{session_id}/analysis")
def analysis(
    session_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return svc.analysis_status(db, user.id, session_id)
    except svc.SimulationError as exc:
        raise _translate(exc) from None


@router.get("/{session_id}/results")
def results(
    session_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return svc.session_results(db, user.id, session_id)
    except svc.SimulationError as exc:
        raise _translate(exc) from None


@router.post("/{session_id}/abandon", dependencies=[Depends(require_csrf)])
def abandon(
    session_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.abandon_session(db, user.id, session_id)
    except svc.SimulationError as exc:
        raise _translate(exc) from None
    return {"ok": True}
