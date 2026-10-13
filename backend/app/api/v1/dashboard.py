from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_job_manager
from backend.app.core.enums import (
    ACTIVE_INCIDENT_STATUSES, AlertStatus, CameraStatus, HazardType, IncidentSource, IncidentStatus, Severity,
)
from backend.app.database.connection import get_db
from backend.app.models import Alert, Camera, Incident, User
from backend.app.models.base import as_utc
from backend.app.schemas.dashboard import DailyCount, DashboardSummary
from backend.app.services.detection_service import DetectionJobManager, model_status_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _count(db: Session, *where) -> int:
    return db.scalar(select(func.count(Incident.id)).where(*where)) or 0


@router.get("/summary", response_model=DashboardSummary)
def summary(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db),
            jobs: DetectionJobManager = Depends(get_job_manager), _: User = Depends(get_current_user)):
    """All figures are computed from the database at request time."""
    now = datetime.now(timezone.utc)
    active = Incident.status.in_(ACTIVE_INCIDENT_STATUSES)

    by_hazard = dict(db.execute(select(Incident.incident_type, func.count()).group_by(Incident.incident_type)).all())
    by_severity = dict(db.execute(select(Incident.severity, func.count()).where(active)
                                  .group_by(Incident.severity)).all())
    by_status = dict(db.execute(select(Incident.status, func.count()).group_by(Incident.status)).all())
    avg_risk = dict(db.execute(select(Incident.incident_type, func.avg(Incident.risk_score))
                               .group_by(Incident.incident_type)).all())

    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    stamps = db.scalars(select(Incident.detection_timestamp).where(Incident.detection_timestamp >= start))
    per_day = Counter(as_utc(ts).date().isoformat() for ts in stamps)
    daily = [DailyCount(date=(start + timedelta(days=i)).date().isoformat(),
                        count=per_day.get((start + timedelta(days=i)).date().isoformat(), 0)) for i in range(days)]

    return DashboardSummary(
        generated_at=now,
        active_incidents=_count(db, active),
        critical_incidents=_count(db, active, Incident.severity == Severity.CRITICAL),
        online_cameras=db.scalar(select(func.count(Camera.id)).where(Camera.status == CameraStatus.ONLINE)) or 0,
        total_cameras=db.scalar(select(func.count(Camera.id))) or 0,
        unacknowledged_alerts=db.scalar(select(func.count(Alert.id))
                                        .where(Alert.status == AlertStatus.UNACKNOWLEDGED)) or 0,
        resolved_incidents=_count(db, Incident.status == IncidentStatus.RESOLVED),
        total_incidents=_count(db),
        demo_incidents=_count(db, Incident.source == IncidentSource.DEMO_HEURISTIC),
        by_hazard={h.value: by_hazard.get(h, 0) for h in HazardType},
        by_severity={s.value: by_severity.get(s, 0) for s in Severity},
        by_status={s.value: by_status.get(s, 0) for s in IncidentStatus},
        daily=daily,
        average_risk_by_hazard={h.value: (round(avg_risk[h], 1) if avg_risk.get(h) is not None else None)
                                for h in HazardType},
        model=model_status_summary(jobs.provider),
        active_jobs=sum(1 for j in jobs.list() if j.is_active),
    )
