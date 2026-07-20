"""app/routers/auth.py — registration, login, logout, whoami.

Preserves the thesis build's username-first UX (the two-step flow is a
deliberate product decision), while replacing its process-local security
with the Fase 1 design: DB-backed rate limiting per username AND source IP
(audit F7), server-side sessions in httpOnly cookies (F6), and CSRF
double-submit on mutations (F5).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import schemas
from app.deps import client_ip, current_user, get_db, require_csrf
from app.security import rate_limit
from app.security.sessions import (
    clear_session_cookies,
    create_auth_session,
    revoke_auth_session,
    set_session_cookies,
)
from config import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from database.models import ConsentLog, User, UserSurvey
from modules.auth import (
    AuthError,
    DuplicateUsernameError,
    WeakPasswordError,
    register_user,
    user_exists,
)
from modules.auth.passwords import verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INVALID_CREDENTIALS = "Nama pengguna atau kata sandi salah."
_LOCKED = (
    "Terlalu banyak percobaan gagal. Silakan coba lagi dalam beberapa menit."
)


@router.post("/check-username", response_model=schemas.UsernameCheckOut)
def check_username(
    payload: schemas.UsernameCheckIn, db: Session = Depends(get_db)
) -> schemas.UsernameCheckOut:
    """Step 1 of the two-step flow: route the client to login or register."""
    return schemas.UsernameCheckOut(exists=user_exists(db, payload.username))


@router.post("/register", response_model=schemas.MeOut, status_code=201)
def register(
    payload: schemas.RegisterIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> schemas.MeOut:
    try:
        user = register_user(
            db,
            username=payload.username,
            password=payload.password,
            full_name=payload.full_name,
            age=payload.age,
            gender=payload.gender,
            risk_profile=payload.risk_profile,
            investing_capability=payload.investing_capability,
            onboarding_survey=payload.onboarding_survey.model_dump(),
        )
    except DuplicateUsernameError:
        raise HTTPException(409, "Nama pengguna sudah digunakan.") from None
    except WeakPasswordError as exc:
        raise HTTPException(422, str(exc)) from None
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from None

    # Compat row for the comparison engine (same mapping as the thesis build).
    survey = payload.onboarding_survey
    db.add(UserSurvey(
        user_id=user.id,
        q_risk_tolerance=survey.ocs_q1,
        q_loss_sensitivity=survey.lai_q1,
        q_trading_frequency=survey.ocs_q2,
        q_holding_behavior=survey.dei_q2,
        survey_type="onboarding",
    ))
    db.add(ConsentLog(
        user_id=user.id,
        consent_given=True,
        consent_text=(
            "Saya telah membaca informasi penelitian dan menyetujui partisipasi."
        ),
        ip_hash=rate_limit.hash_ip(client_ip(request)),
    ))
    db.flush()

    token, csrf = create_auth_session(
        db, user.id, request.headers.get("user-agent")
    )
    set_session_cookies(response, token, csrf)
    return schemas.MeOut(
        user_id=user.id,
        username=user.username or "",
        experience_level=user.experience_level,
        csrf_token=csrf,
    )


@router.post("/login", response_model=schemas.MeOut)
def login(
    payload: schemas.LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> schemas.MeOut:
    username = payload.username.strip()
    ip = client_ip(request)

    if rate_limit.is_locked(db, username, ip):
        raise HTTPException(429, _LOCKED)

    user: User | None = db.query(User).filter(User.username == username).first()
    if (
        user is None
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        rate_limit.record_attempt(username, success=False, ip=ip)
        raise HTTPException(401, _INVALID_CREDENTIALS)

    rate_limit.record_attempt(username, success=True, ip=ip)
    rate_limit.clear_failures(db, username)
    user.last_login_at = datetime.now(UTC)

    token, csrf = create_auth_session(
        db, user.id, request.headers.get("user-agent")
    )
    set_session_cookies(response, token, csrf)
    logger.info("login user=%s id=%s", username, user.id)
    return schemas.MeOut(
        user_id=user.id,
        username=user.username or "",
        experience_level=user.experience_level,
        csrf_token=csrf,
    )


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    revoke_auth_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.MeOut)
def me(request: Request, user: User = Depends(current_user)) -> schemas.MeOut:
    # Echo the CSRF cookie so a cross-site frontend can recover the token after
    # a page reload (it can't read the API-domain cookie via document.cookie).
    return schemas.MeOut(
        user_id=user.id,
        username=user.username or user.alias or "",
        experience_level=user.experience_level,
        csrf_token=request.cookies.get(CSRF_COOKIE_NAME) or "",
    )
