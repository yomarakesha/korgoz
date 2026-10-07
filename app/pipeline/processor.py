"""Per-camera processing thread: FrameBuffer -> detectors -> sinks.

Detection runs on every N-th frame (DETECTION_INTERVAL); frames in between reuse
the latest detections. Errors in a detector or sink are logged and contained,
so one bad frame or one camera never stops the others.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.camera.buffer import FrameBuffer
from app.camera.types import Frame
from app.core.metrics import RateMeter
from app.detection.base import DetectionResult, Detector
from app.pipeline.types import AnalysisSink, FrameAnalysis
from app.recognition.detector import FaceDetection, FaceDetector
from app.tracking.tracker import TrackedObject, Tracker, TrackingResult

logger = logging.getLogger(__name__)

_WAIT_TIMEOUT_SECONDS = 1.0


@dataclass
class ProcessorStats:
    frames_processed: int = 0
    detections_run: int = 0
    detection_errors: int = 0
    avg_detection_ms: float = 0.0  # exponential moving average
    processing_fps: float = 0.0  # smoothed


class FrameProcessor:
    def __init__(
        self,
        camera_id: int,
        buffer: FrameBuffer,
        *,
        detector: Detector | None,
        face_detector: FaceDetector | None = None,
        detection_interval: int = 1,
        sinks: list[AnalysisSink] | None = None,
        tracker: Tracker | None = None,
        min_person_confidence: float = 0.0,
    ) -> None:
        if detection_interval < 1:
            raise ValueError("detection_interval must be >= 1")
        self.camera_id = camera_id
        self.buffer = buffer
        self.detector = detector
        self.face_detector = face_detector
        self.detection_interval = detection_interval
        self.sinks = sinks or []
        self.tracker = tracker
        # With tracking the detector also returns low-score boxes (ByteTrack uses
        # them); only boxes above this threshold are reported as `persons`.
        self.min_person_confidence = min_person_confidence
        self.stats = ProcessorStats()
        self._persons: list[DetectionResult] = []
        self._faces: list[FaceDetection] = []
        self.active_tracks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"pipeline-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self, timeout: float = 10.0) -> None:
        self.request_stop()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        last_index = -1
        rate = RateMeter()
        while not self._stop.is_set():
            frame = self.buffer.wait_next(last_index, _WAIT_TIMEOUT_SECONDS)
            if frame is None:
                continue
            last_index = frame.index
            try:
                self.process(frame)
            except Exception:
                logger.exception("Camera %s: frame processing failed", self.camera_id)
            rate.tick(time.monotonic())
            self.stats.processing_fps = rate.rate

    def process(self, frame: Frame) -> FrameAnalysis:
        """Analyse one frame and hand the result to every sink (also used by tests)."""
        fresh = self.stats.frames_processed % self.detection_interval == 0
        detection_ms = 0.0
        detected = False
        if fresh:
            started = time.perf_counter()
            detected = self._detect(frame)
            detection_ms = (time.perf_counter() - started) * 1000
            self.stats.detections_run += 1
            if self.stats.detections_run == 1:
                self.stats.avg_detection_ms = detection_ms
            else:
                self.stats.avg_detection_ms = 0.9 * self.stats.avg_detection_ms + 0.1 * detection_ms
        self.stats.frames_processed += 1

        tracking = self._track(frame, detected)
        analysis = FrameAnalysis(
            frame=frame,
            persons=[p for p in self._persons if p.confidence >= self.min_person_confidence],
            faces=list(self._faces),
            fresh=fresh,
            detection_ms=detection_ms,
            tracks=tracking.active if tracking else [],
            tracks_started=tracking.started if tracking else [],
            tracks_ended=tracking.ended if tracking else [],
        )
        self.active_tracks = len(analysis.tracks)
        for sink in self.sinks:
            try:
                sink(analysis)
            except Exception:
                logger.exception("Camera %s: analysis sink failed", self.camera_id)
        return analysis

    def _detect(self, frame: Frame) -> bool:
        """Run detectors; False if they failed (previous detections are kept)."""
        try:
            if self.detector is not None:
                self._persons = self.detector.detect(frame.image)
            if self.face_detector is not None:
                self._faces = self.face_detector.detect(frame.image)
        except Exception:
            # A single bad frame must not stop the camera.
            self.stats.detection_errors += 1
            logger.exception("Camera %s: detection failed", self.camera_id)
            return False
        return self.detector is not None

    def _track(self, frame: Frame, detected: bool) -> TrackingResult | None:
        if self.tracker is None:
            return None
        try:
            if detected:
                return self.tracker.update(self._persons, frame.timestamp)
            return self.tracker.predict(frame.timestamp)
        except Exception:
            logger.exception("Camera %s: tracking failed", self.camera_id)
            return None

    def close_tracks(self) -> list[TrackedObject]:
        """End all open tracks (call after the thread stopped)."""
        if self.tracker is None:
            return []
        return self.tracker.close_all(datetime.now(UTC))
