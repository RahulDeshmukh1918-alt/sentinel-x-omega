import importlib.util

import jwt
import pytest

from backend.app.core.security import (
    PasswordPolicyError, create_access_token, decode_access_token, hash_password, verify_password,
)

needs_bcrypt = pytest.mark.skipif(importlib.util.find_spec("bcrypt") is None, reason="bcrypt not installed")


@needs_bcrypt
def test_password_hash_roundtrip():
    h = hash_password("correct horse battery")
    assert h != "correct horse battery" and h.startswith("$2")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong password!", h)


@needs_bcrypt
def test_password_policy():
    with pytest.raises(PasswordPolicyError):
        hash_password("short")
    with pytest.raises(PasswordPolicyError):
        hash_password("x" * 73)


@needs_bcrypt
def test_verify_handles_garbage_hash():
    assert verify_password("anything123", "not-a-bcrypt-hash") is False


def test_token_roundtrip(settings):
    token = create_access_token(42, "ADMIN", settings)
    payload = decode_access_token(token, settings)
    assert payload["sub"] == "42" and payload["role"] == "ADMIN"


def test_expired_and_tampered_tokens_rejected(settings):
    token = create_access_token(1, "VIEWER", settings, expires_minutes=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, settings)
    good = create_access_token(1, "VIEWER", settings)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(good[:-4] + "abcd", settings)
    other = settings.model_copy(update={"jwt_secret_key": "another-secret-another-secret-123"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(good, other)
