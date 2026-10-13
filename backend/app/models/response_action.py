from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.enums import Priority, ResponseActionStatus
from backend.app.models.base import Base, TimestampMixin, enum_column


class ResponseAction(TimestampMixin, Base):
    __tablename__ = "response_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    recommended_department: Mapped[str] = mapped_column(String(100), nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), nullable=False)
    status: Mapped[ResponseActionStatus] = mapped_column(
        enum_column(ResponseActionStatus), nullable=False, default=ResponseActionStatus.RECOMMENDED
    )
    # Always NOT_DISPATCHED: this prototype has no external emergency-dispatch integration.
    dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_DISPATCHED")

    incident = relationship("Incident", back_populates="response_actions")
