"""Face quality gate: reject faces too small, blurry or turned away to embed reliably."""

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from app.camera.types import Image
from app.recognition.detector import FaceDetection


class QualityIssue(StrEnum):
    TOO_SMALL = "too_small"
    BLURRY = "blurry"
    NOT_FRONTAL = "not_frontal"


@dataclass(frozen=True)
class QualityThresholds:
    min_size: int = 40  # pixels, shorter side of the face box
    min_sharpness: float = 30.0  # variance of the Laplacian on the face crop
    max_yaw: float = 0.5  # 0 = frontal, 1 = profile


@dataclass(frozen=True)
class QualityReport:
    size: float
    sharpness: float
    yaw: float
    issue: QualityIssue | None

    @property
    def ok(self) -> bool:
        return self.issue is None


def estimate_yaw(face: FaceDetection) -> float:
    """Head turn from the 5 landmarks: nose offset from the eye midpoint.

    The nose sits between the eyes on a frontal face and moves towards one eye
    as the head turns. Returns 0 (frontal) .. 1 (nose at or beyond an eye).
    """
    (rx, _), (lx, _), (nx, _) = face.landmarks[0], face.landmarks[1], face.landmarks[2]
    half_eye_distance = abs(lx - rx) / 2
    if half_eye_distance < 1e-6:
        return 1.0
    return min(abs(nx - (lx + rx) / 2) / half_eye_distance, 1.0)


def sharpness(image: Image, face: FaceDetection) -> float:
    x1, y1, x2, y2 = face.bbox.as_int_tuple()
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Normalise the size so the score doesn't depend on the face resolution.
    gray = cv2.resize(gray, (112, 112), interpolation=cv2.INTER_AREA)
    return float(np.var(cv2.Laplacian(gray, cv2.CV_64F)))


class FaceQualityChecker:
    def __init__(self, thresholds: QualityThresholds) -> None:
        self.thresholds = thresholds

    def check(self, image: Image, face: FaceDetection) -> QualityReport:
        size = min(face.bbox.width, face.bbox.height)
        sharp = sharpness(image, face)
        yaw = estimate_yaw(face)
        issue = None
        if size < self.thresholds.min_size:
            issue = QualityIssue.TOO_SMALL
        elif sharp < self.thresholds.min_sharpness:
            issue = QualityIssue.BLURRY
        elif yaw > self.thresholds.max_yaw:
            issue = QualityIssue.NOT_FRONTAL
        return QualityReport(size=size, sharpness=sharp, yaw=yaw, issue=issue)
