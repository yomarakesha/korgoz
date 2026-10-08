"""Event Engine: turns pipeline results into domain events.

Sources:
- tracks (an `AnalysisSink`): TRACK_STARTED + PERSON_ENTERED when a track is
  confirmed, TRACK_ENDED + PERSON_LEFT when it ends;
- recognition (`on_recognition`, called by RecognitionSink): PERSON_RECOGNIZED,
  or PERSON_UNKNOWN once a track had UNKNOWN_AFTER_ATTEMPTS faces that matched nobody;
- cameras (`on_camera_status`, a `StatusListener`): CAMERA_ONLINE / CAMERA_OFFLINE.

Deduplication: an event with the same (camera, type, person or track) is emitted
at most once per EVENT_COOLDOWN_SECONDS, measured in event time. Camera status
events are not throttled: they are already emitted only on a real change, and
dropping one would leave the camera's last known state wrong.

The engine only decides *what* happened; `emit` (normally `EventStore`) stores it.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.camera.types import CameraStatus
from app.events.types import EventType
from app.pipeline.types import FrameAnalysis
from app.recognition.service import Identity, Match
from app.tracking.tracker import TrackedObject

logger = logging.getLogger(__name__)

TrackKey = tuple[int, int]  # (camera_id, tracker-local track_id)
CooldownKey = tuple[int, EventType, str]


@dataclass(frozen=True)
class EventRecord:
    """An event before it is stored. `track_id` is the tracker-local number."""

    event_type: EventType
    camera_id: int
    timestamp: datetime
    track_id: int | None = None
    person_id: int | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


EventEmitter = Callable[[EventRecord], None]


class Cooldown:
    def __init__(self, seconds: float) -> None:
        self._window = timedelta(seconds=seconds)
        self._last: dict[CooldownKey, datetime] = {}

    def allow(self, key: CooldownKey, timestamp: datetime) -> bool:
        last = self._last.get(key)
        if last is not None and timestamp - last < self._window:
            return False
        self._last[key] = timestamp
        self._prune(timestamp)
        return True

    def _prune(self, now: datetime) -> None:
        if len(self._last) > 10_000:  # long-running worker: forget expired keys
            self._last = {k: t for k, t in self._last.items() if now - t < self._window}


class EventEngine:
    def __init__(
        self,
        emit: EventEmitter,
        *,
        cooldown_seconds: float = 30.0,
        unknown_after_attempts: int = 3,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._emit = emit
        self._cooldown = Cooldown(cooldown_seconds)
        self._unknown_after = unknown_after_attempts
        self._clock = clock
        self._persons: dict[TrackKey, int] = {}  # recognised tracks -> person_id
        self._unknown_attempts: dict[TrackKey, int] = {}
        self._lock = threading.Lock()  # one engine serves every camera thread

    # --- tracks -----------------------------------------------------------------

    def __call__(self, analysis: FrameAnalysis) -> None:
        camera_id = analysis.frame.camera_id
        for track in analysis.tracks_started:
            for event_type in (EventType.TRACK_STARTED, EventType.PERSON_ENTERED):
                self._publish(
                    EventRecord(
                        event_type,
                        camera_id=camera_id,
                        timestamp=track.started_at,
                        track_id=track.track_id,
                        confidence=round(track.confidence, 4),
                    )
                )
        self.end_tracks(camera_id, analysis.tracks_ended)

    def end_tracks(self, camera_id: int, tracks: list[TrackedObject]) -> None:
        for track in tracks:
            key = (camera_id, track.track_id)
            with self._lock:
                person_id = self._persons.pop(key, None)
                self._unknown_attempts.pop(key, None)
            duration = round((track.last_seen_at - track.started_at).total_seconds(), 2)
            for event_type in (EventType.TRACK_ENDED, EventType.PERSON_LEFT):
                self._publish(
                    EventRecord(
                        event_type,
                        camera_id=camera_id,
                        timestamp=track.last_seen_at,
                        track_id=track.track_id,
                        person_id=person_id,
                        metadata={"duration_seconds": duration},
                    )
                )

    # --- recognition --------------------------------------------------------------

    def on_recognition(
        self, camera_id: int, track_id: int, identity: Identity, timestamp: datetime
    ) -> None:
        key = (camera_id, track_id)
        if isinstance(identity, Match):
            with self._lock:
                self._persons[key] = identity.person_id
            self._publish(
                EventRecord(
                    EventType.PERSON_RECOGNIZED,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    track_id=track_id,
                    person_id=identity.person_id,
                    confidence=round(identity.score, 4),
                )
            )
            return
        with self._lock:
            attempts = self._unknown_attempts.get(key, 0) + 1
            self._unknown_attempts[key] = attempts
        if attempts == self._unknown_after:  # exactly once per track
            self._publish(
                EventRecord(
                    EventType.PERSON_UNKNOWN,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    track_id=track_id,
                    confidence=round(identity.score, 4),
                    metadata={"attempts": attempts},
                )
            )

    # --- cameras -----------------------------------------------------------------

    def on_camera_status(self, camera_id: int, status: CameraStatus) -> None:
        event_type = {
            CameraStatus.ONLINE: EventType.CAMERA_ONLINE,
            CameraStatus.OFFLINE: EventType.CAMERA_OFFLINE,
            CameraStatus.ERROR: EventType.CAMERA_OFFLINE,
        }.get(status)
        if event_type is None:
            return
        self._send(
            EventRecord(
                event_type,
                camera_id=camera_id,
                timestamp=self._clock(),
                metadata={"status": status.value},
            )
        )

    # --- output -------------------------------------------------------------------

    def _publish(self, record: EventRecord) -> None:
        subject = (
            f"person:{record.person_id}"
            if record.person_id is not None and record.event_type is EventType.PERSON_RECOGNIZED
            else f"track:{record.track_id}"
        )
        with self._lock:
            allowed = self._cooldown.allow(
                (record.camera_id, record.event_type, subject), record.timestamp
            )
        if allowed:
            self._send(record)

    def _send(self, record: EventRecord) -> None:
        try:
            self._emit(record)
        except Exception:
            logger.exception("Cannot emit %s", record.event_type.value)
