from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from backend.app.api.deps import get_app_settings, get_current_user, get_job_manager, require_role
from backend.app.core.config import Settings
from backend.app.core.enums import SourceType, UserRole
from backend.app.core.errors import AppError, not_found
from backend.app.core.validators import SourceValidationError, safe_path_within, sanitise_filename
from backend.app.database.connection import get_db
from backend.app.models import Camera, User
from backend.app.schemas.detection import DetectionStatusOut, JobOut, StartDetectionRequest, StopDetectionRequest
from backend.app.services.detection_service import DetectionJobManager, model_status_summary

router = APIRouter(prefix="/detection", tags=["detection"])

_CHUNK = 1024 * 1024
_ALLOWED_CONTENT_TYPES_PREFIX = ("video/", "application/octet-stream")


@router.get("/status", response_model=DetectionStatusOut)
def detection_status(jobs: DetectionJobManager = Depends(get_job_manager), _: User = Depends(get_current_user)):
    """Model status (READY / DEMO_MODE / MODEL_NOT_AVAILABLE) and recent jobs."""
    all_jobs = jobs.list()
    return DetectionStatusOut(model=model_status_summary(jobs.provider),
                              active_jobs=sum(1 for j in all_jobs if j.is_active),
                              jobs=[JobOut(**j.as_dict()) for j in all_jobs])


@router.post("/analyze", response_model=JobOut, status_code=202)
def analyze_upload(
    file: UploadFile = File(..., description="video file (mp4/avi/mov/mkv/webm)"),
    camera_id: int | None = Form(None, description="optional camera the footage belongs to (enables de-duplication)"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    jobs: DetectionJobManager = Depends(get_job_manager),
    _: User = Depends(require_role(UserRole.OPERATOR)),
):
    """Upload a video and analyse it in the background. Poll ``GET /detection/jobs/{id}`` for progress."""
    original = sanitise_filename(file.filename or "upload.mp4")
    ext = ("." + original.rsplit(".", 1)[-1].lower()) if "." in original else ""
    if ext not in settings.allowed_video_extensions:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE",
                       f"'{ext or 'no extension'}' is not allowed; use one of {settings.allowed_video_extensions}")
    if file.content_type and not file.content_type.startswith(_ALLOWED_CONTENT_TYPES_PREFIX):
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", f"content type {file.content_type} is not a video")
    if camera_id is not None and db.get(Camera, camera_id) is None:
        raise not_found("camera", camera_id)

    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex}{ext}"  # server-chosen name: no user-controlled paths
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(_CHUNK):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise AppError(413, "FILE_TOO_LARGE", f"upload exceeds {settings.max_upload_mb} MB")
                out.write(chunk)
        if written == 0:
            raise AppError(400, "EMPTY_FILE", "uploaded file is empty")
        job = jobs.submit(kind="upload", source_type=SourceType.FILE, source_uri=str(dest), source_label=original,
                          camera_id=camera_id, delete_source_after=True)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
    return JobOut(**job.as_dict())


@router.post("/start", response_model=JobOut, status_code=202)
def start_detection(body: StartDetectionRequest, db: Session = Depends(get_db),
                    settings: Settings = Depends(get_app_settings),
                    jobs: DetectionJobManager = Depends(get_job_manager),
                    _: User = Depends(require_role(UserRole.OPERATOR))):
    """Start monitoring a configured camera (webcam, RTSP stream or sample-video file)."""
    cam = db.get(Camera, body.camera_id)
    if cam is None:
        raise not_found("camera", body.camera_id)
    uri = cam.source_uri
    if cam.source_type == SourceType.FILE:
        try:
            uri = str(safe_path_within(settings.sample_video_path, cam.source_uri))
        except SourceValidationError as exc:
            raise AppError(422, "INVALID_CAMERA_SOURCE", str(exc))
    job = jobs.submit(kind="camera", source_type=cam.source_type, source_uri=uri, source_label=cam.name,
                      camera_id=cam.id)
    return JobOut(**job.as_dict())


@router.post("/stop", response_model=JobOut)
def stop_detection(body: StopDetectionRequest, jobs: DetectionJobManager = Depends(get_job_manager),
                   _: User = Depends(require_role(UserRole.OPERATOR))):
    """Request a running job to stop (by ``job_id`` or ``camera_id``). The job finishes its current frame."""
    if body.job_id:
        job = jobs.stop(body.job_id)
    elif body.camera_id:
        active = jobs.active_for_camera(body.camera_id)
        if active is None:
            raise AppError(409, "JOB_NOT_RUNNING", f"camera {body.camera_id} is not being monitored")
        job = jobs.stop(active.id)
    else:
        raise AppError(422, "VALIDATION_ERROR", "provide job_id or camera_id")
    return JobOut(**job.as_dict())


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, jobs: DetectionJobManager = Depends(get_job_manager), _: User = Depends(get_current_user)):
    return JobOut(**jobs.get(job_id).as_dict())


@router.get("/jobs/{job_id}/snapshot", responses={200: {"content": {"image/jpeg": {}}}})
def job_snapshot(job_id: str, jobs: DetectionJobManager = Depends(get_job_manager),
                 _: User = Depends(get_current_user)):
    """Latest analysed frame with detection boxes drawn (a real processed frame, not a simulated feed)."""
    job = jobs.get(job_id)
    if job.snapshot_jpeg is None:
        raise AppError(404, "SNAPSHOT_NOT_AVAILABLE", "no frame has been processed yet")
    return Response(content=job.snapshot_jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
