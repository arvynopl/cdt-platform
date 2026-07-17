"""modules/auth/service.py — register/login orchestration.

The service layer is DB-agnostic: callers pass in a SQLAlchemy Session. This
keeps the auth path testable without binding to the Streamlit app's
connection helper.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from config import AUTH_PASSWORD_MIN_LEN
from database.models import OnboardingSurvey, User, UserProfile
from modules.auth.passwords import hash_password, verify_password
from modules.auth.rate_limit import is_locked, record_failure, reset_attempts

logger = logging.getLogger(__name__)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.\- ]{2,64}$")

_VALID_GENDERS = {"laki-laki", "perempuan", "lainnya"}
_VALID_RISK_PROFILES = {"konservatif", "moderat", "agresif"}
_VALID_CAPABILITIES = {"pemula", "menengah", "berpengalaman"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Base class for authentication errors."""


class DuplicateUsernameError(AuthError):
    """Raised when attempting to register a username already in use."""


class InvalidCredentialsError(AuthError):
    """Raised for any combination of unknown user / bad password."""


class RateLimitedError(AuthError):
    """Raised when an account is locked by the rate limiter."""


class WeakPasswordError(AuthError):
    """Raised for passwords below the minimum length."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_username(raw: str) -> str:
    return (raw or "").strip()


def _validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise AuthError(
            "Nama pengguna hanya boleh berisi huruf, angka, titik, "
            "tanda hubung, garis bawah, atau spasi (2–64 karakter)."
        )


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < AUTH_PASSWORD_MIN_LEN:
        raise WeakPasswordError(
            f"Kata sandi harus minimal {AUTH_PASSWORD_MIN_LEN} karakter."
        )


def user_exists(db: Session, username: str) -> bool:
    """Return True if a User row with this username exists."""
    username = _normalise_username(username)
    if not username:
        return False
    return (
        db.query(User)
        .filter(User.username == username)
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


def register_user(
    db: Session,
    *,
    username: str,
    password: str,
    full_name: str,
    age: int,
    gender: str,
    risk_profile: str,
    investing_capability: str,
    onboarding_survey: dict | None = None,
) -> User:
    """Create a new User + UserProfile (+ optional OnboardingSurvey) row set.

    ``onboarding_survey`` — if provided, must be a dict containing the nine
    Likert (1–5) keys: ``dei_q1..dei_q3``, ``ocs_q1..ocs_q3``, ``lai_q1..lai_q3``.
    Raises DuplicateUsernameError / WeakPasswordError / AuthError on invalid
    input. Caller is responsible for committing the session.
    """
    username = _normalise_username(username)
    _validate_username(username)
    _validate_password(password)

    full_name = (full_name or "").strip()
    if len(full_name) < 2:
        raise AuthError("Nama lengkap harus minimal 2 karakter.")
    if not isinstance(age, int) or age < 17 or age > 100:
        raise AuthError("Usia harus bilangan bulat antara 17 dan 100.")
    if gender not in _VALID_GENDERS:
        raise AuthError(f"Gender tidak valid. Pilihan: {sorted(_VALID_GENDERS)}")
    if risk_profile not in _VALID_RISK_PROFILES:
        raise AuthError(
            f"Profil risiko tidak valid. Pilihan: {sorted(_VALID_RISK_PROFILES)}"
        )
    if investing_capability not in _VALID_CAPABILITIES:
        raise AuthError(
            f"Kemampuan investasi tidak valid. Pilihan: {sorted(_VALID_CAPABILITIES)}"
        )

    if user_exists(db, username):
        raise DuplicateUsernameError(
            f"Nama pengguna {username!r} sudah terdaftar."
        )

    user = User(
        username=username,
        password_hash=hash_password(password),
        alias=username,  # keep legacy display field consistent
        experience_level={
            "pemula": "beginner",
            "menengah": "intermediate",
            "berpengalaman": "advanced",
        }[investing_capability],
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()

    db.add(UserProfile(
        user_id=user.id,
        full_name=full_name,
        age=age,
        gender=gender,
        risk_profile=risk_profile,
        investing_capability=investing_capability,
    ))

    if onboarding_survey:
        _persist_onboarding_survey(db, user.id, onboarding_survey)

    logger.info("Registered new user username=%r id=%s", username, user.id)
    return user


def _persist_onboarding_survey(
    db: Session,
    user_id: int,
    survey: dict,
) -> OnboardingSurvey:
    required = [
        "dei_q1", "dei_q2", "dei_q3",
        "ocs_q1", "ocs_q2", "ocs_q3",
        "lai_q1", "lai_q2", "lai_q3",
    ]
    missing = [k for k in required if k not in survey]
    if missing:
        raise AuthError(f"Survei onboarding kekurangan item: {missing}")
    for k in required:
        v = survey[k]
        if not isinstance(v, int) or not (1 <= v <= 5):
            raise AuthError(
                f"Item survei {k!r} harus bilangan bulat 1–5, diterima {v!r}."
            )

    row = OnboardingSurvey(user_id=user_id, **{k: survey[k] for k in required})
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Authenticate
# ---------------------------------------------------------------------------


def authenticate(db: Session, username: str, password: str) -> User:
    """Verify credentials. Raises on failure.

    On success, updates ``last_login_at`` and resets the rate-limit window.
    """
    username = _normalise_username(username)
    if is_locked(username):
        raise RateLimitedError(
            "Akun sementara dikunci karena terlalu banyak percobaan gagal. "
            "Silakan coba lagi dalam beberapa menit."
        )

    user: User | None = (
        db.query(User).filter(User.username == username).first()
    )
    if user is None or not user.password_hash:
        record_failure(username)
        raise InvalidCredentialsError("Nama pengguna atau kata sandi salah.")

    if not verify_password(password, user.password_hash):
        record_failure(username)
        raise InvalidCredentialsError("Nama pengguna atau kata sandi salah.")

    user.last_login_at = datetime.now(UTC)
    reset_attempts(username)
    db.flush()
    logger.info("Authenticated user username=%r id=%s", username, user.id)
    return user
