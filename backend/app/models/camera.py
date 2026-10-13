from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.enums import CameraStatus, SourceType
from backend.app.models.base import Base, TimestampMixin, enum_column


class Camera(TimestampMixin, Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType), nullable=False)
    # For RTSP this may contain credentials; it is never returned unmasked by the API.
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[CameraStatus] = mapped_column(
        enum_column(CameraStatus), nullable=False, default=CameraStatus.UNKNOWN, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))

    location = relationship("Location", back_populates="cameras")
    incidents = relationship("Incident", back_populates="camera")
