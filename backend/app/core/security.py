"""Password hashing (bcrypt) and JWT access tokens (PyJWT)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from backend.app.core.config import Settings

BCRYPT_MAX_BYTES = 72
MIN_PASSWORD_LENGTH = 8


class PasswordPolicyError(ValueError):
    pass


def hash_password(password: str) -> str:
    import bcrypt  # imported lazily so token helpers work without the C extension

    raw = password.encode("utf-8")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise PasswordPolicyError("password must be at most 72 bytes (bcrypt limit)")
    # 12 rounds by default; tests lower it via BCRYPT_ROUNDS for speed (bcrypt minimum is 4)
    rounds = min(15, max(4, int(os.environ.get("BCRYPT_ROUNDS", "12"))))
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | int, role: str, settings: Settings, expires_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": str(subject), "role": role, "iat": now, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises ``jwt.InvalidTokenError`` (or subclasses) when invalid/expired."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access" or "sub" not in payload:
        raise jwt.InvalidTokenError("not an access token")
    return payload
