"""modules/auth/passwords.py — bcrypt wrapper.

Single source of truth for hashing + verification so the rest of the codebase
never touches bcrypt directly.
"""

from __future__ import annotations

import bcrypt

from config import BCRYPT_ROUNDS


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt, returning a UTF-8 string."""
    if not isinstance(plain, str) or not plain:
        raise ValueError("password must be a non-empty string")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Timing-safe bcrypt verify. Returns False on any input error."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
