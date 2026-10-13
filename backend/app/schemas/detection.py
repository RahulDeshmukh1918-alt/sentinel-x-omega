from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.app.core.enums import JobStatus, SourceType
from backend.app.schemas.common import UTCDateTime


class StartDetectionRequest(BaseModel):
    camera_id: int = Field(gt=0)


class StopDetectionRequest(BaseModel):
    job_id: str | None = Field(default=None, min_length=4, max_length=40)
    camera_id: int | None = Field(default=None, gt=0)


class JobOut(BaseModel):
    id: str
    kind: str
    source_type: SourceType
    source: str
    camera_id: int | None
    status: JobStatus
    is_demo: bool
    created_at: UTCDateTime
    started_at: UTCDateTime | None
    finished_at: UTCDateTime | None
    frames_read: int
    frames_processed: int
    total_frames: int | None
    progress: float | None
    video_time_s: float
    incident_ids: list[int]
    recent_detections: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    has_snapshot: bool


class DetectionStatusOut(BaseModel):
    model: dict[str, Any]
    active_jobs: int
    jobs: list[JobOut]
