from datetime import UTC, datetime, timedelta

from app.camera.buffer import FrameBuffer
from app.camera.types import Image
from app.detection.base import BoundingBox, DetectionResult, Detector
from app.pipeline.annotate import annotate
from app.pipeline.processor import FrameProcessor
from app.tracking.tracker import ByteTracker

from .fakes import make_frame


class WalkingPerson(Detector):
    """A confident person walking right plus a faint (low-score) box."""

    name = "walking"

    def __init__(self) -> None:
        self.calls = 0

    def detect(self, image: Image) -> list[DetectionResult]:
        x = 5 + 2 * self.calls
        self.calls += 1
        return [
            DetectionResult(BoundingBox(x, 5, x + 10, 40), 0.9),
            DetectionResult(BoundingBox(40, 5, 50, 40), 0.2),
        ]


def frame_at(index: int):  # type: ignore[no-untyped-def]
    frame = make_frame(index)
    return type(frame)(
        camera_id=frame.camera_id,
        index=index,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index / 10),
        image=frame.image,
    )


def test_tracks_flow_through_processor() -> None:
    processor = FrameProcessor(
        1,
        FrameBuffer(),
        detector=WalkingPerson(),
        detection_interval=2,
        tracker=ByteTracker(),
        min_person_confidence=0.5,
    )
    analyses = [processor.process(frame_at(i)) for i in range(10)]

    started = [t for a in analyses for t in a.tracks_started]
    assert [t.track_id for t in started] == [1]
    assert all(len(a.persons) == 1 for a in analyses)  # low-score box hidden
    assert [t.track_id for t in analyses[-1].tracks] == [1]
    assert processor.active_tracks == 1
    assert [t.track_id for t in processor.close_tracks()] == [1]

    drawn = annotate(analyses[-1])
    assert drawn.shape == analyses[-1].frame.image.shape
