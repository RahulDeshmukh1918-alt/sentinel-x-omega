from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.enums import HazardType, IncidentSource, IncidentStatus, Severity
from backend.app.models.base import Base, TimestampMixin, enum_column


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # used by duplicate-incident lookup
        Index("ix_incident_dedup", "camera_id", "incident_type", "status", "last_detection_at"),
        Index("ix_incident_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_type: Mapped[HazardType] = mapped_column(enum_column(HazardType), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(enum_column(Severity), nullable=False, index=True)
    # NULL for manual reports, which have no model-derived score
    risk_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus), nullable=False, default=IncidentStatus.OPEN, index=True
    )
    source: Mapped[IncidentSource] = mapped_column(enum_column(IncidentSource), nullable=False)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str | None] = mapped_column(String(255))  # e.g. uploaded file name
    detection_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detection_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    peak_confidence: Mapped[float | None] = mapped_column(Float)
    frames_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    camera = relationship("Camera", back_populates="incidents")
    location = relationship("Location")
    detections = relationship(
        "Detection", back_populates="incident", cascade="all, delete-orphan", order_by="Detection.id"
    )
    alerts = relationship("Alert", back_populates="incident", cascade="all, delete-orphan", order_by="Alert.id")
    response_actions = relationship(
        "ResponseAction", back_populates="incident", cascade="all, delete-orphan", order_by="ResponseAction.id"
    )
