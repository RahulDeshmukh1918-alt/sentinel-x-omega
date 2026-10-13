from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.api.deps import get_app_settings, get_current_user, get_job_manager, require_role
from backend.app.core.config import Settings
from backend.app.core.enums import ACTIVE_INCIDENT_STATUSES, CameraStatus, SourceType, UserRole
from backend.app.core.errors import AppError, conflict, not_found
from backend.app.core.validators import SourceValidationError, mask_credentials, validate_source
from backend.app.database.connection import get_db
from backend.app.models import Camera, Incident, Location, User
from backend.app.schemas.camera import CameraCreate, CameraOut, CameraUpdate, LocationCreate, LocationOut
from backend.app.services.audit_service import AuditAgent
from backend.app.services.detection_service import DetectionJobManager

router = APIRouter(tags=["cameras"])


def _validated_uri(settings: Settings, source_type: SourceType, uri: str) -> str:
    try:
        return validate_source(source_type, uri, sample_dir=settings.sample_video_path,
                               allowed_ext=settings.allowed_video_extensions)
    except SourceValidationError as exc:
        raise AppError(422, "INVALID_CAMERA_SOURCE", str(exc))


def _get_camera(db: Session, camera_id: int) -> Camera:
    cam = db.scalars(select(Camera).where(Camera.id == camera_id).options(selectinload(Camera.location))).first()
    if cam is None:
        raise not_found("camera", camera_id)
    return cam


def _check_location(db: Session, location_id: int | None) -> None:
    if location_id is not None and db.get(Location, location_id) is None:
        raise not_found("location", location_id)


def _out(cam: Camera, jobs: DetectionJobManager) -> CameraOut:
    job = jobs.active_for_camera(cam.id)
    return CameraOut.from_camera(cam, job.id if job else None)


# ------------------------------------------------------------------ cameras
@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(status: CameraStatus | None = Query(None), db: Session = Depends(get_db),
                 jobs: DetectionJobManager = Depends(get_job_manager), _: User = Depends(get_current_user)):
    q = select(Camera).options(selectinload(Camera.location)).order_by(Camera.id)
    if status is not None:
        q = q.where(Camera.status == status)
    return [_out(c, jobs) for c in db.scalars(q)]


@router.post("/cameras", response_model=CameraOut, status_code=201)
def create_camera(body: CameraCreate, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings),
                  jobs: DetectionJobManager = Depends(get_job_manager),
                  user: User = Depends(require_role(UserRole.ADMIN))):
    uri = _validated_uri(settings, body.source_type, body.source_uri)
    _check_location(db, body.location_id)
    cam = Camera(name=body.name.strip(), source_type=body.source_type, source_uri=uri, location_id=body.location_id)
    db.add(cam)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("CAMERA_NAME_EXISTS", f"a camera named '{body.name}' already exists")
    AuditAgent(db).record("CAMERA_CREATED", "cameras", f"camera '{cam.name}' ({cam.source_type.value} "
                          f"{mask_credentials(uri)})", user_id=user.id, entity_type="camera", entity_id=cam.id)
    db.commit()
    return _out(_get_camera(db, cam.id), jobs)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db), jobs: DetectionJobManager = Depends(get_job_manager),
               _: User = Depends(get_current_user)):
    return _out(_get_camera(db, camera_id), jobs)


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraUpdate, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_app_settings), jobs: DetectionJobManager = Depends(get_job_manager),
                  user: User = Depends(require_role(UserRole.ADMIN))):
    cam = _get_camera(db, camera_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise AppError(400, "NO_CHANGES", "request body contains no fields to update")
    if jobs.active_for_camera(camera_id) and ({"source_type", "source_uri"} & data.keys()):
        raise conflict("DETECTION_ALREADY_RUNNING", "stop monitoring before changing the camera source")
    if "source_type" in data or "source_uri" in data:
        stype = data.get("source_type") or cam.source_type
        if "source_uri" not in data:
            raise AppError(422, "INVALID_CAMERA_SOURCE", "source_uri is required when changing source_type")
        cam.source_type, cam.source_uri = stype, _validated_uri(settings, stype, data["source_uri"])
    if "location_id" in data:
        _check_location(db, data["location_id"])
        cam.location_id = data["location_id"]
    if data.get("name"):
        cam.name = data["name"].strip()
    if data.get("status"):
        cam.status = data["status"]
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("CAMERA_NAME_EXISTS", f"a camera named '{data.get('name')}' already exists")
    AuditAgent(db).record("CAMERA_UPDATED", "cameras", f"camera {camera_id} updated: {sorted(data)}",
                          user_id=user.id, entity_type="camera", entity_id=camera_id)
    db.commit()
    db.refresh(cam)
    return _out(_get_camera(db, camera_id), jobs)


@router.delete("/cameras/{camera_id}", status_code=204, response_class=Response)
def delete_camera(camera_id: int, db: Session = Depends(get_db), jobs: DetectionJobManager = Depends(get_job_manager),
                  user: User = Depends(require_role(UserRole.ADMIN))):
    cam = _get_camera(db, camera_id)
    if jobs.active_for_camera(camera_id):
        raise conflict("DETECTION_ALREADY_RUNNING", "stop monitoring before deleting the camera")
    name = cam.name
    db.delete(cam)  # incidents keep their history; camera_id becomes NULL
    AuditAgent(db).record("CAMERA_DELETED", "cameras", f"camera '{name}' deleted", user_id=user.id,
                          entity_type="camera", entity_id=camera_id)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ locations
@router.get("/locations", tags=["locations"])
def list_locations(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    active = dict(db.execute(
        select(Incident.location_id, func.count(Incident.id))
        .where(Incident.status.in_(ACTIVE_INCIDENT_STATUSES), Incident.location_id.is_not(None))
        .group_by(Incident.location_id)).all())
    cams = dict(db.execute(select(Camera.location_id, func.count(Camera.id)).group_by(Camera.location_id)).all())
    out = []
    for loc in db.scalars(select(Location).order_by(Location.name)):
        item = LocationOut.model_validate(loc).model_dump(mode="json")
        item["active_incidents"] = active.get(loc.id, 0)
        item["camera_count"] = cams.get(loc.id, 0)
        out.append(item)
    return out


@router.post("/locations", response_model=LocationOut, status_code=201, tags=["locations"])
def create_location(body: LocationCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.ADMIN))):
    loc = Location(**body.model_dump())
    db.add(loc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("LOCATION_NAME_EXISTS", f"a location named '{body.name}' already exists")
    AuditAgent(db).record("LOCATION_CREATED", "cameras", f"location '{loc.name}'", user_id=user.id,
                          entity_type="location", entity_id=loc.id)
    db.commit()
    return loc
