from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.app.schemas.common import UTCDateTime


class DailyCount(BaseModel):
    date: str
    count: int


class DashboardSummary(BaseModel):
    generated_at: UTCDateTime
    active_incidents: int
    critical_incidents: int  # active incidents with CRITICAL severity
    online_cameras: int
    total_cameras: int
    unacknowledged_alerts: int
    resolved_incidents: int
    total_incidents: int
    demo_incidents: int
    by_hazard: dict[str, int]
    by_severity: dict[str, int]
    by_status: dict[str, int]
    daily: list[DailyCount]
    average_risk_by_hazard: dict[str, float | None]
    model: dict[str, Any]
    active_jobs: int
