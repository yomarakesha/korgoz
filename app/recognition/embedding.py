"""Face embeddings.

`FaceEmbeddingProvider` is the abstraction; `SFaceProvider` uses OpenCV's
SFace model (Apache-2.0, OpenCV Model Zoo): the face is aligned by the 5 YuNet
landmarks and mapped to an L2-normalised vector. Vectors are never written to disk.
"""

import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

from app.camera.types import Image
from app.detection.person_detector import ModelLoadError
from app.recognition.detector import FaceDetection
from app.vector_store.base import Vector

logger = logging.getLogger(__name__)


class FaceEmbeddingProvider(ABC):
    name: str
    dimension: int

    @abstractmethod
    def embed(self, image: Image, face: FaceDetection) -> Vector:
        """L2-normalised embedding of one detected face."""


def _face_row(face: FaceDetection) -> np.ndarray:
    """YuNet output row format expected by `FaceRecognizerSF.alignCrop`."""
    x1, y1 = face.bbox.x1, face.bbox.y1
    points = [coord for point in face.landmarks for coord in point]
    return np.array(
        [x1, y1, face.bbox.width, face.bbox.height, *points, face.confidence], dtype=np.float32
    )


class SFaceProvider(FaceEmbeddingProvider):
    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise ModelLoadError(f"Face embedding model not found: {model_path}")
        try:
            self._model = cv2.FaceRecognizerSF.create(str(model_path), "")
        except cv2.error as exc:
            raise ModelLoadError(f"Cannot load {model_path.name}: {exc}") from exc
        self._lock = threading.Lock()  # the OpenCV net is not safe for concurrent calls
        self.name = f"sface:{model_path.stem}"
        # Take the size from the model output instead of hard-coding it.
        probe = np.zeros((112, 112, 3), dtype=np.uint8)
        self.dimension = int(self._model.feature(probe).size)
        logger.info("Loaded %s (dim=%d)", self.name, self.dimension)

    def embed(self, image: Image, face: FaceDetection) -> Vector:
        with self._lock:
            aligned = self._model.alignCrop(image, _face_row(face))
            feature = self._model.feature(aligned)
        vector = np.asarray(feature, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector
