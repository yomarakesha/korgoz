from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Camera, Event, Location, Track
from app.database.writer import DatabaseWriter
from app.events.engine import EventRecord
from app.events.store import EventStore
from app.events.types import EventType

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Location(id=1, name="Hall"))
        session.add(Camera(id=1, name="entrance", stream_url="0", location_id=1))
        # An old track with the same tracker number (before a worker restart).
        session.add(Track(id=1, camera_id=1, track_identifier="4", started_at=T0, last_seen_at=T0))
        session.commit()
    yield engine
    engine.dispose()


def test_event_gets_the_newest_track_row_and_the_camera_location(engine: Engine) -> None:
    writer = DatabaseWriter(engine)
    writer.start()
    later = T0 + timedelta(hours=1)
    # Submitted to the same writer before the event, like TrackStore does.
    writer.submit(
        "track",
        lambda s: s.add(
            Track(id=2, camera_id=1, track_identifier="4", started_at=later, last_seen_at=later)
        ),
    )
    store = EventStore(writer)
    store(EventRecord(EventType.PERSON_ENTERED, camera_id=1, timestamp=later, track_id=4))
    store(EventRecord(EventType.CAMERA_OFFLINE, camera_id=1, timestamp=later))
    writer.stop()

    with Session(engine) as session:
        entered, offline = session.scalars(select(Event).order_by(Event.id)).all()
    assert entered.track_id == 2
    assert entered.location_id == 1
    assert entered.metadata_ == {"track_identifier": "4"}
    assert offline.track_id is None
    assert offline.event_type is EventType.CAMERA_OFFLINE
