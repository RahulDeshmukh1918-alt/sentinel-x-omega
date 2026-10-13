"""Application configuration.

Settings are read from environment variables (optionally from a ``.env`` file in
the project root). Every field below can be overridden with an environment
variable of the same name in upper case, e.g. ``DETECTOR_MODE=demo``.

Dict/list fields accept JSON, e.g.
``HAZARD_SEVERITY_FACTORS={"FIRE": 0.95, "SMOKE": 0.5}``. List fields also
accept comma-separated values, e.g. ``CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500``.

A deliberately small loader is used instead of ``pydantic-settings`` to keep
the dependency list short; validation is still done by Pydantic.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.core.enums import HazardType

PROJECT_ROOT = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "CHANGE_ME_IN_DOTENV"

# Maps class names emitted by a *custom-trained* model to supported hazards.
# A stock COCO model (e.g. yolov8n.pt) has none of these classes, so it will be
# reported as MODEL_NOT_AVAILABLE rather than silently "detecting" hazards.
DEFAULT_CLASS_MAP: dict[str, str] = {
    "fire": "FIRE",
    "flame": "FIRE",
    "smoke": "SMOKE",
    "accident": "ROAD_ACCIDENT",
    "vehicle_accident": "ROAD_ACCIDENT",
    "car_crash": "ROAD_ACCIDENT",
    "spark": "ELECTRICAL_SPARK",
    "electrical_spark": "ELECTRICAL_SPARK",
    "fall": "PERSON_FALL",
    "fallen_person": "PERSON_FALL",
    "person_fall": "PERSON_FALL",
}

# Prototype design parameters (0..1). NOT measured values — see docs/architecture.
DEFAULT_SEVERITY_FACTORS: dict[str, float] = {
    "FIRE": 0.90,
    "ROAD_ACCIDENT": 0.85,
    "PERSON_FALL": 0.75,
    "ELECTRICAL_SPARK": 0.70,
    "SMOKE": 0.60,
}

_JSON_FIELDS = {"model_class_map", "hazard_severity_factors", "confidence_thresholds"}
_LIST_FIELDS = {"cors_origins", "allowed_video_extensions"}


class Settings(BaseModel):
    # --- application -----------------------------------------------------
    app_name: str = "SENTINEL-X OMEGA"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"])
    serve_frontend: bool = True
    auto_create_tables: bool = True

    # --- database --------------------------------------------------------
    database_url: str = "sqlite:///./data/sentinel.db"

    # --- auth ------------------------------------------------------------
    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=5, le=24 * 60)

    # --- detection model ---------------------------------------------------
    detector_mode: Literal["auto", "yolo", "demo"] = "auto"
    model_weights_path: str = "ml/models/hazard_yolo.pt"
    model_class_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_CLASS_MAP))
    inference_device: str = "cpu"
    model_min_confidence: float = Field(default=0.10, ge=0.0, le=1.0)

    # --- frame processing -----------------------------------------------------
    frame_stride: int = Field(default=5, ge=1, le=120)
    max_frame_width: int = Field(default=960, ge=160, le=3840)
    max_frames_per_job: int = Field(default=20000, ge=1)

    # --- validation ------------------------------------------------------
    default_confidence_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    confidence_thresholds: dict[str, float] = Field(default_factory=dict)
    temporal_window_frames: int = Field(default=8, ge=1, le=500)
    temporal_min_hits: int = Field(default=5, ge=1, le=500)
    temporal_end_after_missed: int = Field(default=10, ge=1, le=1000)

    # --- risk model (prototype design parameters) -------------------------------
    risk_weight_confidence: float = Field(default=0.40, ge=0.0)
    risk_weight_persistence: float = Field(default=0.30, ge=0.0)
    risk_weight_severity: float = Field(default=0.30, ge=0.0)
    persistence_saturation_frames: int = Field(default=15, ge=1)
    hazard_severity_factors: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SEVERITY_FACTORS))
    severity_band_low_max: float = 30
    severity_band_medium_max: float = 55
    severity_band_high_max: float = 75

    # --- incidents ---------------------------------------------------------
    incident_dedup_window_seconds: int = Field(default=300, ge=0)
    incident_update_every_n_hits: int = Field(default=10, ge=1)
    max_detections_stored_per_event: int = Field(default=20, ge=1, le=500)

    # --- uploads / jobs ---------------------------------------------------
    max_upload_mb: int = Field(default=200, ge=1, le=4096)
    allowed_video_extensions: list[str] = Field(default_factory=lambda: [".mp4", ".avi", ".mov", ".mkv", ".webm"])
    upload_dir: str = "data/uploads"
    sample_video_dir: str = "data/sample_videos"
    keep_uploaded_videos: bool = False  # uploaded footage is deleted after analysis by default
    max_concurrent_jobs: int = Field(default=2, ge=1, le=16)
    snapshot_every_n_processed: int = Field(default=3, ge=1)

    # ------------------------------------------------------------------
    @field_validator("model_class_map")
    @classmethod
    def _check_class_map(cls, v: dict[str, str]) -> dict[str, str]:
        cleaned = {}
        for label, hazard in v.items():
            HazardType(hazard)  # raises ValueError on unknown hazard
            cleaned[label.strip().lower()] = hazard
        return cleaned

    @field_validator("hazard_severity_factors")
    @classmethod
    def _check_factors(cls, v: dict[str, float]) -> dict[str, float]:
        for hazard, factor in v.items():
            HazardType(hazard)
            if not 0.0 <= float(factor) <= 1.0:
                raise ValueError(f"severity factor for {hazard} must be within 0..1")
        missing = {h.value for h in HazardType} - set(v)
        if missing:
            raise ValueError(f"hazard_severity_factors missing: {sorted(missing)}")
        return v

    @field_validator("confidence_thresholds")
    @classmethod
    def _check_thresholds(cls, v: dict[str, float]) -> dict[str, float]:
        for hazard, thr in v.items():
            HazardType(hazard)
            if not 0.0 <= float(thr) <= 1.0:
                raise ValueError(f"confidence threshold for {hazard} must be within 0..1")
        return v

    @field_validator("allowed_video_extensions")
    @classmethod
    def _normalise_ext(cls, v: list[str]) -> list[str]:
        return [e.lower() if e.startswith(".") else f".{e.lower()}" for e in v]

    @model_validator(mode="after")
    def _cross_checks(self) -> "Settings":
        if self.risk_weight_confidence + self.risk_weight_persistence + self.risk_weight_severity <= 0:
            raise ValueError("at least one risk weight must be > 0")
        if not (0 <= self.severity_band_low_max < self.severity_band_medium_max < self.severity_band_high_max <= 100):
            raise ValueError("severity bands must satisfy 0 <= low < medium < high <= 100")
        if self.temporal_min_hits > self.temporal_window_frames:
            raise ValueError("temporal_min_hits cannot exceed temporal_window_frames")
        if self.environment == "production" and self.jwt_secret_key == DEFAULT_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set in production")
        return self

    # ------------------------------------------------------------------
    def resolve_path(self, value: str | Path) -> Path:
        """Resolve a configured path relative to the project root."""
        p = Path(value)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def upload_path(self) -> Path:
        return self.resolve_path(self.upload_dir)

    @property
    def sample_video_path(self) -> Path:
        return self.resolve_path(self.sample_video_dir)

    @property
    def weights_path(self) -> Path:
        return self.resolve_path(self.model_weights_path)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def threshold_for(self, hazard: HazardType) -> float:
        return float(self.confidence_thresholds.get(hazard.value, self.default_confidence_threshold))

    def public_view(self) -> dict:
        """Configuration safe to show in the dashboard (no secrets, no full paths)."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "environment": self.environment,
            "detector_mode": self.detector_mode,
            "model_weights_file": Path(self.model_weights_path).name,
            "frame_stride": self.frame_stride,
            "max_frame_width": self.max_frame_width,
            "default_confidence_threshold": self.default_confidence_threshold,
            "confidence_thresholds": {h.value: self.threshold_for(h) for h in HazardType},
            "temporal_window_frames": self.temporal_window_frames,
            "temporal_min_hits": self.temporal_min_hits,
            "temporal_end_after_missed": self.temporal_end_after_missed,
            "risk_weights": {
                "confidence": self.risk_weight_confidence,
                "persistence": self.risk_weight_persistence,
                "severity": self.risk_weight_severity,
            },
            "persistence_saturation_frames": self.persistence_saturation_frames,
            "hazard_severity_factors": self.hazard_severity_factors,
            "severity_bands": {
                "LOW": [0, self.severity_band_low_max],
                "MEDIUM": [self.severity_band_low_max, self.severity_band_medium_max],
                "HIGH": [self.severity_band_medium_max, self.severity_band_high_max],
                "CRITICAL": [self.severity_band_high_max, 100],
            },
            "incident_dedup_window_seconds": self.incident_dedup_window_seconds,
            "max_upload_mb": self.max_upload_mb,
            "allowed_video_extensions": self.allowed_video_extensions,
            "external_dispatch": "NOT IMPLEMENTED - recommendations only",
        }


# ----------------------------------------------------------------------
def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def _coerce(name: str, raw: str):
    if name in _JSON_FIELDS:
        return json.loads(raw)
    if name in _LIST_FIELDS:
        raw = raw.strip()
        if raw.startswith("["):
            return json.loads(raw)
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def load_settings(env: dict[str, str] | None = None, dotenv_path: Path | None = None) -> Settings:
    """Build settings from (in priority order) ``env`` / os.environ, then .env."""
    source: dict[str, str] = _read_dotenv(dotenv_path or PROJECT_ROOT / ".env")
    source.update(os.environ if env is None else env)
    data = {}
    for name in Settings.model_fields:
        key = name.upper()
        if key in source:
            data[name] = _coerce(name, source[key])
    settings = Settings.model_validate(data)
    if settings.jwt_secret_key == DEFAULT_JWT_SECRET:
        logger.warning("JWT_SECRET_KEY is using the placeholder value; set it in .env")
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
