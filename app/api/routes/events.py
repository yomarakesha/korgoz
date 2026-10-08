from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.schemas.event import EventRead
from app.database.models import Event
from app.events.types import EventType

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
def list_events(
    db: DbSession,
    camera_id: int | None = None,
    location_id: int | None = None,
    person_id: int | None = None,
    track_id: Annotated[int | None, Query(description="tracks.id")] = None,
    event_type: Annotated[
        list[EventType] | None, Query(description="repeat to select several types")
    ] = None,
    since: Annotated[datetime | None, Query(description="at or after (ISO 8601)")] = None,
    until: Annotated[datetime | None, Query(description="before (ISO 8601)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventRead]:
    """Events, newest first."""
    query = select(Event)
    if camera_id is not None:
        query = query.where(Event.camera_id == camera_id)
    if location_id is not None:
        query = query.where(Event.location_id == location_id)
    if person_id is not None:
        query = query.where(Event.person_id == person_id)
    if track_id is not None:
        query = query.where(Event.track_id == track_id)
    if event_type:
        query = query.where(Event.event_type.in_(event_type))
    if since is not None:
        query = query.where(Event.timestamp >= since)
    if until is not None:
        query = query.where(Event.timestamp < until)
    query = query.order_by(Event.timestamp.desc(), Event.id.desc()).limit(limit).offset(offset)
    return [EventRead.from_model(e) for e in db.scalars(query)]


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: int, db: DbSession) -> EventRead:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventRead.from_model(event)
