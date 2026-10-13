"""Incident Management Agent: creates, de-duplicates, updates and queries incidents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.ai.postprocessor import TrackEvent
from backend.app.core.enums import (
    ACTIVE_INCIDENT_STATUSES, HazardType, IncidentSource, IncidentStatus, LogStatus, Severity,
)
from backend.app.core.errors import AppError, bad_request, not_found
from backend.app.models import Camera, Detection, Incident, Location
from backend.app.models.base import as_utc, utcnow
from backend.app.services.audit_service import AuditAgent
from backend.app.services.risk_service import RiskAssessment

# status workflow; RESOLVED / FALSE_ALARM can be re-opened
ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.ACKNOWLEDGED, IncidentStatus.IN_PROGRESS, IncidentStatus.RESOLVED,
                          IncidentStatus.FALSE_ALARM},
    IncidentStatus.ACKNOWLEDGED: {IncidentStatus.IN_PROGRESS, IncidentStatus.RESOLVED, IncidentStatus.FALSE_ALARM},
    IncidentStatus.IN_PROGRESS: {IncidentStatus.RESOLVED, IncidentStatus.FALSE_ALARM},
    IncidentStatus.RESOLVED: {IncidentStatus.OPEN},
    IncidentStatus.FALSE_ALARM: {IncidentStatus.OPEN},
}


@dataclass
class IncidentFilters:
    hazard_type: HazardType | None = None
    severity: Severity | None = None
    status: IncidentStatus | None = None
    camera_id: int | None = None
    location_id: int | None = None
    active_only: bool = False
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass
class RecordResult:
    incident: Incident
    created: bool
    escalated: bool
    previous_severity: Severity | None = None


class IncidentManagementAgent:
    def __init__(self, session: Session, dedup_window_seconds: int = 300):
        self.session = session
        self.dedup_window = timedelta(seconds=dedup_window_seconds)
        self.audit = AuditAgent(session)

    # ---------------------------------------------------------------- pipeline
    def find_open_duplicate(self, camera_id: int | None, hazard_type: HazardType) -> Incident | None:
        """An active incident of the same type on the same camera, seen within the dedup window."""
        if camera_id is None or self.dedup_window.total_seconds() <= 0:
            return None
        cutoff = utcnow() - self.dedup_window
        q = (
            select(Incident)
            .where(Incident.camera_id == camera_id, Incident.incident_type == hazard_type,
                   Incident.status.in_(ACTIVE_INCIDENT_STATUSES), Incident.last_detection_at >= cutoff)
            .order_by(Incident.last_detection_at.desc())
            .limit(1)
        )
        return self.session.scalars(q).first()

    def record_confirmed_event(self, event: TrackEvent, risk: RiskAssessment, *, camera_id: int | None,
                               source_label: str, is_demo: bool) -> RecordResult:
        now = utcnow()
        duplicate = self.find_open_duplicate(camera_id, event.hazard_type)
        if duplicate is not None:
            previous = duplicate.severity
            escalated = self._apply_event(duplicate, event, risk, added_hits=event.total_hits, now=now)
            self._add_detections(duplicate, event, camera_id)
            self.audit.record("INCIDENT_MERGED", "incident_agent",
                              f"event track {event.track_id} merged into open incident {duplicate.id} "
                              f"(same camera and hazard within dedup window)",
                              entity_type="incident", entity_id=duplicate.id)
            return RecordResult(duplicate, created=False, escalated=escalated, previous_severity=previous)

        camera = self.session.get(Camera, camera_id) if camera_id is not None else None
        incident = Incident(
            incident_type=event.hazard_type,
            severity=risk.severity,
            risk_score=risk.score,
            status=IncidentStatus.OPEN,
            source=IncidentSource.DEMO_HEURISTIC if is_demo else IncidentSource.AI_MODEL,
            camera_id=camera_id,
            location_id=camera.location_id if camera else None,
            source_label=source_label[:255],
            description=self._describe(event, source_label, is_demo),
            detection_timestamp=now,
            last_detection_at=now,
            peak_confidence=event.max_confidence,
            frames_observed=event.total_hits,
        )
        self.session.add(incident)
        self.session.flush()
        self._add_detections(incident, event, camera_id)
        self.audit.record("INCIDENT_CREATED", "incident_agent",
                          f"{event.hazard_type.value} incident created; {risk.explain()}",
                          entity_type="incident", entity_id=incident.id)
        return RecordResult(incident, created=True, escalated=False)

    def update_from_event(self, incident_id: int, event: TrackEvent, risk: RiskAssessment,
                          added_hits: int) -> RecordResult | None:
        incident = self.session.get(Incident, incident_id)
        if incident is None:
            return None
        previous = incident.severity
        escalated = self._apply_event(incident, event, risk, added_hits=added_hits, now=utcnow())
        if escalated:
            self.audit.record("INCIDENT_ESCALATED", "incident_agent",
                              f"severity {previous.value} -> {incident.severity.value}; {risk.explain()}",
                              entity_type="incident", entity_id=incident.id)
        return RecordResult(incident, created=False, escalated=escalated, previous_severity=previous)

    def _apply_event(self, incident: Incident, event: TrackEvent, risk: RiskAssessment, *,
                     added_hits: int, now: datetime) -> bool:
        incident.last_detection_at = now
        incident.frames_observed = (incident.frames_observed or 0) + max(0, added_hits)
        incident.peak_confidence = max(incident.peak_confidence or 0.0, event.max_confidence)
        if incident.risk_score is None or risk.score > incident.risk_score:
            incident.risk_score = risk.score
        if risk.severity.rank > incident.severity.rank:  # severity only ever escalates automatically
            incident.severity = risk.severity
            return True
        return False

    def _add_detections(self, incident: Incident, event: TrackEvent, camera_id: int | None) -> None:
        now = utcnow()
        for s in event.samples:
            self.session.add(Detection(
                incident=incident, camera_id=camera_id, object_class=event.hazard_type.value,
                raw_label=s.raw_label[:64], confidence=round(s.confidence, 4),
                bbox=[round(v, 1) for v in s.bbox], frame_number=s.frame_index, video_time_s=s.time_s,
                is_demo=s.is_demo, timestamp=now,
            ))

    @staticmethod
    def _describe(event: TrackEvent, source_label: str, is_demo: bool) -> str:
        prefix = "[DEMO HEURISTIC - not a validated detection] " if is_demo else ""
        return (f"{prefix}{event.hazard_type.value.replace('_', ' ').title()} detected on {source_label}: "
                f"first seen at {event.first_time_s:.1f}s (frame {event.first_frame}), confirmed after "
                f"{event.total_hits} positive sampled frames, peak confidence {event.max_confidence:.2f}.")

    # ---------------------------------------------------------------- manual / CRUD
    def create_manual(self, *, hazard_type: HazardType, severity: Severity, description: str | None,
                      camera_id: int | None, location_id: int | None, user_id: int) -> Incident:
        if camera_id is not None and self.session.get(Camera, camera_id) is None:
            raise not_found("camera", camera_id)
        if location_id is not None and self.session.get(Location, location_id) is None:
            raise not_found("location", location_id)
        if location_id is None and camera_id is not None:
            location_id = self.session.get(Camera, camera_id).location_id
        now = utcnow()
        incident = Incident(
            incident_type=hazard_type, severity=severity, risk_score=None, status=IncidentStatus.OPEN,
            source=IncidentSource.MANUAL, camera_id=camera_id, location_id=location_id,
            description=description, source_label="manual report", detection_timestamp=now,
            last_detection_at=now, frames_observed=0,
        )
        self.session.add(incident)
        self.session.flush()
        self.audit.record("INCIDENT_REPORTED", "incident_agent", f"manual {hazard_type.value} report",
                          user_id=user_id, entity_type="incident", entity_id=incident.id)
        return incident

    def update(self, incident_id: int, *, user_id: int, status: IncidentStatus | None = None,
               severity: Severity | None = None, description: str | None = None) -> Incident:
        incident = self.get(incident_id)
        changes = []
        if status is not None and status != incident.status:
            if status not in ALLOWED_TRANSITIONS[incident.status]:
                raise AppError(409, "INVALID_STATUS_TRANSITION",
                               f"cannot change status from {incident.status.value} to {status.value}",
                               {"allowed": sorted(s.value for s in ALLOWED_TRANSITIONS[incident.status])})
            changes.append(f"status {incident.status.value} -> {status.value}")
            incident.status = status
        if severity is not None and severity != incident.severity:
            changes.append(f"severity {incident.severity.value} -> {severity.value} (operator override)")
            incident.severity = severity
        if description is not None and description != incident.description:
            changes.append("description updated")
            incident.description = description
        if not changes:
            raise bad_request("NO_CHANGES", "request does not change the incident")
        self.audit.record("INCIDENT_UPDATED", "incident_agent", "; ".join(changes), user_id=user_id,
                          entity_type="incident", entity_id=incident.id)
        self.session.commit()
        return incident

    def get(self, incident_id: int, *, with_relations: bool = False) -> Incident:
        if with_relations:
            q = (select(Incident).where(Incident.id == incident_id).options(
                selectinload(Incident.detections), selectinload(Incident.alerts),
                selectinload(Incident.response_actions), selectinload(Incident.camera),
                selectinload(Incident.location)))
            incident = self.session.scalars(q).first()
        else:
            incident = self.session.get(Incident, incident_id)
        if incident is None:
            raise not_found("incident", incident_id)
        return incident

    def list(self, filters: IncidentFilters, offset: int = 0, limit: int = 25) -> tuple[list[Incident], int]:
        q = select(Incident)
        f = filters
        if f.hazard_type is not None:
            q = q.where(Incident.incident_type == f.hazard_type)
        if f.severity is not None:
            q = q.where(Incident.severity == f.severity)
        if f.status is not None:
            q = q.where(Incident.status == f.status)
        elif f.active_only:
            q = q.where(Incident.status.in_(ACTIVE_INCIDENT_STATUSES))
        if f.camera_id is not None:
            q = q.where(Incident.camera_id == f.camera_id)
        if f.location_id is not None:
            q = q.where(Incident.location_id == f.location_id)
        date_from, date_to = as_utc(f.date_from), as_utc(f.date_to)  # compare in UTC (DB stores UTC)
        if date_from is not None:
            q = q.where(Incident.detection_timestamp >= date_from)
        if date_to is not None:
            q = q.where(Incident.detection_timestamp <= date_to)
        if date_from and date_to and date_from > date_to:
            raise bad_request("INVALID_DATE_RANGE", "date_from must be before date_to")
        total = self.session.scalar(select(func.count()).select_from(q.subquery())) or 0
        q = (q.options(selectinload(Incident.response_actions), selectinload(Incident.camera),
                       selectinload(Incident.location))
             .order_by(Incident.detection_timestamp.desc(), Incident.id.desc()).offset(offset).limit(limit))
        return list(self.session.scalars(q)), total


def log_pipeline_failure(session: Session, message: str, job_id: str | None = None) -> None:
    AuditAgent(session).record("PIPELINE_FAILED", "detection_service", message, status=LogStatus.FAILURE)
    session.commit()
