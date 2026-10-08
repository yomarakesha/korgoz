"""Ontology relations (spec §8) answered with SQL.

Person  ─generated──────→ Event     events.person_id
Event   ─detected_by────→ Camera    events.camera_id
Event   ─occurred_at────→ Location  events.location_id
Track   ─belongs_to─────→ Camera    tracks.camera_id
Person  ─associated_with→ Track     a PERSON_RECOGNIZED event links them
Session ─contains───────→ Event     same track, inside the session interval
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models import Event, Track, TrackSession
from app.events.types import EventType
from app.ontology.objects import CameraObject, EventObject, LocationObject, TrackObject


class Relation(StrEnum):
    GENERATED = "generated"
    DETECTED_BY = "detected_by"
    OCCURRED_AT = "occurred_at"
    BELONGS_TO = "belongs_to"
    ASSOCIATED_WITH = "associated_with"
    CONTAINS = "contains"


def _with_relations(query: Select[Event]) -> Select[Event]:
    return query.options(selectinload(Event.camera), selectinload(Event.location))


class Ontology:
    def __init__(self, session: Session) -> None:
        self.session = session

    # Person ─associated_with→ Track
    def tracks_of_person(self, person_id: int) -> list[TrackObject]:
        query = (
            select(Track)
            .where(Track.id.in_(self._associated_track_ids(person_id)))
            .order_by(Track.started_at)
        )
        return [TrackObject.from_model(t) for t in self.session.scalars(query)]

    def _associated_track_ids(self, person_id: int) -> Select[int | None]:
        return select(Event.track_id).where(
            Event.person_id == person_id,
            Event.event_type == EventType.PERSON_RECOGNIZED,
            Event.track_id.is_not(None),
        )

    # Person ─generated→ Event (directly, or through a track associated with the person)
    def events_of_person(
        self,
        person_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventObject]:
        query = select(Event).where(
            or_(
                Event.person_id == person_id,
                Event.track_id.in_(self._associated_track_ids(person_id)),
            )
        )
        if since is not None:
            query = query.where(Event.timestamp >= since)
        if until is not None:
            query = query.where(Event.timestamp < until)
        query = query.order_by(Event.timestamp.desc(), Event.id.desc()).limit(limit).offset(offset)
        return [EventObject.from_model(e) for e in self.session.scalars(_with_relations(query))]

    # Event ─detected_by→ Camera, Event ─occurred_at→ Location
    def camera_of(self, event: EventObject) -> CameraObject:
        return event.camera

    def location_of(self, event: EventObject) -> LocationObject | None:
        return event.location

    # Session ─contains→ Event
    def events_in_session(self, session_id: int) -> list[EventObject]:
        stay = self.session.get(TrackSession, session_id)
        if stay is None:
            return []
        query = select(Event).where(
            Event.track_id == stay.track_id, Event.timestamp >= stay.started_at
        )
        if stay.ended_at is not None:
            query = query.where(Event.timestamp <= stay.ended_at)
        query = query.order_by(Event.timestamp, Event.id)
        return [EventObject.from_model(e) for e in self.session.scalars(_with_relations(query))]
