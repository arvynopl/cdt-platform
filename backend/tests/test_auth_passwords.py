"""tests/test_auth_passwords.py — bcrypt wrapper sanity."""

import pytest

from modules.auth.passwords import hash_password, verify_password


def test_hash_verify_roundtrip():
    h = hash_password("super-secret-password")
    assert isinstance(h, str)
    assert h != "super-secret-password"
    assert verify_password("super-secret-password", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("correct")
    assert verify_password("incorrect", h) is False


def test_hash_produces_distinct_salts():
    h1 = hash_password("same-plaintext")
    h2 = hash_password("same-plaintext")
    assert h1 != h2  # bcrypt salts differ
    assert verify_password("same-plaintext", h1)
    assert verify_password("same-plaintext", h2)


def test_verify_rejects_empty_input():
    h = hash_password("abcd1234")
    assert verify_password("", h) is False
    assert verify_password("abcd1234", "") is False


def test_hash_rejects_empty_password():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_rejects_malformed_hash():
    # Not a valid bcrypt hash — should return False, not raise.
    assert verify_password("pw", "not-a-bcrypt-hash") is False
