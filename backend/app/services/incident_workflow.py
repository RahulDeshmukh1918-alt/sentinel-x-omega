"""DatabaseIncidentSink: the SQL-backed end of the pipeline.

For each confirmed event it runs, in one transaction:
Incident Management Agent -> Response Recommendation (persisted) -> Alert Agent -> Audit Agent.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session, sessionmaker

from backend.app.ai.postprocessor import TrackEvent
from backend.app.core.enums import AlertType, LogStatus
from backend.app.models import ResponseAction
from backend.app.services.alert_service import AlertAgent
from backend.app.services.audit_service import AuditAgent
from backend.app.services.incident_service import IncidentManagementAgent
from backend.app.services.pipeline import SourceContext
from backend.app.services.response_service import ResponseRecommendation, ResponseRecommendationAgent
from backend.app.services.risk_service import RiskAssessment

logger = logging.getLogger(__name__)

# SQLite allows one writer at a time; serialise writes from concurrent jobs.
_WRITE_LOCK = threading.Lock()


def persist_recommendations(session: Session, incident, recs: list[ResponseRecommendation]) -> list[ResponseAction]:
    actions = []
    for r in recs:
        action = ResponseAction(incident=incident, recommended_department=r.department,
                                recommended_action=r.action, priority=r.priority)
        session.add(action)
        actions.append(action)
    return actions


class DatabaseIncidentSink:
    def __init__(self, session_factory: sessionmaker[Session], dedup_window_seconds: int,
                 response_agent: ResponseRecommendationAgent | None = None):
        self.session_factory = session_factory
        self.dedup_window_seconds = dedup_window_seconds
        self.response_agent = response_agent or ResponseRecommendationAgent()
        self._hits_written: dict[int, int] = {}

    def on_confirmed(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment,
                     recommendations: list[ResponseRecommendation]) -> int | None:
        with _WRITE_LOCK, self.session_factory() as session:
            try:
                agent = IncidentManagementAgent(session, self.dedup_window_seconds)
                result = agent.record_confirmed_event(event, risk, camera_id=ctx.camera_id,
                                                      source_label=ctx.source_label, is_demo=event.is_demo)
                incident = result.incident
                alerts = AlertAgent(session)
                demo = " [DEMO]" if event.is_demo else ""
                if result.created:
                    persist_recommendations(session, incident, recommendations)
                    alerts.create_for_incident(
                        incident, AlertType.INCIDENT_CREATED,
                        f"{risk.severity.value} {event.hazard_type.value} detected on {ctx.source_label}"
                        f" (risk {risk.score:.0f}){demo}. Recommendation: {recommendations[0].department}."
                        if recommendations else f"{event.hazard_type.value} detected{demo}",
                    )
                elif result.escalated:
                    self._escalate(session, incident, result.previous_severity, ctx)
                session.commit()
                self._hits_written[incident.id] = event.total_hits
                return incident.id
            except Exception as exc:
                session.rollback()
                logger.exception("failed to persist confirmed event")
                self._log_failure(f"could not persist {event.hazard_type.value} event: {exc}")
                return None

    def on_updated(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment, incident_id: int) -> None:
        with _WRITE_LOCK, self.session_factory() as session:
            try:
                added = event.total_hits - self._hits_written.get(incident_id, event.total_hits)
                result = IncidentManagementAgent(session, self.dedup_window_seconds).update_from_event(
                    incident_id, event, risk, added_hits=added)
                if result is not None and result.escalated:
                    self._escalate(session, result.incident, result.previous_severity, ctx)
                session.commit()
                self._hits_written[incident_id] = event.total_hits
            except Exception:
                session.rollback()
                logger.exception("failed to update incident %s", incident_id)

    def on_ended(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment, incident_id: int) -> None:
        self.on_updated(ctx, event, risk, incident_id)
        with _WRITE_LOCK, self.session_factory() as session:
            AuditAgent(session).record(
                "EVENT_ENDED", "detection_service",
                f"{event.hazard_type.value} no longer observed on {ctx.source_label} after {event.last_time_s:.1f}s "
                "(incident stays open until an operator resolves it)",
                status=LogStatus.INFO, entity_type="incident", entity_id=incident_id)
            session.commit()

    def _escalate(self, session: Session, incident, previous, ctx: SourceContext) -> None:
        recs = self.response_agent.recommend(incident.incident_type, incident.severity)
        persist_recommendations(session, incident, recs)
        AlertAgent(session).create_for_incident(
            incident, AlertType.SEVERITY_ESCALATED,
            f"Incident #{incident.id} escalated {previous.value if previous else '?'} -> {incident.severity.value} "
            f"on {ctx.source_label} (risk {incident.risk_score:.0f}).",
        )

    def _log_failure(self, message: str) -> None:
        try:
            with self.session_factory() as session:
                AuditAgent(session).record("PERSIST_FAILED", "incident_workflow", message, status=LogStatus.FAILURE)
                session.commit()
        except Exception:  # pragma: no cover - last resort
            logger.exception("could not write failure audit log")
