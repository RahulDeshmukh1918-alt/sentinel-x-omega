"""Audit Agent: records processing and incident-management decisions in ``system_logs``."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.app.core.enums import LogStatus
from backend.app.models import SystemLog

logger = logging.getLogger("sentinel.audit")


class AuditAgent:
    def __init__(self, session: Session):
        self.session = session

    def record(self, action: str, module: str, message: str, *, status: LogStatus = LogStatus.SUCCESS,
               user_id: int | None = None, entity_type: str | None = None, entity_id: int | None = None) -> SystemLog:
        """Adds a log row to the current unit of work (the caller commits)."""
        entry = SystemLog(
            action=action, module=module, message=message[:2000], status=status,
            user_id=user_id, entity_type=entity_type, entity_id=entity_id,
        )
        self.session.add(entry)
        level = logging.WARNING if status in (LogStatus.FAILURE, LogStatus.WARNING) else logging.INFO
        logger.log(level, "%s/%s %s: %s", module, action, status.value, message)
        return entry
