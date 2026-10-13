from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import Pagination, get_current_user, require_role
from backend.app.core.enums import AlertStatus, Severity, UserRole
from backend.app.database.connection import get_db
from backend.app.models import User
from backend.app.schemas.common import Page
from backend.app.schemas.incident import AlertOut
from backend.app.services.alert_service import AlertAgent

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertOut])
def list_alerts(status: AlertStatus | None = None, severity: Severity | None = None,
                incident_id: int | None = Query(None, gt=0), pagination: Pagination = Depends(),
                db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows, total = AlertAgent(db).list(status=status, severity=severity, incident_id=incident_id,
                                      offset=pagination.offset, limit=pagination.page_size)
    return Page[AlertOut].build([AlertOut.model_validate(a) for a in rows], total, pagination.page, pagination.page_size)


@router.patch("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_role(UserRole.OPERATOR))):
    """Marks the alert as seen. Returns 409 if it was already acknowledged."""
    return AlertOut.model_validate(AlertAgent(db).acknowledge(alert_id, user.id))
