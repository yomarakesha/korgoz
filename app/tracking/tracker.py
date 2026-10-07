"""Multi-object tracking.

`Tracker` is the abstraction used by the pipeline. `ByteTracker` implements the
ByteTrack association scheme (Zhang et al., 2022):

1. Predict every track with a Kalman filter.
2. Match high-confidence detections to tracked + lost tracks by IoU.
3. Match low-confidence detections to the still unmatched *tracked* tracks
   (this recovers people who are partly occluded and scored low).
4. Match remaining high detections to tentative (not yet confirmed) tracks.
5. Start tentative tracks from leftover high detections; drop stale tracks.

Simplification: matching is greedy by IoU instead of the Hungarian algorithm.
With tens of people per frame the result is practically the same and no
extra dependency is needed.
"""

import itertools
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.detection.base import BoundingBox, DetectionResult
from app.tracking.kalman import KalmanBoxFilter


class TrackState(StrEnum):
    TENTATIVE = "tentative"  # seen once, may be noise
    TRACKED = "tracked"  # confirmed and matched recently
    LOST = "lost"  # confirmed, temporarily not matched (occlusion)
    REMOVED = "removed"


@dataclass
class Track:
    # 0 until confirmed: public ids are given only to real tracks, so they stay consecutive.
    track_id: int
    kalman: KalmanBoxFilter = field(repr=False)
    confidence: float
    started_at: datetime
    last_seen_at: datetime
    state: TrackState = TrackState.TENTATIVE
    hits: int = 1

    @property
    def bbox(self) -> BoundingBox:
        return self.kalman.box


@dataclass(frozen=True, slots=True)
class TrackedObject:
    """Read-only snapshot of a track handed to the rest of the system."""

    track_id: int
    bbox: BoundingBox
    confidence: float
    started_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class TrackingResult:
    active: list[TrackedObject]  # confirmed tracks currently visible
    started: list[TrackedObject]  # confirmed in this update
    ended: list[TrackedObject]  # removed in this update (were confirmed)


@dataclass(frozen=True)
class TrackerConfig:
    high_threshold: float = 0.5  # detections above this create/extend tracks
    low_threshold: float = 0.1  # 2nd association pass uses [low, high)
    new_track_threshold: float = 0.6  # minimum score to start a new track
    match_iou: float = 0.2  # 1st pass (tracked + lost tracks)
    low_match_iou: float = 0.5  # 2nd pass (low-score detections)
    tentative_match_iou: float = 0.3
    max_lost_seconds: float = 3.0  # how long a lost track can be re-found


class Tracker(ABC):
    @abstractmethod
    def update(self, detections: list[DetectionResult], timestamp: datetime) -> TrackingResult:
        """Associate a fresh set of detections with existing tracks."""

    @abstractmethod
    def predict(self, timestamp: datetime) -> TrackingResult:
        """Advance tracks one frame without detections (between detection frames)."""

    @abstractmethod
    def close_all(self, timestamp: datetime) -> list[TrackedObject]:
        """End every confirmed track (worker shutdown)."""


def _greedy_match(
    tracks: list[Track], detections: list[DetectionResult], min_iou: float
) -> tuple[list[tuple[Track, DetectionResult]], list[Track], list[DetectionResult]]:
    pairs = sorted(
        (
            (track.bbox.iou(det.bbox), t_idx, d_idx)
            for t_idx, track in enumerate(tracks)
            for d_idx, det in enumerate(detections)
        ),
        reverse=True,
    )
    used_tracks: set[int] = set()
    used_dets: set[int] = set()
    matches = []
    for iou, t_idx, d_idx in pairs:
        if iou < min_iou:
            break
        if t_idx in used_tracks or d_idx in used_dets:
            continue
        used_tracks.add(t_idx)
        used_dets.add(d_idx)
        matches.append((tracks[t_idx], detections[d_idx]))
    unmatched_tracks = [t for i, t in enumerate(tracks) if i not in used_tracks]
    unmatched_dets = [d for i, d in enumerate(detections) if i not in used_dets]
    return matches, unmatched_tracks, unmatched_dets


def _snapshot(track: Track) -> TrackedObject:
    return TrackedObject(
        track_id=track.track_id,
        bbox=track.bbox,
        confidence=track.confidence,
        started_at=track.started_at,
        last_seen_at=track.last_seen_at,
    )


class ByteTracker(Tracker):
    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._tracks: list[Track] = []
        self._ids = itertools.count(1)

    def _predict_all(self) -> None:
        for track in self._tracks:
            track.kalman.predict()

    def _visible(self) -> list[TrackedObject]:
        return [_snapshot(t) for t in self._tracks if t.state is TrackState.TRACKED]

    def predict(self, timestamp: datetime) -> TrackingResult:
        self._predict_all()
        return TrackingResult(active=self._visible(), started=[], ended=[])

    def update(self, detections: list[DetectionResult], timestamp: datetime) -> TrackingResult:
        cfg = self.config
        self._predict_all()

        high = [d for d in detections if d.confidence >= cfg.high_threshold]
        low = [d for d in detections if cfg.low_threshold <= d.confidence < cfg.high_threshold]
        confirmed = [t for t in self._tracks if t.state in (TrackState.TRACKED, TrackState.LOST)]
        tentative = [t for t in self._tracks if t.state is TrackState.TENTATIVE]
        started: list[TrackedObject] = []

        def apply(track: Track, det: DetectionResult) -> None:
            track.kalman.update(det.bbox)
            track.confidence = det.confidence
            track.last_seen_at = timestamp
            track.hits += 1
            if track.state is TrackState.TENTATIVE:
                track.track_id = next(self._ids)
                track.state = TrackState.TRACKED
                started.append(_snapshot(track))
            track.state = TrackState.TRACKED

        # 1) high-score detections vs confirmed tracks (including lost ones)
        matches, remaining, high_left = _greedy_match(confirmed, high, cfg.match_iou)
        for track, det in matches:
            apply(track, det)

        # 2) low-score detections vs tracks that were visible until now
        still_tracked = [t for t in remaining if t.state is TrackState.TRACKED]
        matches, unmatched, _ = _greedy_match(still_tracked, low, cfg.low_match_iou)
        for track, det in matches:
            apply(track, det)
        for track in unmatched:
            track.state = TrackState.LOST

        # 3) leftover high detections vs tentative tracks; unconfirmed noise is dropped
        matches, stale, high_left = _greedy_match(tentative, high_left, cfg.tentative_match_iou)
        for track, det in matches:
            apply(track, det)
        for track in stale:
            track.state = TrackState.REMOVED

        # 4) new tentative tracks
        for det in high_left:
            if det.confidence >= cfg.new_track_threshold:
                self._tracks.append(
                    Track(
                        track_id=0,
                        kalman=KalmanBoxFilter(det.bbox),
                        confidence=det.confidence,
                        started_at=timestamp,
                        last_seen_at=timestamp,
                    )
                )

        # 5) forget tracks lost for too long
        ended: list[TrackedObject] = []
        for track in self._tracks:
            lost_for = (timestamp - track.last_seen_at).total_seconds()
            if track.state is TrackState.LOST and lost_for > cfg.max_lost_seconds:
                track.state = TrackState.REMOVED
                ended.append(_snapshot(track))
        self._tracks = [t for t in self._tracks if t.state is not TrackState.REMOVED]
        return TrackingResult(active=self._visible(), started=started, ended=ended)

    def close_all(self, timestamp: datetime) -> list[TrackedObject]:
        ended = [
            _snapshot(t) for t in self._tracks if t.state in (TrackState.TRACKED, TrackState.LOST)
        ]
        self._tracks = []
        return ended
