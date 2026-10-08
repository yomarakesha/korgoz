import uuid

import numpy as np

from app.camera.types import Image
from app.detection.base import BoundingBox
from app.recognition.detector import FaceDetection, FaceDetector
from app.recognition.embedding import FaceEmbeddingProvider
from app.recognition.quality import FaceQualityChecker, QualityThresholds
from app.recognition.service import FaceRecognitionService
from app.vector_store.base import Vector, VectorMatch, VectorStore, VectorStoreError


def make_face(
    x: float = 10, y: float = 10, size: float = 100, nose_offset: float = 0.0, conf: float = 0.9
) -> FaceDetection:
    """Frontal face; `nose_offset` shifts the nose (fraction of half the eye distance)."""
    eye_y, half = y + size * 0.4, size * 0.2
    cx = x + size / 2
    return FaceDetection(
        bbox=BoundingBox(x, y, x + size, y + size),
        confidence=conf,
        landmarks=(
            (cx - half, eye_y),
            (cx + half, eye_y),
            (cx + nose_offset * half, y + size * 0.6),
            (cx - half, y + size * 0.8),
            (cx + half, y + size * 0.8),
        ),
    )


def noise_image(height: int = 240, width: int = 320) -> Image:
    """High-frequency texture: passes the sharpness check."""
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


def unit(*values: float) -> Vector:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


class FakeFaceDetector(FaceDetector):
    name = "fake-faces"

    def __init__(self, faces: list[FaceDetection] | None = None) -> None:
        self.faces = faces if faces is not None else [make_face()]

    def detect(self, image: Image) -> list[FaceDetection]:
        return list(self.faces)


class FakeEmbedder(FaceEmbeddingProvider):
    name = "fake-embedder"
    dimension = 3

    def __init__(self, vector: Vector | None = None) -> None:
        self.vector = vector if vector is not None else unit(1, 0, 0)
        self.calls = 0

    def embed(self, image: Image, face: FaceDetection) -> Vector:
        self.calls += 1
        return self.vector


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self.points: dict[str, tuple[int, Vector]] = {}
        self.down = False
        self.searches = 0

    def _check(self) -> None:
        if self.down:
            raise VectorStoreError("Qdrant search failed: ConnectError")

    def create_collection(self, dimension: int) -> None:
        self._check()

    def add_embedding(self, person_id: int, vector: Vector, model_name: str) -> str:
        self._check()
        vector_id = str(uuid.uuid4())
        self.points[vector_id] = (person_id, vector)
        return vector_id

    def search(self, vector: Vector, limit: int = 1) -> list[VectorMatch]:
        self._check()
        self.searches += 1
        scored = sorted(
            (
                VectorMatch(vid, pid, float(np.dot(vector, stored)))
                for vid, (pid, stored) in self.points.items()
            ),
            key=lambda m: m.score,
            reverse=True,
        )
        return scored[:limit]

    def delete_embedding(self, vector_id: str) -> None:
        self._check()
        self.points.pop(vector_id, None)

    def delete_person(self, person_id: int) -> None:
        self._check()
        self.points = {k: v for k, v in self.points.items() if v[0] != person_id}

    def health_check(self) -> bool:
        return not self.down


def make_service(
    *,
    faces: list[FaceDetection] | None = None,
    embedder: FakeEmbedder | None = None,
    store: InMemoryVectorStore | None = None,
    threshold: float = 0.5,
) -> FaceRecognitionService:
    thresholds = QualityThresholds(min_size=40, min_sharpness=30.0, max_yaw=0.5)
    return FaceRecognitionService(
        FakeFaceDetector(faces),
        embedder or FakeEmbedder(),
        FaceQualityChecker(thresholds),
        store or InMemoryVectorStore(),
        match_threshold=threshold,
        registration_quality=FaceQualityChecker(
            QualityThresholds(min_size=80, min_sharpness=30.0, max_yaw=0.5)
        ),
    )
