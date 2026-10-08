"""Builds AI components from settings. The only place that names concrete models."""

import logging
from dataclasses import dataclass, field

from app.config import Settings, VisionMode
from app.detection.base import Detector
from app.detection.person_detector import ModelLoadError, YoloxPersonDetector
from app.recognition.detector import FaceDetector, YuNetFaceDetector
from app.recognition.embedding import SFaceProvider
from app.recognition.quality import FaceQualityChecker, QualityThresholds
from app.recognition.service import FaceRecognitionService
from app.tracking.tracker import ByteTracker, Tracker, TrackerConfig
from app.vector_store.base import VectorStore
from app.vector_store.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


@dataclass
class AIComponents:
    person_detector: Detector | None = None
    face_detector: FaceDetector | None = None
    recognition: FaceRecognitionService | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "error"
        if self.person_detector is None:
            return "not_configured"
        return "ok"

    def describe(self) -> dict[str, object]:
        return {
            "status": self.status,
            "person_detector": self.person_detector.name if self.person_detector else None,
            "face_detector": self.face_detector.name if self.face_detector else None,
            "face_embedder": self.recognition.embedder.name if self.recognition else None,
            "errors": list(self.errors),
        }


def build_tracker(settings: Settings) -> Tracker | None:
    """A fresh tracker per camera (track ids are per camera)."""
    if not settings.tracking_enabled:
        return None
    return ByteTracker(
        TrackerConfig(
            high_threshold=settings.person_confidence_threshold,
            low_threshold=settings.track_low_threshold,
            new_track_threshold=settings.track_new_threshold,
            match_iou=settings.track_match_iou,
            max_lost_seconds=settings.track_max_lost_seconds,
        )
    )


def build_vector_store(settings: Settings, timeout_seconds: float | None = None) -> VectorStore:
    api_key = settings.qdrant_api_key
    return QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        api_key=api_key.get_secret_value() if api_key is not None else None,
        timeout_seconds=timeout_seconds or settings.qdrant_timeout_seconds,
    )


def build_face_detector(settings: Settings) -> FaceDetector:
    return YuNetFaceDetector(
        settings.face_detector_model_path, score_threshold=settings.face_detection_threshold
    )


def build_recognition_service(
    settings: Settings, face_detector: FaceDetector | None = None
) -> FaceRecognitionService:
    """Raises `ModelLoadError` if a model file is missing or broken."""
    live = QualityThresholds(
        min_size=settings.face_min_size,
        min_sharpness=settings.face_min_sharpness,
        max_yaw=settings.face_max_yaw,
    )
    registration = QualityThresholds(
        min_size=settings.face_registration_min_size,
        min_sharpness=settings.face_min_sharpness,
        max_yaw=settings.face_max_yaw,
    )
    return FaceRecognitionService(
        face_detector or build_face_detector(settings),
        SFaceProvider(settings.face_embedding_model_path),
        FaceQualityChecker(live),
        build_vector_store(settings),
        match_threshold=settings.face_match_threshold,
        registration_quality=FaceQualityChecker(registration),
    )


def build_ai_components(settings: Settings) -> AIComponents:
    """Load models; a failure is reported, not raised, so capture keeps running."""
    components = AIComponents()

    if settings.person_detector_enabled:
        try:
            # ByteTrack needs low-score boxes too; the processor filters for display.
            score_threshold = (
                min(settings.track_low_threshold, settings.person_confidence_threshold)
                if settings.tracking_enabled
                else settings.person_confidence_threshold
            )
            components.person_detector = YoloxPersonDetector(
                settings.person_detector_model_path,
                score_threshold=score_threshold,
                nms_threshold=settings.person_nms_threshold,
                num_threads=settings.onnx_num_threads,
            )
        except ModelLoadError as exc:
            logger.error("%s (run: python -m scripts.download_models)", exc)
            components.errors.append(str(exc))

    # Privacy by design: anonymous mode never runs face analysis.
    if settings.vision_mode is VisionMode.RECOGNITION:
        try:
            components.face_detector = build_face_detector(settings)
            components.recognition = build_recognition_service(settings, components.face_detector)
        except ModelLoadError as exc:
            logger.error("%s (run: python -m scripts.download_models)", exc)
            components.errors.append(str(exc))
    return components
