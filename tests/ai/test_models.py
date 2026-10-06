"""Real-model tests. Slow-ish and need downloaded files: run with `pytest -m ai`."""

from pathlib import Path
from typing import cast

import cv2
import pytest

from app.camera.types import Image
from app.detection.person_detector import YoloxPersonDetector
from app.recognition.detector import YuNetFaceDetector

pytestmark = pytest.mark.ai

MODELS = Path("models")
SAMPLES = Path("data/samples")


def require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"{path} missing: run python -m scripts.download_models --samples")
    return path


@pytest.mark.parametrize("model", ["yolox_s.onnx", "yolox_tiny.onnx"])
def test_yolox_finds_pedestrians(model: str) -> None:
    detector = YoloxPersonDetector(require(MODELS / model))
    capture = cv2.VideoCapture(str(require(SAMPLES / "vtest.avi")))
    ok, frame = capture.read()
    capture.release()
    assert ok
    persons = detector.detect(cast(Image, frame))
    assert len(persons) >= 2
    assert all(p.confidence >= 0.5 for p in persons)
    height, width = frame.shape[:2]
    assert all(0 <= p.bbox.x1 < p.bbox.x2 <= width for p in persons)
    assert all(0 <= p.bbox.y1 < p.bbox.y2 <= height for p in persons)


def test_yunet_finds_one_face() -> None:
    detector = YuNetFaceDetector(require(MODELS / "face_detection_yunet_2023mar.onnx"))
    image = cv2.imread(str(require(SAMPLES / "lena.jpg")))
    assert image is not None
    faces = detector.detect(cast(Image, image))
    assert len(faces) == 1
    assert faces[0].confidence > 0.8
    assert len(faces[0].landmarks) == 5
