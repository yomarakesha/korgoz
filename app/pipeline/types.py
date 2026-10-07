"""Result of running the vision pipeline on one frame."""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.camera.types import Frame
from app.detection.base import DetectionResult
from app.recognition.detector import FaceDetection
from app.tracking.tracker import TrackedObject


@dataclass(frozen=True)
class FrameAnalysis:
    frame: Frame
    persons: list[DetectionResult] = field(default_factory=list)
    faces: list[FaceDetection] = field(default_factory=list)
    # Tracking (empty when tracking is disabled): confirmed tracks visible now,
    # plus tracks confirmed / ended on this frame.
    tracks: list[TrackedObject] = field(default_factory=list)
    tracks_started: list[TrackedObject] = field(default_factory=list)
    tracks_ended: list[TrackedObject] = field(default_factory=list)
    # False when detections were reused from the last detection frame
    # (detection runs only every DETECTION_INTERVAL frames).
    fresh: bool = False
    detection_ms: float = 0.0


# Downstream consumers (tracking, events, live view) receive every analysis.
AnalysisSink = Callable[[FrameAnalysis], None]
