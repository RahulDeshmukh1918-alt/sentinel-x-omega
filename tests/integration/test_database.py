"""Database models, relationships and constraints."""
import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import inspect, select  # noqa: E402
from sqlalchemy.exc import IntegrityError, StatementError  # noqa: E402

from backend.app.core.enums import (  # noqa: E402
    AlertType, HazardType, IncidentSource, IncidentStatus, Priority, Severity, SourceType,
)
from backend.app.models import Alert, Camera, Detection, Incident, Location, ResponseAction  # noqa: E402
from backend.app.models.base import utcnow  # noqa: E402

pytestmark = pytest.mark.integration


def make_incident(session, camera=None, **kw):
    now = utcnow()
    inc = Incident(incident_type=kw.get("incident_type", HazardType.FIRE), severity=kw.get("severity", Severity.HIGH),
                   risk_score=70.0, status=kw.get("status", IncidentStatus.OPEN), source=IncidentSource.AI_MODEL,
                   camera=camera, detection_timestamp=now, last_detection_at=now, frames_observed=5)
    session.add(inc)
    session.flush()
    return inc


def test_all_tables_created(db_engine):
    names = set(inspect(db_engine).get_table_names())
    assert {"users", "cameras", "locations", "incidents", "detections", "alerts", "response_actions",
            "system_logs"} <= names


def test_useful_indexes_exist(db_engine):
    idx = {i["name"] for i in inspect(db_engine).get_indexes("incidents")}
    assert "ix_incident_dedup" in idx


def test_relationships_and_cascade(db_session):
    loc = Location(name="Gate 1", latitude=18.52, longitude=73.85)
    cam = Camera(name="Cam A", source_type=SourceType.WEBCAM, source_uri="0", location=loc)
    db_session.add_all([loc, cam])
    inc = make_incident(db_session, cam)
    db_session.add_all([
        Detection(incident=inc, camera_id=cam.id, object_class="FIRE", confidence=0.9, bbox=[1, 2, 3, 4], frame_number=10),
        Alert(incident=inc, alert_type=AlertType.INCIDENT_CREATED, severity=Severity.HIGH, message="x"),
        ResponseAction(incident=inc, recommended_department="Fire Brigade", recommended_action="go", priority=Priority.P2),
    ])
    db_session.commit()
    assert inc.camera.location.name == "Gate 1"
    assert len(inc.detections) == 1 and inc.detections[0].bbox == [1, 2, 3, 4]
    assert inc.response_actions[0].dispatch_status == "NOT_DISPATCHED"

    db_session.delete(inc)
    db_session.commit()
    assert db_session.scalars(select(Detection)).all() == []
    assert db_session.scalars(select(Alert)).all() == []
    assert db_session.scalars(select(ResponseAction)).all() == []


def test_deleting_camera_keeps_incident_history(db_session):
    cam = Camera(name="Cam B", source_type=SourceType.WEBCAM, source_uri="1")
    db_session.add(cam)
    inc = make_incident(db_session, cam)
    db_session.commit()
    db_session.delete(cam)
    db_session.commit()
    db_session.refresh(inc)
    assert inc.camera_id is None


def test_unique_camera_name(db_session):
    db_session.add(Camera(name="Dup", source_type=SourceType.WEBCAM, source_uri="0"))
    db_session.commit()
    db_session.add(Camera(name="Dup", source_type=SourceType.WEBCAM, source_uri="1"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_location_coordinate_check_constraint(db_session):
    db_session.add(Location(name="Nowhere", latitude=123.0, longitude=0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enum_columns_reject_unknown_values(db_session):
    with pytest.raises((StatementError, LookupError, ValueError)):
        db_session.add(Camera(name="Bad", source_type="TELEPATHY", source_uri="0"))
        db_session.commit()
    db_session.rollback()


def test_timestamps_are_set(db_session):
    inc = make_incident(db_session)
    db_session.commit()
    assert inc.created_at is not None and inc.updated_at is not None
