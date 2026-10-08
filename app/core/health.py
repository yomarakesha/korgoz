"""Health checks for external components.

Each check returns a status string and never raises: a broken dependency must
show up in /health, not crash the API.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

import httpx
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.camera.types import CameraStatus
from app.config import Settings, VisionMode
from app.database.models import Camera
from app.database.session import ping_database

logger = logging.getLogger(__name__)


class ComponentStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class HealthReport:
    status: str
    database: ComponentStatus
    qdrant: ComponentStatus
    ai: ComponentStatus
    cameras: int

    @property
    def is_healthy(self) -> bool:
        return self.status == "ok"


def check_database(engine: Engine) -> ComponentStatus:
    try:
        ping_database(engine)
    except Exception as exc:  # any driver/network error means "unavailable"
        logger.warning("Database health check failed: %s", type(exc).__name__)
        return ComponentStatus.UNAVAILABLE
    return ComponentStatus.OK


def check_qdrant(settings: Settings) -> ComponentStatus:
    # Imported here: the factory pulls in OpenCV/ONNX, which /health itself doesn't need.
    from app.pipeline.factory import build_vector_store

    store = build_vector_store(settings, timeout_seconds=settings.health_check_timeout_seconds)
    return ComponentStatus.OK if store.health_check() else ComponentStatus.UNAVAILABLE


def count_online_cameras(engine: Engine) -> int:
    """Cameras reported ONLINE by the worker process (via the database)."""
    try:
        with Session(engine) as session:
            query = select(func.count(Camera.id)).where(Camera.status == CameraStatus.ONLINE)
            return session.scalar(query) or 0
    except Exception as exc:
        logger.warning("Camera status query failed: %s", type(exc).__name__)
        return 0


def check_ai(settings: Settings) -> ComponentStatus:
    """AI models live in the worker process; ask its status endpoint."""
    url = f"http://{settings.live_view_host}:{settings.live_view_port}/status"
    try:
        response = httpx.get(url, timeout=settings.health_check_timeout_seconds)
        response.raise_for_status()
        ai_status = response.json()["ai"]["status"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Worker status check failed: %s", type(exc).__name__)
        return ComponentStatus.UNAVAILABLE
    if ai_status == "ok":
        return ComponentStatus.OK
    if ai_status == "not_configured":
        return ComponentStatus.NOT_CONFIGURED
    return ComponentStatus.UNAVAILABLE


def build_report(engine: Engine, settings: Settings) -> HealthReport:
    database = check_database(engine)
    qdrant = check_qdrant(settings)
    ai = check_ai(settings)
    cameras = count_online_cameras(engine) if database is ComponentStatus.OK else 0

    # Without the database the API can't serve anything useful. Qdrant matters
    # only in recognition mode; a missing worker/AI degrades but doesn't fail the API.
    qdrant_required = settings.vision_mode is VisionMode.RECOGNITION
    if database is not ComponentStatus.OK:
        status = "error"
    elif (
        qdrant_required and qdrant is not ComponentStatus.OK
    ) or ai is ComponentStatus.UNAVAILABLE:
        status = "degraded"
    else:
        status = "ok"
    return HealthReport(status=status, database=database, qdrant=qdrant, ai=ai, cameras=cameras)
