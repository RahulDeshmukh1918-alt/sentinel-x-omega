from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_app_settings, get_current_user
from backend.app.core.config import Settings
from backend.app.core.enums import LogStatus
from backend.app.core.errors import AppError
from backend.app.core.security import create_access_token, verify_password
from backend.app.database.connection import get_db
from backend.app.models import User
from backend.app.schemas.user import TokenResponse, UserOut
from backend.app.services.audit_service import AuditAgent

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Exchange e-mail + password for a JWT")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db),
          settings: Settings = Depends(get_app_settings)) -> TokenResponse:
    """OAuth2 password flow: send ``username`` (the e-mail) and ``password`` as form fields."""
    email = form.username.strip().lower()
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    audit = AuditAgent(db)
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        audit.record("LOGIN_FAILED", "auth", f"failed login for {email[:80]}", status=LogStatus.WARNING)
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "incorrect e-mail or password", headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token(user.id, user.role.value, settings)
    audit.record("LOGIN", "auth", f"{user.email} signed in", user_id=user.id)
    db.commit()
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60,
                         user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
