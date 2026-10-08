from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select

from app.api.dependencies import DbSession
from app.api.schemas.event import EventRead
from app.database.models import Event
from app.events.types import EventType

router = APIRouter(prefix="/events", tags=["events"])


class EventFilters:
    """Query parameters shared by the list and the count endpoints."""

    def __init__(
        self,
        camera_id: int | None = None,
        location_id: int | None = None,
        person_id: int | None = None,
        track_id: Annotated[int | None, Query(description="tracks.id")] = None,
        event_type: Annotated[
            list[EventType] | None, Query(description="repeat to select several types")
        ] = None,
        since: Annotated[datetime | None, Query(description="at or after (ISO 8601)")] = None,
        until: Annotated[datetime | None, Query(description="before (ISO 8601)")] = None,
    ) -> None:
        self.conditions: list[ColumnElement[bool]] = []
        if camera_id is not None:
            self.conditions.append(Event.camera_id == camera_id)
        if location_id is not None:
            self.conditions.append(Event.location_id == location_id)
        if person_id is not None:
            self.conditions.append(Event.person_id == person_id)
        if track_id is not None:
            self.conditions.append(Event.track_id == track_id)
        if event_type:
            self.conditions.append(Event.event_type.in_(event_type))
        if since is not None:
            self.conditions.append(Event.timestamp >= since)
        if until is not None:
            self.conditions.append(Event.timestamp < until)


Filters = Annotated[EventFilters, Depends()]


@router.get("", response_model=list[EventRead])
def list_events(
    db: DbSession,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventRead]:
    """Events, newest first."""
    query = (
        select(Event)
        .where(*filters.conditions)
        .order_by(Event.timestamp.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [EventRead.from_model(e) for e in db.scalars(query)]


class EventCount(BaseModel):
    count: int


@router.get("/count", response_model=EventCount)
def count_events(db: DbSession, filters: Filters) -> EventCount:
    """Number of events matching the same filters as `GET /events` (e.g. "events today")."""
    return EventCount(count=db.scalar(select(func.count(Event.id)).where(*filters.conditions)) or 0)


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: int, db: DbSession) -> EventRead:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventRead.from_model(event)
