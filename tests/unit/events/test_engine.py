from datetime import UTC, datetime, timedelta

import pytest

from app.camera.types import CameraStatus
from app.detection.base import BoundingBox
from app.events.engine import EventEngine, EventRecord
from app.events.types import EventType as E
from app.pipeline.types import FrameAnalysis
from app.recognition.service import Match, Unknown
from app.tracking.tracker import TrackedObject
from tests.unit.pipeline.fakes import make_frame

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def track(track_id: int, seconds: float = 0.0) -> TrackedObject:
    return TrackedObject(
        track_id, BoundingBox(0, 0, 10, 30), 0.876543, T0, T0 + timedelta(seconds=seconds)
    )


def build(cooldown: float = 30.0, unknown_after: int = 3) -> tuple[EventEngine, list[EventRecord]]:
    events: list[EventRecord] = []
    engine = EventEngine(
        events.append,
        cooldown_seconds=cooldown,
        unknown_after_attempts=unknown_after,
        clock=lambda: T0,
    )
    return engine, events


def types(events: list[EventRecord]) -> list[E]:
    return [e.event_type for e in events]


def test_track_start_and_end() -> None:
    engine, events = build()
    engine(FrameAnalysis(frame=make_frame(0), tracks_started=[track(4)]))
    engine(FrameAnalysis(frame=make_frame(1), tracks_ended=[track(4, seconds=12.5)]))
    assert types(events) == [E.TRACK_STARTED, E.PERSON_ENTERED, E.TRACK_ENDED, E.PERSON_LEFT]
    assert all(e.track_id == 4 and e.camera_id == 1 for e in events)
    assert events[1].timestamp == T0
    assert events[1].confidence == 0.8765
    assert events[3].timestamp == T0 + timedelta(seconds=12.5)
    assert events[3].metadata == {"duration_seconds": 12.5}
    assert events[3].person_id is None


def test_recognized_person_is_attached_to_leave_events() -> None:
    engine, events = build()
    engine.on_recognition(1, 4, Match(person_id=7, score=0.81234), T0)
    engine.end_tracks(1, [track(4, seconds=5)])
    assert types(events) == [E.PERSON_RECOGNIZED, E.TRACK_ENDED, E.PERSON_LEFT]
    assert events[0].person_id == 7
    assert events[0].confidence == 0.8123
    assert [e.person_id for e in events[1:]] == [7, 7]


def test_same_person_recognized_again_within_cooldown_is_suppressed() -> None:
    engine, events = build(cooldown=30)
    engine.on_recognition(1, 4, Match(7, 0.8), T0)
    engine.on_recognition(1, 5, Match(7, 0.8), T0 + timedelta(seconds=10))  # track split
    engine.on_recognition(2, 9, Match(7, 0.8), T0 + timedelta(seconds=10))  # other camera
    engine.on_recognition(1, 6, Match(7, 0.8), T0 + timedelta(seconds=31))
    assert [(e.camera_id, e.track_id) for e in events] == [(1, 4), (2, 9), (1, 6)]


def test_unknown_only_after_several_attempts_and_only_once() -> None:
    engine, events = build(unknown_after=3)
    for i in range(5):
        engine.on_recognition(1, 4, Unknown(score=0.2), T0 + timedelta(seconds=i))
    assert types(events) == [E.PERSON_UNKNOWN]
    assert events[0].metadata == {"attempts": 3}
    assert events[0].timestamp == T0 + timedelta(seconds=2)


def test_ended_track_resets_unknown_counter() -> None:
    engine, events = build(unknown_after=2, cooldown=0)
    engine.on_recognition(1, 4, Unknown(0.1), T0)
    engine.end_tracks(1, [track(4)])
    engine.on_recognition(1, 4, Unknown(0.1), T0 + timedelta(minutes=1))  # new track, same no.
    assert E.PERSON_UNKNOWN not in types(events)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CameraStatus.ONLINE, [E.CAMERA_ONLINE]),
        (CameraStatus.OFFLINE, [E.CAMERA_OFFLINE]),
        (CameraStatus.ERROR, [E.CAMERA_OFFLINE]),
        (CameraStatus.UNKNOWN, []),
    ],
)
def test_camera_status(status: CameraStatus, expected: list[E]) -> None:
    engine, events = build()
    engine.on_camera_status(3, status)
    assert types(events) == expected
    assert all(e.camera_id == 3 and e.timestamp == T0 for e in events)


def test_camera_status_is_never_throttled() -> None:
    engine, events = build(cooldown=3600)
    for status in (CameraStatus.ONLINE, CameraStatus.OFFLINE, CameraStatus.ONLINE):
        engine.on_camera_status(1, status)
    assert types(events) == [E.CAMERA_ONLINE, E.CAMERA_OFFLINE, E.CAMERA_ONLINE]


def test_emitter_failure_is_contained() -> None:
    def broken(_record: EventRecord) -> None:
        raise RuntimeError("queue full")

    engine = EventEngine(broken)
    engine(FrameAnalysis(frame=make_frame(0), tracks_started=[track(1)]))  # must not raise
