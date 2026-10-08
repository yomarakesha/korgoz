"""One shared scenario for analytics tests (SQLite unit tests and PostgreSQL integration).

All times UTC, on 2026-01-01:
    track 1  camera 1  09:00-09:10  person 1 recognised
    track 2  camera 1  09:05-09:06  person 2 recognised
    track 3  camera 2  10:30-open   unknown (last seen 10:59:58)
    track 4  camera 1  11:00-11:30  person 1 recognised again
Camera 1 is in location 1 ("Hall"), camera 2 has no location.
"""

from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.database.models import Camera, Event, Location, Person, Track, TrackSession
from app.events.types import EventType as E

DAY = datetime(2026, 1, 1, tzinfo=UTC)


def t(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute, seconds=second)


TRACKS = [
    # id, camera, start, end (None = still open), last_seen, person (None = unknown)
    (1, 1, t(9), t(9, 10), t(9, 10), 1),
    (2, 1, t(9, 5), t(9, 6), t(9, 6), 2),
    (3, 2, t(10, 30), None, t(10, 59, 58), None),
    (4, 1, t(11), t(11, 30), t(11, 30), 1),
]


def _event(
    kind: E,
    at: datetime,
    person_id: int | None = None,
    *,
    camera: int,
    location: int | None,
    track_id: int,
) -> Event:
    return Event(
        event_type=kind,
        camera_id=camera,
        location_id=location,
        track_id=track_id,
        person_id=person_id,
        timestamp=at,
        metadata_={},
    )


def seed(engine: Engine) -> None:
    with Session(engine) as session:
        session.add_all(
            [
                Location(id=1, name="Hall"),
                Person(id=1, name="Alice"),
                Person(id=2, name="Bob"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Camera(id=1, name="entrance", stream_url="0", location_id=1),
                Camera(id=2, name="yard", stream_url="1"),
            ]
        )
        session.flush()
        for track_id, camera, start, end, seen, person in TRACKS:
            location = 1 if camera == 1 else None
            session.add(
                Track(
                    id=track_id,
                    camera_id=camera,
                    track_identifier=str(track_id),
                    started_at=start,
                    ended_at=end,
                    last_seen_at=seen,
                )
            )
            session.flush()

            event = partial(_event, camera=camera, location=location, track_id=track_id)
            session.add(event(E.PERSON_ENTERED, start))
            if person is not None:
                session.add(event(E.PERSON_RECOGNIZED, start + timedelta(seconds=2), person))
            else:
                session.add(event(E.PERSON_UNKNOWN, start + timedelta(seconds=5)))
            if end is not None:
                session.add(event(E.PERSON_LEFT, end, person))
                session.add(
                    TrackSession(
                        track_id=track_id,
                        camera_id=camera,
                        started_at=start,
                        ended_at=end,
                        duration_seconds=(end - start).total_seconds(),
                    )
                )
        session.commit()
