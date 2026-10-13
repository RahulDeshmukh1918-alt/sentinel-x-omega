"""Shared enumerations.

These live in ``core`` (not ``models``) so the pure-Python pipeline modules
(risk scoring, temporal validation, response recommendation) can use them
without importing SQLAlchemy.
"""
from __future__ import annotations

from enum import Enum


class HazardType(str, Enum):
    FIRE = "FIRE"
    SMOKE = "SMOKE"
    ROAD_ACCIDENT = "ROAD_ACCIDENT"
    ELECTRICAL_SPARK = "ELECTRICAL_SPARK"
    PERSON_FALL = "PERSON_FALL"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


ACTIVE_INCIDENT_STATUSES = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.IN_PROGRESS)


class IncidentSource(str, Enum):
    AI_MODEL = "AI_MODEL"              # produced by a trained detection model
    DEMO_HEURISTIC = "DEMO_HEURISTIC"  # produced by the labelled demo detector
    MANUAL = "MANUAL"                  # reported by an operator


class AlertStatus(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AlertType(str, Enum):
    INCIDENT_CREATED = "INCIDENT_CREATED"
    SEVERITY_ESCALATED = "SEVERITY_ESCALATED"
    MANUAL_REPORT = "MANUAL_REPORT"


class Priority(str, Enum):
    P1 = "P1"  # most urgent
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ResponseActionStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"


class CameraStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


class SourceType(str, Enum):
    FILE = "FILE"
    WEBCAM = "WEBCAM"
    RTSP = "RTSP"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class LogStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INFO = "INFO"
    WARNING = "WARNING"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ModelStatus(str, Enum):
    READY = "READY"                              # trained model loaded and verified
    DEMO_MODE = "DEMO_MODE"                      # labelled heuristic detector in use
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"  # no usable model; detection disabled
