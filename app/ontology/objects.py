"""Ontology objects (spec §8): Person, Camera, Location, Event, Session, Track.

Device is not modelled yet: the spec names it but defines no attributes, and
today every device is a camera.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.database import models
from app.events.types import EventType


@dataclass(frozen=True, slots=True)
class LocationObject:
    id: int
    name: str

    @classmethod
    def from_model(cls, row: models.Location) -> "LocationObject":
        return cls(id=row.id, name=row.name)


@dataclass(frozen=True, slots=True)
class CameraObject:
    id: int
    name: str
    location_id: int | None

    @classmethod
    def from_model(cls, row: models.Camera) -> "CameraObject":
        return cls(id=row.id, name=row.name, location_id=row.location_id)


@dataclass(frozen=True, slots=True)
class PersonObject:
    id: int
    name: str
    external_id: str | None

    @classmethod
    def from_model(cls, row: models.Person) -> "PersonObject":
        return cls(id=row.id, name=row.name, external_id=row.external_id)


@dataclass(frozen=True, slots=True)
class TrackObject:
    id: int
    camera_id: int
    track_identifier: str
    started_at: datetime
    ended_at: datetime | None

    @classmethod
    def from_model(cls, row: models.Track) -> "TrackObject":
        return cls(
            id=row.id,
            camera_id=row.camera_id,
            track_identifier=row.track_identifier,
            started_at=row.started_at,
            ended_at=row.ended_at,
        )


@dataclass(frozen=True, slots=True)
class SessionObject:
    id: int
    track_id: int
    camera_id: int
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None

    @classmethod
    def from_model(cls, row: models.TrackSession) -> "SessionObject":
        return cls(
            id=row.id,
            track_id=row.track_id,
            camera_id=row.camera_id,
            started_at=row.started_at,
            ended_at=row.ended_at,
            duration_seconds=row.duration_seconds,
        )


@dataclass(frozen=True, slots=True)
class EventObject:
    """An event with its relations resolved: detected_by Camera, occurred_at Location."""

    id: int
    event_type: EventType
    timestamp: datetime
    confidence: float | None
    camera: CameraObject
    location: LocationObject | None
    person_id: int | None
    track_id: int | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, row: models.Event) -> "EventObject":
        return cls(
            id=row.id,
            event_type=row.event_type,
            timestamp=row.timestamp,
            confidence=row.confidence,
            camera=CameraObject.from_model(row.camera),
            location=LocationObject.from_model(row.location) if row.location else None,
            person_id=row.person_id,
            track_id=row.track_id,
            metadata=dict(row.metadata_ or {}),
        )
