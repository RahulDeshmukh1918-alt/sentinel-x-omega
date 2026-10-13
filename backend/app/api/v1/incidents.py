from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import Pagination, get_current_user, require_role
from backend.app.core.enums import AlertType, HazardType, IncidentStatus, Severity, UserRole
from backend.app.database.connection import get_db
from backend.app.models import SystemLog, User
from backend.app.schemas.common import Page
from backend.app.schemas.incident import (
    AlertOut, AuditEntryOut, DetectionOut, IncidentCreate, IncidentDetail, IncidentOut, IncidentUpdate,
    ResponseActionOut,
)
from backend.app.services.alert_service import AlertAgent
from backend.app.services.incident_service import IncidentFilters, IncidentManagementAgent
from backend.app.services.incident_workflow import persist_recommendations
from backend.app.services.response_service import ResponseRecommendationAgent

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _detail(db: Session, agent: IncidentManagementAgent, incident_id: int) -> IncidentDetail:
    inc = agent.get(incident_id, with_relations=True)
    history = db.scalars(select(SystemLog).where(SystemLog.entity_type == "incident", SystemLog.entity_id == inc.id)
                         .order_by(SystemLog.timestamp, SystemLog.id))
    return IncidentDetail(
        **IncidentOut.from_incident(inc).model_dump(),
        detections=[DetectionOut.model_validate(d) for d in inc.detections],
        alerts=[AlertOut.model_validate(a) for a in inc.alerts],
        response_actions=[ResponseActionOut.model_validate(r) for r in inc.response_actions],
        history=[AuditEntryOut.model_validate(h) for h in history],
    )


@router.get("", response_model=Page[IncidentOut])
def list_incidents(
    hazard_type: HazardType | None = None,
    severity: Severity | None = None,
    status: IncidentStatus | None = None,
    camera_id: int | None = Query(None, gt=0),
    location_id: int | None = Query(None, gt=0),
    active_only: bool = False,
    date_from: datetime | None = Query(None, description="ISO 8601, inclusive"),
    date_to: datetime | None = Query(None, description="ISO 8601, inclusive"),
    pagination: Pagination = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filters = IncidentFilters(hazard_type, severity, status, camera_id, location_id, active_only, date_from, date_to)
    rows, total = IncidentManagementAgent(db).list(filters, pagination.offset, pagination.page_size)
    return Page[IncidentOut].build([IncidentOut.from_incident(r) for r in rows], total, pagination.page, pagination.page_size)


@router.post("", response_model=IncidentDetail, status_code=201)
def report_incident(body: IncidentCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.OPERATOR))):
    """Manual incident report by an operator (``source=MANUAL``, no model risk score)."""
    agent = IncidentManagementAgent(db)
    inc = agent.create_manual(hazard_type=body.incident_type, severity=body.severity, description=body.description,
                              camera_id=body.camera_id, location_id=body.location_id, user_id=user.id)
    persist_recommendations(db, inc, ResponseRecommendationAgent().recommend(inc.incident_type, inc.severity))
    AlertAgent(db).create_for_incident(inc, AlertType.MANUAL_REPORT,
                                       f"Manual {inc.severity.value} {inc.incident_type.value} report by {user.name}")
    db.commit()
    return _detail(db, agent, inc.id)


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _detail(db, IncidentManagementAgent(db), incident_id)


@router.patch("/{incident_id}", response_model=IncidentDetail)
def update_incident(incident_id: int, body: IncidentUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.OPERATOR))):
    agent = IncidentManagementAgent(db)
    agent.update(incident_id, user_id=user.id, status=body.status, severity=body.severity,
                 description=body.description)
    db.expire_all()
    return _detail(db, agent, incident_id)
