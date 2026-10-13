from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_app_settings, get_job_manager
from backend.app.core.config import Settings
from backend.app.database.connection import check_database
from backend.app.services.detection_service import DetectionJobManager

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness and dependency check (public)")
def health(settings: Settings = Depends(get_app_settings),
           jobs: DetectionJobManager = Depends(get_job_manager)) -> dict:
    db_ok = check_database()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "ok" if db_ok else "unavailable",
        "detector_mode": settings.detector_mode,
        # Existence check only - does not load the model.
        "model_weights_present": settings.weights_path.is_file(),
        "active_jobs": sum(1 for j in jobs.list() if j.is_active),
        "time": datetime.now(timezone.utc).isoformat(),
    }
