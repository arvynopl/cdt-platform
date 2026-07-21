"""app/routers/profile.py — cognitive profile, session history, surveys.

Read models mirror the data assembly of the thesis build's "Profil Kognitif
Saya" page so the Fase 2 frontend can render the same radar/trajectory
visualisations from one call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import schemas
from app.deps import current_user, get_db, require_csrf
from app.security.sessions import (
    clear_session_cookies,
    create_auth_session,
    set_session_cookies,
)
from app.services.account import (
    anonymize_user,
    export_user_data,
    export_user_data_csv_zip,
)
from database.models import (
    AuthSession,
    BiasMetric,
    CdtSnapshot,
    CognitiveProfile,
    PostSessionSurvey,
    SessionSummary,
    UATFeedback,
    User,
    UserProfile,
)
from modules.analytics.personal_baseline import (
    compute_personal_thresholds,
    normalised_scientific_thresholds,
)
from modules.auth.passwords import hash_password, verify_password
from modules.utils.export import export_user_history_csv

router = APIRouter(prefix="/api/me", tags=["profile"])


@router.get("/profile")
def my_profile(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    profile = (
        db.query(CognitiveProfile).filter_by(user_id=user.id).first()
    )
    metrics = (
        db.query(BiasMetric)
        .filter_by(user_id=user.id)
        .order_by(BiasMetric.computed_at)
        .all()
    )
    snapshots = (
        db.query(CdtSnapshot)
        .filter_by(user_id=user.id)
        .order_by(CdtSnapshot.session_number)
        .all()
    )

    metrics_data = [
        {
            "session_num": i + 1,
            "session_id": m.session_id,
            "ocs": m.overconfidence_score or 0.0,
            "dei": abs(m.disposition_dei or 0.0),
            "dei_raw": m.disposition_dei or 0.0,
            "pgr": m.disposition_pgr or 0.0,
            "plr": m.disposition_plr or 0.0,
            "lai_norm": min((m.loss_aversion_index or 0.0) / 3.0, 1.0),
            "lai_raw": m.loss_aversion_index or 0.0,
            "computed_at": m.computed_at.isoformat() if m.computed_at else None,
        }
        for i, m in enumerate(metrics)
    ]
    personal = compute_personal_thresholds(metrics_data) if metrics_data else None

    return {
        "profile": None if profile is None else {
            "bias_intensity_vector": dict(profile.bias_intensity_vector),
            "risk_preference": profile.risk_preference,
            "stability_index": profile.stability_index,
            "session_count": profile.session_count,
            "interaction_scores": (
                dict(profile.interaction_scores)
                if profile.interaction_scores else None
            ),
            "last_updated_at": (
                profile.last_updated_at.isoformat()
                if profile.last_updated_at else None
            ),
        },
        "metrics": metrics_data,
        "cdt_snapshots": [
            {
                "session_number": s.session_number,
                "cdt_overconfidence": s.cdt_overconfidence,
                "cdt_disposition": s.cdt_disposition,
                "cdt_loss_aversion": s.cdt_loss_aversion,
                "cdt_risk_preference": s.cdt_risk_preference,
                "cdt_stability_index": s.cdt_stability_index,
            }
            for s in snapshots
        ],
        "thresholds": {
            "scientific": normalised_scientific_thresholds(),
            "personal": personal,
        },
    }


@router.get("/history")
def my_history(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Flat per-session rows — the frontend renders these and offers CSV
    download client-side (NFR07 interoperability)."""
    return {"rows": export_user_history_csv(db, user.id)}


# ---------------------------------------------------------------------------
# Account management (Manajemen Akun)
# ---------------------------------------------------------------------------

# Mirrors the mapping applied at registration in modules/auth/service.py.
_CAPABILITY_TO_LEVEL = {
    "pemula": "beginner",
    "menengah": "intermediate",
    "berpengalaman": "advanced",
}


@router.get("/account")
def my_account(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Account identity plus the editable profile fields."""
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    return {
        "username": user.username,
        "experience_level": user.experience_level,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "profile": None if profile is None else {
            "full_name": profile.full_name,
            "age": profile.age,
            "gender": profile.gender,
            "risk_profile": profile.risk_profile,
            "investing_capability": profile.investing_capability,
        },
    }


@router.patch("/profile", dependencies=[Depends(require_csrf)])
def update_my_profile(
    payload: schemas.ProfileUpdateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update the editable profile fields.

    Username is not accepted here on purpose: it is the login identity and the
    key research records are grouped by, so it stays immutable.
    """
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    if profile is None:
        raise HTTPException(404, "Profil tidak ditemukan.")

    profile.full_name = payload.full_name
    profile.age = payload.age
    profile.gender = payload.gender
    profile.risk_profile = payload.risk_profile
    profile.investing_capability = payload.investing_capability
    # Keep the denormalised level on User consistent with the capability.
    user.experience_level = _CAPABILITY_TO_LEVEL[payload.investing_capability]
    return {"status": "ok"}


@router.post("/password", dependencies=[Depends(require_csrf)])
def change_my_password(
    payload: schemas.PasswordChangeIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change the password after re-verifying the current one.

    All existing sessions are revoked, because a password change should sign
    out every other device. A fresh session is then issued for THIS browser so
    the caller is not thrown out of the page they are standing on; the new CSRF
    token rides back in the body for the cross-site frontend to cache.
    """
    if not verify_password(payload.current_password, user.password_hash or ""):
        raise HTTPException(400, "Kata sandi saat ini tidak cocok.")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            400, "Kata sandi baru harus berbeda dari kata sandi sekarang."
        )

    user.password_hash = hash_password(payload.new_password)
    db.query(AuthSession).filter_by(user_id=user.id).delete(
        synchronize_session=False
    )
    db.flush()

    token, csrf = create_auth_session(
        db, user.id, request.headers.get("user-agent")
    )
    set_session_cookies(response, token, csrf)
    return {"status": "ok", "csrf_token": csrf}


# ---------------------------------------------------------------------------
# UU PDP data-subject rights (audit F8)
# ---------------------------------------------------------------------------

@router.get("/export")
def export_my_data(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Everything the system holds about the caller (data portability)."""
    return export_user_data(db, user.id)


@router.get("/export/csv")
def export_my_data_csv(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    """Same data as /export, as a ZIP of per-table CSVs (convenience format)."""
    payload = export_user_data_csv_zip(db, user.id)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="data_saya_cdt_csv.zip"'
        },
    )


@router.post("/delete", dependencies=[Depends(require_csrf)])
def delete_my_account(
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Withdraw: anonymise the account (identity + login removed, de-identified
    research rows kept) and end the session."""
    anonymize_user(db, user.id)
    clear_session_cookies(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Surveys
# ---------------------------------------------------------------------------

survey_router = APIRouter(prefix="/api", tags=["surveys"])


@survey_router.post(
    "/sessions/{session_id}/post-survey", dependencies=[Depends(require_csrf)]
)
def submit_post_session_survey(
    session_id: str,
    payload: schemas.PostSessionSurveyIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    owned = (
        db.query(SessionSummary)
        .filter_by(session_id=session_id, user_id=user.id)
        .first()
    )
    if owned is None:
        raise HTTPException(404, "Sesi tidak ditemukan.")

    existing = (
        db.query(PostSessionSurvey)
        .filter_by(user_id=user.id, session_id=session_id)
        .first()
    )
    if existing is not None:
        # One survey per session (DB unique constraint); latest answers win.
        existing.self_overconfidence = payload.self_overconfidence
        existing.self_disposition = payload.self_disposition
        existing.self_loss_aversion = payload.self_loss_aversion
        existing.feedback_usefulness = payload.feedback_usefulness
    else:
        db.add(PostSessionSurvey(
            user_id=user.id, session_id=session_id, **payload.model_dump()
        ))
    db.flush()
    return {"ok": True}


@survey_router.post("/uat-feedback", dependencies=[Depends(require_csrf)])
def submit_uat_feedback(
    payload: schemas.UATFeedbackIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Append-only SUS submission; latest per user is used for analysis.

    The optional third open question folds into ``open_useful`` with the
    same "[Saran perbaikan]" marker the thesis build used, so longitudinal
    analysis across both systems reads one format.
    """
    useful = (payload.open_useful or "").strip()
    suggestion = (payload.open_suggestion or "").strip()
    if suggestion:
        useful = (
            f"{useful}\n\n[Saran perbaikan]\n{suggestion}"
            if useful else f"[Saran perbaikan]\n{suggestion}"
        )

    fb = UATFeedback(
        user_id=user.id,
        session_id=payload.session_id,
        open_confusing=(payload.open_confusing or "").strip() or None,
        open_useful=useful or None,
        **{f"sus_q{i}": getattr(payload, f"sus_q{i}") for i in range(1, 11)},
    )
    db.add(fb)
    db.flush()
    return {"ok": True, "sus_score": fb.sus_score}
