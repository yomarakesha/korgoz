"""Stores `EventRecord`s through the worker's `DatabaseWriter`.

The tracker-local track number is resolved to `tracks.id` in the writer thread:
the track row was submitted to the same writer earlier, so it already exists.
`location_id` is copied from the camera at the time of the event.
"""

from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Camera, Event, Track
from app.database.writer import DatabaseWriter
from app.events.engine import EventRecord


def _track_row_id(session: Session, camera_id: int, track_id: int) -> int | None:
    # Track numbers restart with the worker; the newest row is the current track.
    return session.scalar(
        select(Track.id)
        .where(Track.camera_id == camera_id, Track.track_identifier == str(track_id))
        .order_by(Track.id.desc())
        .limit(1)
    )


def _store(session: Session, record: EventRecord) -> None:
    camera = session.get(Camera, record.camera_id)
    if camera is None:
        return  # deleted while the worker was still running: its last events are moot
    metadata = dict(record.metadata)
    track_row = None
    if record.track_id is not None:
        metadata["track_identifier"] = str(record.track_id)
        track_row = _track_row_id(session, record.camera_id, record.track_id)
    session.add(
        Event(
            event_type=record.event_type,
            camera_id=record.camera_id,
            location_id=camera.location_id,
            track_id=track_row,
            person_id=record.person_id,
            timestamp=record.timestamp,
            confidence=record.confidence,
            metadata_=metadata,
        )
    )


class EventStore:
    """`EventEmitter` that persists events asynchronously."""

    def __init__(self, writer: DatabaseWriter) -> None:
        self._writer = writer

    def __call__(self, record: EventRecord) -> None:
        self._writer.submit(
            f"{record.event_type.value} event (camera {record.camera_id})",
            partial(_store, record=record),
        )
