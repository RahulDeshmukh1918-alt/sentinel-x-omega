"""Alert Agent: creates dashboard alerts and handles acknowledgement.

Alerts are shown in the dashboard only. There is no SMS, e-mail, siren or
emergency-dispatch integration in this prototype.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.enums import AlertStatus, AlertType, Severity
from backend.app.core.errors import conflict, not_found
from backend.app.models import Alert, Incident
from backend.app.models.base import utcnow
from backend.app.services.audit_service import AuditAgent


class AlertAgent:
    def __init__(self, session: Session):
        self.session = session
        self.audit = AuditAgent(session)

    def create_for_incident(self, incident: Incident, alert_type: AlertType, message: str,
                            severity: Severity | None = None) -> Alert:
        alert = Alert(incident=incident, alert_type=alert_type, severity=severity or incident.severity,
                      message=message, status=AlertStatus.UNACKNOWLEDGED)
        self.session.add(alert)
        self.session.flush()
        self.audit.record("ALERT_CREATED", "alert_agent", f"{alert_type.value} alert for incident {incident.id}",
                          entity_type="incident", entity_id=incident.id)
        return alert

    def acknowledge(self, alert_id: int, user_id: int) -> Alert:
        alert = self.session.get(Alert, alert_id)
        if alert is None:
            raise not_found("alert", alert_id)
        if alert.status == AlertStatus.ACKNOWLEDGED:
            raise conflict("ALERT_ALREADY_ACKNOWLEDGED", f"Alert {alert_id} was already acknowledged",
                           {"acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None})
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = user_id
        self.audit.record("ALERT_ACKNOWLEDGED", "alert_agent", f"alert {alert_id} acknowledged",
                          user_id=user_id, entity_type="incident", entity_id=alert.incident_id)
        self.session.commit()
        return alert

    def list(self, *, status: AlertStatus | None = None, severity: Severity | None = None,
             incident_id: int | None = None, offset: int = 0, limit: int = 50) -> tuple[list[Alert], int]:
        q = select(Alert)
        if status is not None:
            q = q.where(Alert.status == status)
        if severity is not None:
            q = q.where(Alert.severity == severity)
        if incident_id is not None:
            q = q.where(Alert.incident_id == incident_id)
        total = self.session.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.session.scalars(q.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit))
        return list(rows), total
