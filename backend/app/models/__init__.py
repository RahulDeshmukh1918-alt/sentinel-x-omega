"""ORM models. Importing this package registers every table on ``Base.metadata``."""
from backend.app.models.alert import Alert
from backend.app.models.base import Base
from backend.app.models.camera import Camera
from backend.app.models.detection import Detection
from backend.app.models.incident import Incident
from backend.app.models.location import Location
from backend.app.models.response_action import ResponseAction
from backend.app.models.system_log import SystemLog
from backend.app.models.user import User

__all__ = [
    "Alert",
    "Base",
    "Camera",
    "Detection",
    "Incident",
    "Location",
    "ResponseAction",
    "SystemLog",
    "User",
]
