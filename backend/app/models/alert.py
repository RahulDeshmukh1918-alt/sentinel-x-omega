from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.enums import AlertStatus, AlertType, Severity
from backend.app.models.base import Base, CreatedAtMixin, enum_column


class Alert(CreatedAtMixin, Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_type: Mapped[AlertType] = mapped_column(enum_column(AlertType), nullable=False)
    severity: Mapped[Severity] = mapped_column(enum_column(Severity), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Alerts are shown on the dashboard only. No SMS/e-mail/dispatch integration exists.
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="DASHBOARD")
    status: Mapped[AlertStatus] = mapped_column(
        enum_column(AlertStatus), nullable=False, default=AlertStatus.UNACKNOWLEDGED, index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    incident = relationship("Incident", back_populates="alerts")
