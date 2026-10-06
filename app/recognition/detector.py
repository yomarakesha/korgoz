"""Face detection.

`FaceDetector` is the abstraction; `YuNetFaceDetector` uses OpenCV's built-in
YuNet (MIT license, OpenCV Model Zoo), which is small and fast on CPU.
"""

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.camera.types import Image
from app.detection.base import BoundingBox
from app.detection.person_detector import ModelLoadError

logger = logging.getLogger(__name__)

Landmarks = tuple[tuple[float, float], ...]  # right eye, left eye, nose, mouth right, mouth left


@dataclass(frozen=True, slots=True)
class FaceDetection:
    bbox: BoundingBox
    confidence: float
    landmarks: Landmarks


class FaceDetector(ABC):
    name: str

    @abstractmethod
    def detect(self, image: Image) -> list[FaceDetection]: ...


class YuNetFaceDetector(FaceDetector):
    def __init__(
        self,
        model_path: Path,
        *,
        score_threshold: float = 0.8,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        if not model_path.is_file():
            raise ModelLoadError(f"Face detector model not found: {model_path}")
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(model_path), "", (320, 320), score_threshold, nms_threshold, top_k
            )
        except cv2.error as exc:
            raise ModelLoadError(f"Cannot load {model_path.name}: {exc}") from exc
        # YuNet keeps the input size as internal state, so calls must not interleave.
        self._lock = threading.Lock()
        self.name = f"yunet:{model_path.stem}"
        logger.info("Loaded %s", self.name)

    def detect(self, image: Image) -> list[FaceDetection]:
        height, width = image.shape[:2]
        with self._lock:
            self._detector.setInputSize((width, height))
            _, faces = self._detector.detect(image)
        if faces is None:
            return []
        results = []
        for row in faces:
            x, y, w, h = (float(v) for v in row[:4])
            points = row[4:14].reshape(5, 2)
            results.append(
                FaceDetection(
                    bbox=BoundingBox(x, y, x + w, y + h).clip(width, height),
                    confidence=float(row[14]),
                    landmarks=tuple((float(px), float(py)) for px, py in points),
                )
            )
        return results
