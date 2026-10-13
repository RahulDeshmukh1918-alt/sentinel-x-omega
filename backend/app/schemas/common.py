from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict

T = TypeVar("T")


def _ensure_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(_ensure_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(cls, items: list[Any], total: int, page: int, page_size: int) -> "Page":
        return cls(items=items, total=total, page=page, page_size=page_size,
                   pages=max(1, math.ceil(total / page_size)) if page_size else 1)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class MessageResponse(BaseModel):
    message: str
