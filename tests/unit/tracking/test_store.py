from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Camera, TrackSession
from app.database.models import Track as TrackRow
from app.detection.base import BoundingBox
from app.pipeline.types import FrameAnalysis
from app.tracking.store import TrackStore
from app.tracking.tracker import TrackedObject

from ..camera.helpers import wait_until
from ..pipeline.fakes import make_frame

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    """File-backed SQLite: the store thread and the test get separate connections.

    The shared in-memory engine (one connection for all threads) let a read in the
    test roll back the store thread's open transaction, which made tests flaky.
    """
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'tracks.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def tracked(track_id: int, seen: datetime) -> TrackedObject:
    return TrackedObject(track_id, BoundingBox(0, 0, 10, 30), 0.9, started_at=T0, last_seen_at=seen)


def add_camera(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Camera(id=1, name="cam", stream_url="0"))
        session.commit()


def sessions(engine: Engine) -> list[TrackSession]:
    with Session(engine) as session:
        return list(session.scalars(select(TrackSession)))


def rows(engine: Engine) -> list[TrackRow]:
    with Session(engine) as session:
        return list(session.scalars(select(TrackRow).order_by(TrackRow.id)))


def test_track_lifecycle_is_persisted(sqlite_engine: Engine) -> None:
    add_camera(sqlite_engine)
    store = TrackStore(sqlite_engine, flush_interval_seconds=0.05)
    store.start([1])
    try:
        frame = make_frame(0)
        store(FrameAnalysis(frame=frame, tracks=[tracked(7, T0)], tracks_started=[tracked(7, T0)]))
        assert wait_until(lambda: len(rows(sqlite_engine)) == 1)

        later = T0 + timedelta(seconds=4)
        store(FrameAnalysis(frame=frame, tracks=[tracked(7, later)]))
        assert wait_until(lambda: rows(sqlite_engine)[0].last_seen_at.replace(tzinfo=UTC) == later)

        end = T0 + timedelta(seconds=6)
        store(FrameAnalysis(frame=frame, tracks_ended=[tracked(7, end)]))
    finally:
        store.stop()
    row = rows(sqlite_engine)[0]
    assert row.track_identifier == "7"
    assert row.camera_id == 1
    assert row.ended_at is not None and row.ended_at.replace(tzinfo=UTC) == end
    stay = sessions(sqlite_engine)[0]
    assert stay.track_id == row.id
    assert stay.camera_id == 1
    assert stay.duration_seconds == 6


def test_orphaned_tracks_are_closed_on_start(sqlite_engine: Engine) -> None:
    add_camera(sqlite_engine)
    seen = T0 + timedelta(seconds=30)
    with Session(sqlite_engine) as session:
        session.add(TrackRow(camera_id=1, track_identifier="3", started_at=T0, last_seen_at=seen))
        session.commit()
    store = TrackStore(sqlite_engine)
    store.start([1])
    store.stop()
    row = rows(sqlite_engine)[0]
    assert row.ended_at is not None and row.ended_at.replace(tzinfo=UTC) == seen
    assert [s.duration_seconds for s in sessions(sqlite_engine)] == [30]


def test_database_outage_does_not_raise() -> None:
    broken = create_engine("postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    store = TrackStore(broken, flush_interval_seconds=0.05)
    store.start([1])
    frame = make_frame(0)
    store(FrameAnalysis(frame=frame, tracks=[tracked(1, T0)], tracks_started=[tracked(1, T0)]))
    store.end_tracks(1, [tracked(1, T0)])
    store.stop()


def test_tracks_of_a_deleted_camera_are_skipped(sqlite_engine: Engine) -> None:
    store = TrackStore(sqlite_engine, flush_interval_seconds=0.05)
    store.start([1])  # camera 1 is not in the database (deleted via the API)
    frame = make_frame(0)
    store(FrameAnalysis(frame=frame, tracks=[tracked(7, T0)], tracks_started=[tracked(7, T0)]))
    store(FrameAnalysis(frame=frame, tracks_ended=[tracked(7, T0 + timedelta(seconds=2))]))
    store.stop()
    assert rows(sqlite_engine) == []
    assert sessions(sqlite_engine) == []
