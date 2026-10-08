"""Per-track recognition in the worker (an `AnalysisSink`).

Recognition runs per track, not per frame: a new track is tried on fresh
detection frames until it is identified, but at most once every
RECOGNITION_INTERVAL_SECONDS. Once identified, the result sticks to the track
until it ends. Qdrant is queried on every attempt, so people registered through
the API are recognised without restarting the worker.

Faces come from the frame-wide face detection (`FrameAnalysis.faces`); a face
belongs to a track when its centre lies inside exactly one track box.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.pipeline.types import FrameAnalysis
from app.recognition.detector import FaceDetection
from app.recognition.service import FaceRecognitionService, Identity, Match
from app.tracking.tracker import TrackedObject
from app.vector_store.base import VectorStoreError

logger = logging.getLogger(__name__)

TrackKey = tuple[int, int]  # (camera_id, tracker-local track_id)
NameResolver = Callable[[int], str | None]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class TrackIdentity:
    identity: Identity
    name: str | None = None  # registered person's name (Match only)

    @property
    def label(self) -> str:
        if isinstance(self.identity, Match):
            name = self.name or f"Person #{self.identity.person_id}"
            return f"{name} {self.identity.score:.2f}"
        return "Unknown"


def assign_faces(
    tracks: list[TrackedObject], faces: list[FaceDetection]
) -> dict[int, FaceDetection]:
    """track_id -> its most confident face; faces inside several boxes are skipped."""
    assigned: dict[int, FaceDetection] = {}
    for face in faces:
        cx, cy = face.bbox.center
        owners = [
            t for t in tracks if t.bbox.x1 <= cx <= t.bbox.x2 and t.bbox.y1 <= cy <= t.bbox.y2
        ]
        if len(owners) != 1:
            continue  # no track, or ambiguous between overlapping people
        track_id = owners[0].track_id
        if track_id not in assigned or face.confidence > assigned[track_id].confidence:
            assigned[track_id] = face
    return assigned


class RecognitionSink:
    def __init__(
        self,
        service: FaceRecognitionService,
        *,
        interval_seconds: float = 1.0,
        resolve_name: NameResolver | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._resolve_name = resolve_name or (lambda _person_id: None)
        self._clock = clock
        self._identities: dict[TrackKey, TrackIdentity] = {}
        self._last_attempt: dict[TrackKey, float] = {}
        self._lock = threading.Lock()  # identities are read by live view threads

    def __call__(self, analysis: FrameAnalysis) -> None:
        camera_id = analysis.frame.camera_id
        self._forget(camera_id, analysis.tracks_ended)
        # Face boxes are only aligned with the image on detection frames.
        if not analysis.fresh or not analysis.faces:
            return
        now = self._clock()
        faces = assign_faces(analysis.tracks, analysis.faces)
        for track in analysis.tracks:
            key = (camera_id, track.track_id)
            face = faces.get(track.track_id)
            if face is not None and self._due(key, now):
                self._recognise(key, analysis, face)

    def _recognise(self, key: TrackKey, analysis: FrameAnalysis, face: FaceDetection) -> None:
        try:
            identity = self._service.identify(analysis.frame.image, face)
        except VectorStoreError:
            return  # already logged; retried after the interval
        if identity is None:
            return  # low-quality face, try again on a later frame
        name = self._resolve_name(identity.person_id) if isinstance(identity, Match) else None
        with self._lock:
            self._identities[key] = TrackIdentity(identity, name)
        logger.debug("Camera %s track %s: %s", key[0], key[1], self._identities[key].label)

    def _due(self, key: TrackKey, now: float) -> bool:
        """Not identified yet and not tried within the interval (marks the attempt)."""
        with self._lock:  # one sink serves every camera thread
            current = self._identities.get(key)
            if current is not None and isinstance(current.identity, Match):
                return False
            if now - self._last_attempt.get(key, float("-inf")) < self._interval:
                return False
            self._last_attempt[key] = now
            return True

    def _forget(self, camera_id: int, ended: list[TrackedObject]) -> None:
        with self._lock:
            for track in ended:
                self._identities.pop((camera_id, track.track_id), None)
                self._last_attempt.pop((camera_id, track.track_id), None)

    def identities(self, camera_id: int) -> dict[int, TrackIdentity]:
        """track_id -> identity for one camera (tracks never tried are absent)."""
        with self._lock:
            return {
                tid: ident for (cam, tid), ident in self._identities.items() if cam == camera_id
            }

    def labels(self, camera_id: int) -> dict[int, str]:
        return {tid: ident.label for tid, ident in self.identities(camera_id).items()}
