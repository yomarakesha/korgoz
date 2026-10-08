from datetime import UTC, datetime

from app.camera.types import Frame
from app.detection.base import BoundingBox
from app.pipeline.types import FrameAnalysis
from app.recognition.detector import FaceDetection
from app.recognition.service import Match, Unknown
from app.recognition.sink import RecognitionSink, TrackIdentity, assign_faces
from app.tracking.tracker import TrackedObject
from app.vector_store.base import Vector
from tests.unit.recognition.fakes import (
    FakeEmbedder,
    InMemoryVectorStore,
    make_face,
    make_service,
    noise_image,
    unit,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def track(track_id: int, x1: float, y1: float, x2: float, y2: float) -> TrackedObject:
    return TrackedObject(track_id, BoundingBox(x1, y1, x2, y2), 0.9, NOW, NOW)


def analysis(
    tracks: list[TrackedObject],
    faces: list[FaceDetection],
    *,
    fresh: bool = True,
    ended: list[TrackedObject] | None = None,
    camera_id: int = 1,
) -> FrameAnalysis:
    frame = Frame(camera_id=camera_id, index=0, timestamp=NOW, image=noise_image())
    return FrameAnalysis(
        frame=frame, faces=faces, tracks=tracks, tracks_ended=ended or [], fresh=fresh
    )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def build(
    store: InMemoryVectorStore, vector: Vector | None = None
) -> tuple[RecognitionSink, Clock, FakeEmbedder]:
    clock = Clock()
    embedder = FakeEmbedder(vector)
    sink = RecognitionSink(
        make_service(store=store, embedder=embedder),
        interval_seconds=1.0,
        resolve_name={7: "Alice"}.get,
        clock=clock,
    )
    return sink, clock, embedder


PERSON = track(1, 0, 0, 160, 230)
FACE = make_face(x=20, y=10, size=100)


def test_assign_faces_skips_faces_outside_or_shared() -> None:
    left, right = track(1, 0, 0, 100, 200), track(2, 80, 0, 200, 200)
    inside_left = make_face(x=10, y=10, size=50)  # centre (35, 35)
    shared = make_face(x=65, y=10, size=40)  # centre (85, 30): in both boxes
    outside = make_face(x=300, y=10, size=40)
    assert assign_faces([left, right], [inside_left, shared, outside]) == {1: inside_left}


def test_assign_faces_keeps_the_most_confident() -> None:
    weak, strong = make_face(conf=0.81), make_face(conf=0.95)
    assert assign_faces([PERSON], [weak, strong]) == {1: strong}


def test_registered_person_gets_a_named_label() -> None:
    store = InMemoryVectorStore()
    store.add_embedding(7, unit(1, 0, 0), "fake")
    sink, _, _ = build(store)
    sink(analysis([PERSON], [FACE]))
    assert sink.labels(1) == {1: "Alice 1.00"}
    assert sink.labels(2) == {}  # other camera


def test_identified_track_is_not_recognised_again() -> None:
    store = InMemoryVectorStore()
    store.add_embedding(7, unit(1, 0, 0), "fake")
    sink, clock, embedder = build(store)
    sink(analysis([PERSON], [FACE]))
    clock.now = 100
    sink(analysis([PERSON], [FACE]))
    assert embedder.calls == 1


def test_unknown_track_is_retried_at_most_once_per_interval() -> None:
    sink, clock, embedder = build(InMemoryVectorStore())
    sink(analysis([PERSON], [FACE]))
    assert sink.labels(1) == {1: "Unknown"}
    clock.now = 0.5
    sink(analysis([PERSON], [FACE]))
    assert embedder.calls == 1
    clock.now = 1.5
    sink(analysis([PERSON], [FACE]))
    assert embedder.calls == 2


def test_person_registered_later_is_recognised_on_retry() -> None:
    store = InMemoryVectorStore()
    sink, clock, _ = build(store)
    sink(analysis([PERSON], [FACE]))
    store.add_embedding(7, unit(1, 0, 0), "fake")  # e.g. POST /persons meanwhile
    clock.now = 2
    sink(analysis([PERSON], [FACE]))
    assert sink.labels(1) == {1: "Alice 1.00"}


def test_stale_frames_and_tracks_without_faces_are_skipped() -> None:
    sink, _, embedder = build(InMemoryVectorStore())
    sink(analysis([PERSON], [FACE], fresh=False))
    sink(analysis([PERSON], []))
    assert embedder.calls == 0
    assert sink.labels(1) == {}


def test_ended_track_is_forgotten() -> None:
    sink, _, _ = build(InMemoryVectorStore())
    sink(analysis([PERSON], [FACE]))
    sink(analysis([], [], ended=[PERSON]))
    assert sink.labels(1) == {}


def test_vector_store_outage_is_contained() -> None:
    store = InMemoryVectorStore()
    store.down = True
    sink, _, _ = build(store)
    sink(analysis([PERSON], [FACE]))  # must not raise
    assert sink.labels(1) == {}


def test_label_without_a_known_name() -> None:
    assert TrackIdentity(Match(3, 0.876)).label == "Person #3 0.88"
    assert TrackIdentity(Unknown(0.2)).label == "Unknown"
