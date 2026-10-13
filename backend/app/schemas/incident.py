from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from backend.app.core.enums import (
    AlertStatus, AlertType, HazardType, IncidentSource, IncidentStatus, LogStatus, Priority,
    ResponseActionStatus, Severity,
)
from backend.app.schemas.common import ORMModel, UTCDateTime


class ResponseActionOut(ORMModel):
    id: int
    incident_id: int
    recommended_department: str
    recommended_action: str
    priority: Priority
    status: ResponseActionStatus
    dispatch_status: str
    created_at: UTCDateTime


class AlertOut(ORMModel):
    id: int
    incident_id: int
    alert_type: AlertType
    severity: Severity
    message: str
    channel: str
    status: AlertStatus
    created_at: UTCDateTime
    acknowledged_at: UTCDateTime | None
    acknowledged_by: int | None


class DetectionOut(ORMModel):
    id: int
    incident_id: int | None
    camera_id: int | None
    object_class: str
    raw_label: str | None
    confidence: float
    bbox: list[float]
    frame_number: int
    video_time_s: float | None
    is_demo: bool
    timestamp: UTCDateTime


class AuditEntryOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    module: str
    status: LogStatus
    message: str
    timestamp: UTCDateTime


class IncidentCreate(BaseModel):
    """Manual incident report by an operator."""
    incident_type: HazardType
    severity: Severity
    description: str | None = Field(default=None, max_length=2000)
    camera_id: int | None = None
    location_id: int | None = None


class IncidentUpdate(BaseModel):
    status: IncidentStatus | None = None
    severity: Severity | None = None
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _at_least_one(self) -> "IncidentUpdate":
        if self.status is None and self.severity is None and self.description is None:
            raise ValueError("provide at least one of status, severity, description")
        return self


class IncidentOut(BaseModel):
    id: int
    incident_type: HazardType
    severity: Severity
    risk_score: float | None
    status: IncidentStatus
    source: IncidentSource
    is_demo: bool
    camera_id: int | None
    camera_name: str | None
    location_id: int | None
    location_name: str | None
    source_label: str | None
    description: str | None
    detection_timestamp: UTCDateTime
    last_detection_at: UTCDateTime
    peak_confidence: float | None
    frames_observed: int
    recommended_action: str | None
    recommended_department: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @classmethod
    def from_incident(cls, inc) -> "IncidentOut":
        latest = inc.response_actions[-1] if inc.response_actions else None
        return cls(
            id=inc.id, incident_type=inc.incident_type, severity=inc.severity, risk_score=inc.risk_score,
            status=inc.status, source=inc.source, is_demo=inc.source == IncidentSource.DEMO_HEURISTIC,
            camera_id=inc.camera_id, camera_name=inc.camera.name if inc.camera else None,
            location_id=inc.location_id, location_name=inc.location.name if inc.location else None,
            source_label=inc.source_label, description=inc.description,
            detection_timestamp=inc.detection_timestamp, last_detection_at=inc.last_detection_at,
            peak_confidence=inc.peak_confidence, frames_observed=inc.frames_observed,
            recommended_action=latest.recommended_action if latest else None,
            recommended_department=latest.recommended_department if latest else None,
            created_at=inc.created_at, updated_at=inc.updated_at,
        )


class IncidentDetail(IncidentOut):
    detections: list[DetectionOut]
    alerts: list[AlertOut]
    response_actions: list[ResponseActionOut]
    history: list[AuditEntryOut]
