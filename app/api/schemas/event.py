from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.database.models import Event
from app.events.types import EventType
from app.ontology.objects import EventObject


class EventRead(BaseModel):
    id: int
    event_type: EventType
    timestamp: datetime
    camera_id: int
    location_id: int | None
    person_id: int | None
    track_id: int | None  # tracks.id (the live-view number is metadata.track_identifier)
    confidence: float | None
    metadata: dict[str, Any]

    @classmethod
    def from_model(cls, event: Event) -> "EventRead":
        return cls(
            id=event.id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            camera_id=event.camera_id,
            location_id=event.location_id,
            person_id=event.person_id,
            track_id=event.track_id,
            confidence=event.confidence,
            metadata=dict(event.metadata_ or {}),
        )


class NamedRef(BaseModel):
    id: int
    name: str


class TimelineEntry(BaseModel):
    """One step of a person's history: what happened, where (camera, location), when."""

    event_id: int
    event_type: EventType
    timestamp: datetime
    confidence: float | None
    camera: NamedRef
    location: NamedRef | None
    track_id: int | None

    @classmethod
    def from_object(cls, event: EventObject) -> "TimelineEntry":
        return cls(
            event_id=event.id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            confidence=event.confidence,
            camera=NamedRef(id=event.camera.id, name=event.camera.name),
            location=(
                NamedRef(id=event.location.id, name=event.location.name) if event.location else None
            ),
            track_id=event.track_id,
        )
