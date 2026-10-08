"""Real-model tests. Slow-ish and need downloaded files: run with `pytest -m ai`."""

import itertools
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest

from app.camera.types import Image
from app.config import Settings
from app.detection.person_detector import YoloxPersonDetector
from app.recognition.detector import YuNetFaceDetector
from app.recognition.embedding import SFaceProvider
from app.recognition.quality import FaceQualityChecker, QualityThresholds
from app.recognition.service import FaceRecognitionService, Match, Unknown
from app.vector_store.base import Vector

pytestmark = pytest.mark.ai

MODELS = Path("models")
SAMPLES = Path("data/samples")
PORTRAITS = ["biden_1", "biden_2", "harris_1", "harris_2", "obama_1"]


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


def load(name: str) -> Image:
    from app.api.routes.persons import decode_image

    return decode_image(require(SAMPLES / name).read_bytes())


@pytest.fixture(scope="module")
def sface() -> tuple[YuNetFaceDetector, SFaceProvider]:
    return (
        YuNetFaceDetector(require(MODELS / "face_detection_yunet_2023mar.onnx")),
        SFaceProvider(require(MODELS / "face_recognition_sface_2021dec.onnx")),
    )


def embed(models: tuple[YuNetFaceDetector, SFaceProvider], name: str) -> Vector:
    detector, embedder = models
    image = load(name)
    faces = detector.detect(image)
    assert len(faces) == 1
    return embedder.embed(image, faces[0])


def test_sface_vector_is_normalised(sface: tuple[YuNetFaceDetector, SFaceProvider]) -> None:
    vector = embed(sface, "lena.jpg")
    assert sface[1].dimension == vector.size == 128
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-5)


def test_sface_separates_people_at_the_default_threshold(
    sface: tuple[YuNetFaceDetector, SFaceProvider],
) -> None:
    """Public-domain portraits (two photos each of two people, years apart)."""
    threshold = Settings(_env_file=None, database_url="sqlite://").face_match_threshold
    vectors = {n: embed(sface, f"{n}.jpg") for n in PORTRAITS}
    for a, b in itertools.combinations(PORTRAITS, 2):
        score = float(np.dot(vectors[a], vectors[b]))
        same = a.split("_")[0] == b.split("_")[0]
        assert (score >= threshold) is same, f"{a} vs {b}: {score:.3f}"


def test_registration_then_identification_end_to_end(
    sface: tuple[YuNetFaceDetector, SFaceProvider],
) -> None:
    """Register from one photo, recognise the same person on another one."""
    from tests.unit.recognition.fakes import InMemoryVectorStore

    detector, embedder = sface
    store = InMemoryVectorStore()
    service = FaceRecognitionService(
        detector,
        embedder,
        FaceQualityChecker(QualityThresholds()),
        store,
        match_threshold=0.40,
        registration_quality=FaceQualityChecker(QualityThresholds(min_size=80)),
    )
    store.add_embedding(1, service.registration_embedding(load("biden_1.jpg")), embedder.name)
    store.add_embedding(2, service.registration_embedding(load("harris_1.jpg")), embedder.name)

    for name, expected in [("biden_2.jpg", 1), ("harris_2.jpg", 2)]:
        image = load(name)
        identity = service.identify(image, detector.detect(image)[0])
        assert isinstance(identity, Match) and identity.person_id == expected, name
    stranger = load("obama_1.jpg")
    assert isinstance(service.identify(stranger, detector.detect(stranger)[0]), Unknown)
