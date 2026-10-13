from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, utcnow


class Detection(Base):
    """A sampled model detection that contributed to an incident."""

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), index=True)
    object_class: Mapped[str] = mapped_column(String(32), nullable=False)  # HazardType value
    raw_label: Mapped[str | None] = mapped_column(String(64))  # class name emitted by the detector
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[list] = mapped_column(JSON, nullable=False)  # [x1, y1, x2, y2] in original-frame pixels
    frame_number: Mapped[int] = mapped_column(Integer, nullable=False)
    video_time_s: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    incident = relationship("Incident", back_populates="detections")
