"""Consistent error envelope used by every API endpoint.

Every error response has the shape::

    {"error": {"code": "INCIDENT_NOT_FOUND", "message": "...", "details": {...}}}
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers

    def to_dict(self) -> dict:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def not_found(entity: str, entity_id: Any) -> AppError:
    return AppError(404, f"{entity.upper()}_NOT_FOUND", f"{entity.capitalize()} {entity_id} not found")


def conflict(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(409, code, message, details)


def bad_request(code: str, message: str, details: Any | None = None) -> AppError:
    return AppError(400, code, message, details)
