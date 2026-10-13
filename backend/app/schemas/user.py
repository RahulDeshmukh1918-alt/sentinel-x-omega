from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from backend.app.core.enums import UserRole
from backend.app.schemas.common import ORMModel, UTCDateTime


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = UserRole.VIEWER


class UserOut(ORMModel):
    id: int
    name: str
    email: str
    role: UserRole
    is_active: bool
    created_at: UTCDateTime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
