from datetime import UTC, datetime

import numpy as np

from app.camera.types import Frame, Image
from app.detection.base import BoundingBox, DetectionResult, Detector


def make_frame(index: int, camera_id: int = 1) -> Frame:
    return Frame(
        camera_id=camera_id,
        index=index,
        timestamp=datetime.now(UTC),
        image=np.zeros((48, 64, 3), dtype=np.uint8),
    )


class CountingDetector(Detector):
    name = "fake"

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def detect(self, image: Image) -> list[DetectionResult]:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("model crashed")
        return [DetectionResult(BoundingBox(1, 2, 30, 40), confidence=0.5 + self.calls / 100)]
