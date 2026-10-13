"""Detection service: detector lifecycle and background detection jobs.

Inference runs in worker threads so long videos and live streams never block
the FastAPI event loop. Each job owns its ``VideoSource`` and DB sessions and
always releases them, whether it completes, is stopped, or fails.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2

from backend.app.ai.detector import BaseDetector, DetectorInfo, build_detector
from backend.app.ai.video_source import VideoSource, VideoSourceError
from backend.app.core.config import Settings
from backend.app.core.enums import CameraStatus, JobStatus, LogStatus, ModelStatus, SourceType
from backend.app.core.errors import AppError
from backend.app.database import connection
from backend.app.models import Camera
from backend.app.models.base import utcnow
from backend.app.services.audit_service import AuditAgent
from backend.app.services.incident_workflow import DatabaseIncidentSink
from backend.app.services.pipeline import HazardPipeline, PipelineConfig, PipelineStats, SourceContext
from backend.app.services.response_service import ResponseRecommendationAgent
from backend.app.services.risk_service import RiskAssessmentAgent, RiskConfig

logger = logging.getLogger(__name__)


class DetectorProvider:
    """Builds the detector lazily (first use), once, thread-safely."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._detector: BaseDetector | None = None
        self._info: DetectorInfo | None = None

    def get(self) -> tuple[BaseDetector | None, DetectorInfo]:
        with self._lock:
            if self._info is None:
                s = self.settings
                self._detector, self._info = build_detector(
                    s.detector_mode, s.weights_path, s.model_class_map, s.inference_device, s.model_min_confidence)
                logger.info("detector resolved: %s (%s)", self._info.status.value, self._info.message)
            return self._detector, self._info


@dataclass
class DetectionJob:
    id: str
    kind: str                      # "upload" | "camera"
    source_type: SourceType
    source_uri: str = field(repr=False)
    source_label: str
    camera_id: int | None = None
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    is_demo: bool = False
    frames_processed: int = 0
    frames_read: int = 0
    total_frames: int | None = None
    video_time_s: float = 0.0
    incident_ids: list[int] = field(default_factory=list)
    recent_detections: deque = field(default_factory=lambda: deque(maxlen=20))
    delete_source_after: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    snapshot_jpeg: bytes | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def is_active(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    def as_dict(self) -> dict:
        progress = None
        if self.total_frames:
            progress = round(min(1.0, self.frames_read / self.total_frames), 3)
        return {
            "id": self.id, "kind": self.kind, "source_type": self.source_type.value, "source": self.source_label,
            "camera_id": self.camera_id, "status": self.status.value, "is_demo": self.is_demo,
            "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
            "frames_read": self.frames_read, "frames_processed": self.frames_processed,
            "total_frames": self.total_frames, "progress": progress, "video_time_s": self.video_time_s,
            "incident_ids": list(self.incident_ids), "recent_detections": list(self.recent_detections),
            "error_code": self.error_code, "error_message": self.error_message,
            "has_snapshot": self.snapshot_jpeg is not None,
        }


class DetectionJobManager:
    MAX_HISTORY = 50

    def __init__(self, settings: Settings, provider: DetectorProvider | None = None):
        self.settings = settings
        self.provider = provider or DetectorProvider(settings)
        self._jobs: dict[str, DetectionJob] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ queries
    def list(self) -> list[DetectionJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def get(self, job_id: str) -> DetectionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise AppError(404, "JOB_NOT_FOUND", f"detection job {job_id} not found")
        return job

    def active_for_camera(self, camera_id: int) -> DetectionJob | None:
        return next((j for j in self._jobs.values() if j.camera_id == camera_id and j.is_active), None)

    # ------------------------------------------------------------------ control
    def submit(self, *, kind: str, source_type: SourceType, source_uri: str, source_label: str,
               camera_id: int | None = None, delete_source_after: bool = False) -> DetectionJob:
        detector, info = self.provider.get()
        if detector is None:
            raise AppError(503, "MODEL_NOT_AVAILABLE", info.message, {"model_status": info.status.value})
        with self._lock:
            active = [j for j in self._jobs.values() if j.is_active]
            if len(active) >= self.settings.max_concurrent_jobs:
                raise AppError(429, "TOO_MANY_JOBS",
                               f"at most {self.settings.max_concurrent_jobs} detection jobs can run at once")
            if camera_id is not None and any(j.camera_id == camera_id for j in active):
                raise AppError(409, "DETECTION_ALREADY_RUNNING", f"camera {camera_id} is already being monitored")
            job = DetectionJob(id=uuid.uuid4().hex[:12], kind=kind, source_type=source_type, source_uri=source_uri,
                               source_label=source_label, camera_id=camera_id, is_demo=detector.is_demo,
                               delete_source_after=delete_source_after)
            self._jobs[job.id] = job
            self._trim_history()
        job.thread = threading.Thread(target=self._run, args=(job, detector), name=f"detect-{job.id}", daemon=True)
        job.thread.start()
        return job

    def stop(self, job_id: str) -> DetectionJob:
        job = self.get(job_id)
        if not job.is_active:
            raise AppError(409, "JOB_NOT_RUNNING", f"job {job_id} is already {job.status.value}")
        job.stop_event.set()
        return job

    def stop_all(self, timeout: float = 5.0) -> None:
        for job in list(self._jobs.values()):
            job.stop_event.set()
        for job in list(self._jobs.values()):
            if job.thread is not None:
                job.thread.join(timeout=timeout)

    def _trim_history(self) -> None:
        finished = sorted((j for j in self._jobs.values() if not j.is_active), key=lambda j: j.created_at)
        while len(self._jobs) > self.MAX_HISTORY and finished:
            self._jobs.pop(finished.pop(0).id, None)

    # ------------------------------------------------------------------ worker
    def _run(self, job: DetectionJob, detector: BaseDetector) -> None:
        s = self.settings
        session_factory = connection.get_session_factory()
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        self._audit(session_factory, "DETECTION_STARTED",
                    f"job {job.id} started on {job.source_label} using {detector.name}"
                    + (" (DEMO MODE)" if detector.is_demo else ""), camera_id=job.camera_id)

        pipeline = HazardPipeline(detector, RiskAssessmentAgent(RiskConfig.from_settings(s)),
                                  ResponseRecommendationAgent(), PipelineConfig.from_settings(s))
        sink = DatabaseIncidentSink(session_factory, s.incident_dedup_window_seconds)
        ctx = SourceContext(camera_id=job.camera_id, source_label=job.source_label, job_id=job.id)

        def on_progress(stats: PipelineStats, kept, frame_index: int, time_s: float) -> None:
            job.frames_processed, job.frames_read, job.video_time_s = stats.frames_processed, stats.frames_read, time_s
            job.incident_ids = list(stats.incident_ids)
            for d in kept:
                job.recent_detections.append({
                    "hazard_type": d.hazard_type.value, "confidence": round(d.confidence, 3),
                    "bbox": [round(v, 1) for v in d.bbox], "frame": frame_index, "video_time_s": time_s,
                    "detected_at": datetime.now(timezone.utc).isoformat(), "is_demo": d.is_demo,
                })

        def on_snapshot(image) -> None:
            ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                job.snapshot_jpeg = buf.tobytes()

        source = VideoSource(job.source_type, job.source_uri)
        try:
            source.open()
            job.total_frames = source.frame_count
            self._set_camera_status(session_factory, job.camera_id, CameraStatus.ONLINE, None)
            stats = pipeline.run(source, sink, ctx, stop_event=job.stop_event, on_progress=on_progress,
                                 on_snapshot=on_snapshot, snapshot_every=s.snapshot_every_n_processed)
            job.incident_ids = list(stats.incident_ids)
            job.status = JobStatus.STOPPED if stats.stopped_early else JobStatus.COMPLETED
            self._audit(session_factory, "DETECTION_FINISHED",
                        f"job {job.id} {job.status.value.lower()}: {stats.frames_processed} frames analysed, "
                        f"{stats.events_confirmed} confirmed events, incidents {stats.incident_ids}",
                        camera_id=job.camera_id)
        except VideoSourceError as exc:
            job.status, job.error_code, job.error_message = JobStatus.FAILED, exc.code, exc.message
            new_status = CameraStatus.OFFLINE if exc.code in ("CAMERA_UNAVAILABLE", "STREAM_LOST") else CameraStatus.ERROR
            self._set_camera_status(session_factory, job.camera_id, new_status, exc.message)
            self._audit(session_factory, "DETECTION_FAILED", f"job {job.id}: {exc.code} {exc.message}",
                        status=LogStatus.FAILURE, camera_id=job.camera_id)
        except Exception as exc:  # keep the worker from dying silently
            logger.exception("detection job %s crashed", job.id)
            job.status, job.error_code, job.error_message = JobStatus.FAILED, "PIPELINE_ERROR", str(exc)[:300]
            self._audit(session_factory, "DETECTION_FAILED", f"job {job.id}: {exc}", status=LogStatus.FAILURE,
                        camera_id=job.camera_id)
        finally:
            source.release()
            job.finished_at = datetime.now(timezone.utc)
            if job.delete_source_after and not s.keep_uploaded_videos:
                Path(job.source_uri).unlink(missing_ok=True)

    @staticmethod
    def _set_camera_status(session_factory, camera_id: int | None, status: CameraStatus, error: str | None) -> None:
        if camera_id is None:
            return
        try:
            with session_factory() as session:
                cam = session.get(Camera, camera_id)
                if cam is not None:
                    cam.status = status
                    cam.last_error = error[:255] if error else None
                    if status == CameraStatus.ONLINE:
                        cam.last_seen_at = utcnow()
                    session.commit()
        except Exception:
            logger.exception("could not update camera %s status", camera_id)

    @staticmethod
    def _audit(session_factory, action: str, message: str, status: LogStatus = LogStatus.INFO,
               camera_id: int | None = None) -> None:
        try:
            with session_factory() as session:
                AuditAgent(session).record(action, "detection_service", message, status=status,
                                           entity_type="camera" if camera_id else None, entity_id=camera_id)
                session.commit()
        except Exception:
            logger.exception("could not write audit log")


def model_status_summary(provider: DetectorProvider) -> dict:
    _, info = provider.get()
    d = info.as_dict()
    d["detection_enabled"] = info.status != ModelStatus.MODEL_NOT_AVAILABLE
    return d
