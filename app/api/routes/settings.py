"""Read-only view of the running configuration for the dashboard's Settings page.

Only non-secret values: no database / Qdrant / camera URLs, no keys, no host names.
Settings are changed in `.env` and applied by restarting the API and the worker.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.api.dependencies import SettingsDep
from app.config import VisionMode

router = APIRouter(tags=["settings"])


class PublicSettings(BaseModel):
    app_name: str
    version: str
    environment: str
    vision_mode: VisionMode
    person_detector_model: str
    detection_interval: int
    person_confidence_threshold: float
    tracking_enabled: bool
    track_max_lost_seconds: float
    face_match_threshold: float
    face_min_size: int
    face_registration_min_size: int
    recognition_interval_seconds: float
    events_enabled: bool
    event_cooldown_seconds: float
    unknown_after_attempts: int
    analytics_timezone: str
    camera_max_fps: float | None
    live_view_enabled: bool


@router.get("/settings", response_model=PublicSettings)
def public_settings(settings: SettingsDep) -> PublicSettings:
    values = settings.model_dump(include=set(PublicSettings.model_fields))
    return PublicSettings(
        **values,
        version=__version__,
        person_detector_model=settings.person_detector_model_path.name,
    )
