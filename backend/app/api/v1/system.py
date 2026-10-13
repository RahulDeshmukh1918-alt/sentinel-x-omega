from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import Pagination, get_app_settings, get_current_user, require_role
from backend.app.core.config import Settings
from backend.app.core.enums import LogStatus, UserRole
from backend.app.database.connection import get_db
from backend.app.models import SystemLog, User
from backend.app.schemas.common import Page
from backend.app.schemas.incident import AuditEntryOut

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/config", summary="Effective detection / risk configuration (no secrets)")
def get_config(settings: Settings = Depends(get_app_settings), _: User = Depends(get_current_user)) -> dict:
    return settings.public_view()


@router.get("/logs", response_model=Page[AuditEntryOut], summary="Audit trail")
def audit_logs(module: str | None = None, status: LogStatus | None = None, pagination: Pagination = Depends(),
               db: Session = Depends(get_db), _: User = Depends(require_role(UserRole.OPERATOR))):
    q = select(SystemLog)
    if module:
        q = q.where(SystemLog.module == module)
    if status:
        q = q.where(SystemLog.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(SystemLog.timestamp.desc(), SystemLog.id.desc())
                      .offset(pagination.offset).limit(pagination.page_size))
    return Page[AuditEntryOut].build([AuditEntryOut.model_validate(r) for r in rows], total, pagination.page, pagination.page_size)
