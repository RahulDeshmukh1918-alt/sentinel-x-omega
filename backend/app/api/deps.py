"""Shared FastAPI dependencies: settings, DB session, job manager, auth and roles."""
from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.enums import UserRole
from backend.app.core.errors import AppError
from backend.app.core.security import decode_access_token
from backend.app.database.connection import get_db
from backend.app.models import User
from backend.app.services.detection_service import DetectionJobManager

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_UNAUTHORISED_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_job_manager(request: Request) -> DetectionJobManager:
    return request.app.state.job_manager


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> User:
    if not token:
        raise AppError(401, "NOT_AUTHENTICATED", "missing bearer token", headers=_UNAUTHORISED_HEADERS)
    try:
        payload = decode_access_token(token, settings)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise AppError(401, "INVALID_TOKEN", "token is invalid or expired", headers=_UNAUTHORISED_HEADERS)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "INVALID_TOKEN", "user no longer exists or is disabled", headers=_UNAUTHORISED_HEADERS)
    return user


_ROLE_LEVEL = {UserRole.VIEWER: 1, UserRole.OPERATOR: 2, UserRole.ADMIN: 3}


def require_role(minimum: UserRole) -> Callable[..., User]:
    """ADMIN > OPERATOR > VIEWER. ``require_role(UserRole.OPERATOR)`` admits operators and admins."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if _ROLE_LEVEL[user.role] < _ROLE_LEVEL[minimum]:
            raise AppError(403, "FORBIDDEN", f"requires {minimum.value} role or higher")
        return user

    return _checker


class Pagination:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
