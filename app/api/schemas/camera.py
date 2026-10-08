from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.camera.stream import detect_source_kind
from app.camera.types import CameraStatus, SourceKind
from app.core.logging import redact
from app.database.models import Camera


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # USB index ("0"), RTSP/HTTP URL or video file path. Stored as-is, never returned.
    stream_url: str = Field(min_length=1, max_length=2048)
    location_id: int | None = None
    enabled: bool = True


class CameraUpdate(BaseModel):
    """Only the fields sent are changed. The stream URL can't be edited: re-create the camera."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    location_id: int | None = None
    enabled: bool | None = None


class CameraRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location_id: int | None
    enabled: bool
    status: CameraStatus
    source_kind: SourceKind
    stream_url_masked: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, camera: Camera) -> "CameraRead":
        return cls(
            id=camera.id,
            name=camera.name,
            location_id=camera.location_id,
            enabled=camera.enabled,
            status=camera.status,
            source_kind=detect_source_kind(camera.stream_url),
            stream_url_masked=redact(camera.stream_url),
            created_at=camera.created_at,
            updated_at=camera.updated_at,
        )
