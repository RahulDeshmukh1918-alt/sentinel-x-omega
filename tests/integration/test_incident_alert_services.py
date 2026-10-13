"""Incident Management Agent, Alert Agent and the database sink."""
from datetime import timedelta

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import select  # noqa: E402

from backend.app.ai.postprocessor import DetectionSample, EventKind, TrackEvent  # noqa: E402
from backend.app.core.enums import (  # noqa: E402
    AlertStatus, HazardType, IncidentSource, IncidentStatus, Severity, SourceType, UserRole,
)
from backend.app.core.errors import AppError  # noqa: E402
from backend.app.database import connection  # noqa: E402
from backend.app.models import Alert, Camera, Detection, Incident, ResponseAction, SystemLog  # noqa: E402
from backend.app.models.base import utcnow  # noqa: E402
from backend.app.services.alert_service import AlertAgent  # noqa: E402
from backend.app.services.incident_service import IncidentManagementAgent  # noqa: E402
from backend.app.services.incident_workflow import DatabaseIncidentSink  # noqa: E402
from backend.app.services.pipeline import SourceContext  # noqa: E402
from backend.app.services.response_service import ResponseRecommendationAgent  # noqa: E402
from backend.app.services.risk_service import RiskAssessmentAgent, RiskConfig  # noqa: E402

pytestmark = pytest.mark.integration


def event(hazard=HazardType.FIRE, hits=5, conf=0.8, track_id=1, kind=EventKind.CONFIRMED, demo=False):
    samples = tuple(DetectionSample(i * 5, i * 0.2, conf, (1.0, 2.0, 30.0, 40.0), "fire", demo) for i in range(hits))
    return TrackEvent(kind, track_id, hazard, 0, (hits - 1) * 5, 0.0, (hits - 1) * 0.2, hits, conf, conf, demo,
                      samples[-1], samples)


@pytest.fixture
def risk(settings):
    return RiskAssessmentAgent(RiskConfig.from_settings(settings))


@pytest.fixture
def camera(db_session):
    cam = Camera(name="Cam 1", source_type=SourceType.WEBCAM, source_uri="0")
    db_session.add(cam)
    db_session.commit()
    return cam


def test_confirmed_event_creates_incident_with_detections_and_audit(db_session, risk, camera):
    agent = IncidentManagementAgent(db_session, 300)
    r = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                     source_label="Cam 1", is_demo=False)
    db_session.commit()
    assert r.created and not r.escalated
    inc = r.incident
    assert inc.status == IncidentStatus.OPEN and inc.source == IncidentSource.AI_MODEL
    assert inc.frames_observed == 5 and inc.peak_confidence == 0.8
    assert len(db_session.scalars(select(Detection).where(Detection.incident_id == inc.id)).all()) == 5
    logs = db_session.scalars(select(SystemLog).where(SystemLog.entity_id == inc.id)).all()
    assert any(l.action == "INCIDENT_CREATED" and "risk=" in l.message for l in logs)


def test_demo_events_are_labelled(db_session, risk, camera):
    r = IncidentManagementAgent(db_session).record_confirmed_event(
        event(demo=True), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id, source_label="c", is_demo=True)
    assert r.incident.source == IncidentSource.DEMO_HEURISTIC
    assert r.incident.description.startswith("[DEMO HEURISTIC")


def test_duplicate_within_window_is_merged(db_session, risk, camera):
    agent = IncidentManagementAgent(db_session, 300)
    first = agent.record_confirmed_event(event(track_id=1), risk.assess(HazardType.FIRE, 0.6, 5),
                                         camera_id=camera.id, source_label="c", is_demo=False)
    db_session.commit()
    second = agent.record_confirmed_event(event(track_id=2, hits=10, conf=0.95), risk.assess(HazardType.FIRE, 0.95, 15),
                                          camera_id=camera.id, source_label="c", is_demo=False)
    db_session.commit()
    assert not second.created and second.incident.id == first.incident.id
    assert second.incident.frames_observed == 15
    assert db_session.scalar(select(Incident).where(Incident.id != first.incident.id)) is None


def test_different_hazard_or_camera_is_not_merged(db_session, risk, camera):
    agent = IncidentManagementAgent(db_session, 300)
    a = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                     source_label="c", is_demo=False)
    b = agent.record_confirmed_event(event(HazardType.SMOKE), risk.assess(HazardType.SMOKE, 0.8, 5),
                                     camera_id=camera.id, source_label="c", is_demo=False)
    c = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=None,
                                     source_label="upload", is_demo=False)
    assert len({a.incident.id, b.incident.id, c.incident.id}) == 3


def test_resolved_or_stale_incidents_are_not_merged(db_session, risk, camera):
    agent = IncidentManagementAgent(db_session, 300)
    first = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                         source_label="c", is_demo=False).incident
    first.status = IncidentStatus.RESOLVED
    db_session.commit()
    second = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                          source_label="c", is_demo=False).incident
    assert second.id != first.id
    second.last_detection_at = utcnow() - timedelta(seconds=301)
    db_session.commit()
    third = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                         source_label="c", is_demo=False).incident
    assert third.id not in (first.id, second.id)


def test_severity_escalates_but_never_auto_downgrades(db_session, risk, camera):
    agent = IncidentManagementAgent(db_session)
    low = risk.assess(HazardType.SMOKE, 0.5, 1)
    inc = agent.record_confirmed_event(event(HazardType.SMOKE), low, camera_id=camera.id, source_label="c",
                                       is_demo=False).incident
    high = risk.assess(HazardType.SMOKE, 1.0, 30)
    r = agent.update_from_event(inc.id, event(HazardType.SMOKE, hits=30), high, added_hits=25)
    assert r.escalated and inc.severity.rank > low.severity.rank
    r2 = agent.update_from_event(inc.id, event(HazardType.SMOKE), low, added_hits=1)
    assert not r2.escalated and inc.severity == high.severity


def test_status_transitions(db_session, risk, camera, create_user):
    user = create_user(UserRole.OPERATOR)
    agent = IncidentManagementAgent(db_session)
    inc = agent.record_confirmed_event(event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id,
                                       source_label="c", is_demo=False).incident
    db_session.commit()
    agent.update(inc.id, user_id=user.id, status=IncidentStatus.IN_PROGRESS)
    agent.update(inc.id, user_id=user.id, status=IncidentStatus.RESOLVED)
    with pytest.raises(AppError) as exc:
        agent.update(inc.id, user_id=user.id, status=IncidentStatus.IN_PROGRESS)
    assert exc.value.status_code == 409 and exc.value.code == "INVALID_STATUS_TRANSITION"
    with pytest.raises(AppError) as exc:
        agent.update(inc.id, user_id=user.id, status=IncidentStatus.RESOLVED)
    assert exc.value.code == "NO_CHANGES"
    agent.update(inc.id, user_id=user.id, status=IncidentStatus.OPEN)  # re-open allowed


def test_manual_incident(db_session, camera, create_user):
    user = create_user(UserRole.OPERATOR)
    inc = IncidentManagementAgent(db_session).create_manual(
        hazard_type=HazardType.PERSON_FALL, severity=Severity.HIGH, description="seen by guard",
        camera_id=camera.id, location_id=None, user_id=user.id)
    assert inc.source == IncidentSource.MANUAL and inc.risk_score is None
    with pytest.raises(AppError) as exc:
        IncidentManagementAgent(db_session).create_manual(hazard_type=HazardType.FIRE, severity=Severity.LOW,
                                                          description=None, camera_id=999, location_id=None,
                                                          user_id=user.id)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------- alerts
def test_alert_acknowledgement(db_session, risk, camera, create_user):
    user = create_user(UserRole.OPERATOR)
    inc = IncidentManagementAgent(db_session).record_confirmed_event(
        event(), risk.assess(HazardType.FIRE, 0.8, 5), camera_id=camera.id, source_label="c", is_demo=False).incident
    from backend.app.core.enums import AlertType

    alert = AlertAgent(db_session).create_for_incident(inc, AlertType.INCIDENT_CREATED, "fire!")
    db_session.commit()
    acked = AlertAgent(db_session).acknowledge(alert.id, user.id)
    assert acked.status == AlertStatus.ACKNOWLEDGED and acked.acknowledged_by == user.id
    assert acked.acknowledged_at is not None
    with pytest.raises(AppError) as exc:
        AlertAgent(db_session).acknowledge(alert.id, user.id)
    assert exc.value.status_code == 409
    with pytest.raises(AppError) as exc:
        AlertAgent(db_session).acknowledge(12345, user.id)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------- database sink (pipeline boundary)
def test_database_sink_creates_incident_alert_and_recommendation(db_engine, settings, risk, camera):
    sink = DatabaseIncidentSink(connection.get_session_factory(), settings.incident_dedup_window_seconds)
    ctx = SourceContext(camera.id, "Cam 1")
    assessment = risk.assess(HazardType.ROAD_ACCIDENT, 0.9, 15)
    recs = ResponseRecommendationAgent().recommend(HazardType.ROAD_ACCIDENT, assessment.severity)
    iid = sink.on_confirmed(ctx, event(HazardType.ROAD_ACCIDENT), assessment, recs)
    assert iid is not None
    with connection.get_session_factory()() as s:
        depts = [a.recommended_department for a in s.scalars(select(ResponseAction).where(ResponseAction.incident_id == iid))]
        assert "Ambulance / EMS" in depts and "Traffic Police" in depts
        alerts = s.scalars(select(Alert).where(Alert.incident_id == iid)).all()
        assert len(alerts) == 1 and alerts[0].status == AlertStatus.UNACKNOWLEDGED

    # same camera + hazard again: merged, no second incident and no second creation alert
    iid2 = sink.on_confirmed(ctx, event(HazardType.ROAD_ACCIDENT, track_id=99), assessment, recs)
    assert iid2 == iid
    with connection.get_session_factory()() as s:
        assert len(s.scalars(select(Incident)).all()) == 1
        assert len(s.scalars(select(Alert)).all()) == 1
