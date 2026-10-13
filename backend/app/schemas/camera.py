from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.core.enums import CameraStatus, SourceType
from backend.app.core.validators import mask_credentials
from backend.app.schemas.common import ORMModel, UTCDateTime


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationOut(ORMModel):
    id: int
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None
    created_at: UTCDateTime


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_type: SourceType
    source_uri: str = Field(
        min_length=1, max_length=500,
        description="WEBCAM: device index ('0'); RTSP: stream URL; FILE: path relative to data/sample_videos",
    )
    location_id: int | None = None


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    source_type: SourceType | None = None
    source_uri: str | None = Field(default=None, min_length=1, max_length=500)
    location_id: int | None = None
    status: CameraStatus | None = None


class CameraOut(BaseModel):
    id: int
    name: str
    source_type: SourceType
    source_display: str  # credentials masked; the raw URI is never returned
    location_id: int | None
    location_name: str | None
    status: CameraStatus
    last_seen_at: UTCDateTime | None
    last_error: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    monitoring_job_id: str | None = None

    @classmethod
    def from_camera(cls, cam, job_id: str | None = None) -> "CameraOut":
        return cls(
            id=cam.id, name=cam.name, source_type=cam.source_type, source_display=mask_credentials(cam.source_uri),
            location_id=cam.location_id, location_name=cam.location.name if cam.location else None,
            status=cam.status, last_seen_at=cam.last_seen_at, last_error=cam.last_error,
            created_at=cam.created_at, updated_at=cam.updated_at, monitoring_job_id=job_id,
        )
