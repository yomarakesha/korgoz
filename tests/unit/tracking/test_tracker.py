from datetime import UTC, datetime, timedelta

from app.detection.base import BoundingBox, DetectionResult
from app.tracking.tracker import ByteTracker, TrackerConfig

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def at(step: int, fps: float = 10) -> datetime:
    return T0 + timedelta(seconds=step / fps)


def person(x: float, y: float = 100, score: float = 0.9) -> DetectionResult:
    return DetectionResult(BoundingBox(x, y, x + 40, y + 120), score)


def test_moving_person_keeps_one_id() -> None:
    tracker = ByteTracker()
    started, ids = [], set()
    for step in range(20):
        result = tracker.update([person(10 + 4 * step)], at(step))
        started += result.started
        ids |= {t.track_id for t in result.active}
    assert ids == {1}
    assert len(started) == 1  # confirmed on its second detection


def test_single_noise_detection_never_becomes_a_track() -> None:
    tracker = ByteTracker()
    tracker.update([person(500)], at(0))  # one-off false positive
    result = tracker.update([], at(1))
    assert result.active == [] and result.started == []
    # The noise did not consume an id: the first real person is #1.
    tracker.update([person(10)], at(2))
    assert [t.track_id for t in tracker.update([person(12)], at(3)).active] == [1]


def test_low_score_detection_keeps_track_alive() -> None:
    tracker = ByteTracker()
    for step in range(3):
        tracker.update([person(10 + 2 * step)], at(step))
    # Partly occluded: detector is unsure (0.3) but the box still overlaps.
    result = tracker.update([person(16, score=0.3)], at(3))
    assert [t.track_id for t in result.active] == [1]


def test_low_score_detection_never_starts_a_track() -> None:
    tracker = ByteTracker()
    for step in range(5):
        result = tracker.update([person(10, score=0.3)], at(step))
    assert result.active == []


def test_lost_track_is_recovered_within_window() -> None:
    tracker = ByteTracker(TrackerConfig(max_lost_seconds=3))
    for step in range(3):
        tracker.update([person(100)], at(step))
    for step in range(3, 13):  # hidden for one second
        assert tracker.update([], at(step)).active == []
    result = tracker.update([person(100)], at(13))
    assert [t.track_id for t in result.active] == [1]
    assert result.started == []  # same track, not a new one


def test_track_ends_after_lost_window() -> None:
    tracker = ByteTracker(TrackerConfig(max_lost_seconds=1))
    for step in range(3):
        tracker.update([person(100)], at(step))
    ended = []
    for step in range(3, 30):
        ended += tracker.update([], at(step)).ended
    assert [t.track_id for t in ended] == [1]
    assert ended[0].last_seen_at == at(2)


def test_two_people_keep_separate_stable_ids() -> None:
    tracker = ByteTracker()
    history = []
    for step in range(15):
        result = tracker.update([person(50 + 3 * step), person(400 - 3 * step)], at(step))
        if len(result.active) == 2:
            left, right = sorted(result.active, key=lambda t: t.bbox.x1)
            history.append((left.track_id, right.track_id))
    assert len(history) >= 13
    assert set(history) == {history[0]}  # ids never swap
    assert sorted(history[0]) == [1, 2]


def test_predict_moves_boxes_between_detections() -> None:
    tracker = ByteTracker()
    for step in range(10):
        tracker.update([person(10 + 5 * step)], at(step))
    before = tracker.predict(at(10)).active[0].bbox.x1
    after = tracker.predict(at(11)).active[0].bbox.x1
    assert after > before


def test_close_all_returns_confirmed_tracks() -> None:
    tracker = ByteTracker()
    for step in range(3):
        tracker.update([person(10), person(300)], at(step))
    tracker.update([person(600)], at(3))  # tentative, not returned
    assert sorted(t.track_id for t in tracker.close_all(at(4))) == [1, 2]
    assert tracker.predict(at(5)).active == []
