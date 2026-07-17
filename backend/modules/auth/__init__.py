"""modules/auth — v6 authentication for the CDT Bias Detection System.

Exports the register / authenticate / profile-lookup primitives used by the
Streamlit entry flow. The auth layer is intentionally minimal (username +
bcrypt password) for an MVP SQLite deployment — it is not a replacement for a
production IdP.
"""

from modules.auth.passwords import hash_password, verify_password
from modules.auth.rate_limit import is_locked, record_failure, reset_attempts
from modules.auth.service import (
    AuthError,
    DuplicateUsernameError,
    InvalidCredentialsError,
    RateLimitedError,
    WeakPasswordError,
    authenticate,
    register_user,
    user_exists,
)

__all__ = [
    "AuthError",
    "DuplicateUsernameError",
    "InvalidCredentialsError",
    "RateLimitedError",
    "WeakPasswordError",
    "authenticate",
    "hash_password",
    "is_locked",
    "record_failure",
    "register_user",
    "reset_attempts",
    "user_exists",
    "verify_password",
]
