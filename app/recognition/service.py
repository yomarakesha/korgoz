"""Face recognition: quality check -> embedding -> vector search -> threshold.

No forced matching: if the best match is below FACE_MATCH_THRESHOLD the face is
UNKNOWN, even if it is the "closest" registered person.
"""

from dataclasses import dataclass

from app.camera.types import Image
from app.recognition.detector import FaceDetection, FaceDetector
from app.recognition.embedding import FaceEmbeddingProvider
from app.recognition.quality import FaceQualityChecker, QualityIssue
from app.vector_store.base import Vector, VectorStore


@dataclass(frozen=True, slots=True)
class Match:
    person_id: int
    score: float


@dataclass(frozen=True, slots=True)
class Unknown:
    score: float  # best (rejected) similarity, 0.0 if nobody is registered


Identity = Match | Unknown


class RegistrationError(ValueError):
    """The photo can't be used to register a person (shown to the API client)."""


class FaceRecognitionService:
    def __init__(
        self,
        detector: FaceDetector,
        embedder: FaceEmbeddingProvider,
        quality: FaceQualityChecker,
        store: VectorStore,
        *,
        match_threshold: float,
        registration_quality: FaceQualityChecker | None = None,
    ) -> None:
        self.detector = detector
        self.embedder = embedder
        self.quality = quality
        self.registration_quality = registration_quality or quality
        self.store = store
        self.match_threshold = match_threshold

    def identify(self, image: Image, face: FaceDetection) -> Identity | None:
        """Identity of a detected face; None if the face fails the quality check."""
        if not self.quality.check(image, face).ok:
            return None
        return self.match(self.embedder.embed(image, face))

    def match(self, vector: Vector) -> Identity:
        matches = self.store.search(vector, limit=1)
        if not matches:
            return Unknown(score=0.0)
        best = matches[0]
        if best.score < self.match_threshold:
            return Unknown(score=best.score)
        return Match(person_id=best.person_id, score=best.score)

    def registration_embedding(self, image: Image) -> Vector:
        """Embedding of the single good-quality face in a registration photo."""
        faces = self.detector.detect(image)
        if not faces:
            raise RegistrationError("No face found in the photo")
        if len(faces) > 1:
            raise RegistrationError(f"Expected one face, found {len(faces)}")
        report = self.registration_quality.check(image, faces[0])
        if report.issue is QualityIssue.TOO_SMALL:
            raise RegistrationError(
                f"Face is too small ({report.size:.0f}px, need "
                f"{self.registration_quality.thresholds.min_size}px)"
            )
        if report.issue is QualityIssue.BLURRY:
            raise RegistrationError("Face is too blurry")
        if report.issue is QualityIssue.NOT_FRONTAL:
            raise RegistrationError("Face is not frontal enough")
        return self.embedder.embed(image, faces[0])
