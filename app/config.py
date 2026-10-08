"""Application configuration.

All settings come from environment variables (or a local `.env` file during
development). Secrets are wrapped in `SecretStr` so they never show up in
`repr()`, logs or tracebacks by accident.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionMode(StrEnum):
    """Operating mode of the platform (see README, "Modes")."""

    ANONYMOUS = "anonymous"
    RECOGNITION = "recognition"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General ---------------------------------------------------------
    app_name: str = "KörGöz"
    environment: str = "development"
    log_level: LogLevel = LogLevel.INFO
    vision_mode: VisionMode = VisionMode.ANONYMOUS

    # --- API -------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # --- Storage ---------------------------------------------------------
    # Required: contains credentials, so there is intentionally no default.
    database_url: SecretStr
    database_echo: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "korgoz_faces"
    qdrant_timeout_seconds: float = Field(default=5.0, gt=0)
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    # --- Camera (single-camera MVP defaults) -----------------------------
    # If CAMERA_URL is set, the worker runs this camera in addition to the
    # enabled cameras stored in the database (env wins on an id clash).
    # USB webcam: "0"; RTSP: "rtsp://user:pass@host:554/stream"; or a video file path.
    camera_id: int = Field(default=1, ge=1)
    camera_url: SecretStr | None = None
    camera_max_fps: float | None = Field(default=15.0, gt=0)
    camera_loop_video: bool = True
    camera_open_timeout_seconds: float = Field(default=5.0, gt=0)
    camera_read_timeout_seconds: float = Field(default=5.0, gt=0)
    camera_reconnect_initial_delay_seconds: float = Field(default=1.0, gt=0)
    camera_reconnect_max_delay_seconds: float = Field(default=30.0, gt=0)
    camera_read_failure_threshold: int = Field(default=10, ge=1)

    # --- Vision pipeline -------------------------------------------------
    # Run detection on every N-th frame; tracking fills the gaps.
    detection_interval: int = Field(default=3, ge=1)
    person_detector_enabled: bool = True
    person_detector_model_path: Path = Path("models/yolox_s.onnx")
    person_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    person_nms_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    # 0 = let ONNX Runtime decide (all physical cores).
    onnx_num_threads: int = Field(default=0, ge=0)
    # Face detection runs only in recognition mode (anonymous mode never looks at faces).
    face_detector_model_path: Path = Path("models/face_detection_yunet_2023mar.onnx")
    face_detection_threshold: float = Field(default=0.8, ge=0.0, le=1.0)

    # --- Tracking (ByteTrack) ---------------------------------------------
    # PERSON_CONFIDENCE_THRESHOLD is the "high" score; boxes between
    # TRACK_LOW_THRESHOLD and it only extend existing tracks.
    tracking_enabled: bool = True
    track_low_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    track_new_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    track_match_iou: float = Field(default=0.2, gt=0.0, le=1.0)
    track_max_lost_seconds: float = Field(default=3.0, gt=0.0)
    track_flush_interval_seconds: float = Field(default=5.0, gt=0.0)

    # --- Recognition (recognition mode only) -----------------------------
    face_embedding_model_path: Path = Path("models/face_recognition_sface_2021dec.onnx")
    # Cosine similarity; below it the face is UNKNOWN (no forced matching).
    # Calibrated on sample portraits: same person 0.74-0.78, different people <= 0.25.
    face_match_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    # Quality gate. Registration photos must pass it; live faces below it are skipped.
    face_min_size: int = Field(default=40, ge=8)  # pixels, shorter side of the face box
    face_registration_min_size: int = Field(default=80, ge=8)
    face_min_sharpness: float = Field(default=30.0, ge=0.0)  # variance of the Laplacian
    face_max_yaw: float = Field(default=0.5, ge=0.0, le=1.0)  # 0 = frontal, 1 = profile
    # Per track: retry recognition at most this often until the person is identified.
    recognition_interval_seconds: float = Field(default=1.0, gt=0.0)
    face_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    # --- Events -----------------------------------------------------------
    events_enabled: bool = True
    # The same event (type + person, or type + track) is stored at most once per window.
    event_cooldown_seconds: float = Field(default=30.0, ge=0.0)
    # PERSON_UNKNOWN only after this many good-quality faces of a track matched nobody.
    unknown_after_attempts: int = Field(default=3, ge=1)

    # --- Analytics ----------------------------------------------------------
    # IANA zone for hourly buckets and peak hours, e.g. "Asia/Tashkent".
    analytics_timezone: str = "UTC"

    # --- Dashboard ----------------------------------------------------------
    # Built React app (cd frontend && npm run build), served by the API at /ui.
    dashboard_dir: Path = Path("frontend/dist")
    # Extra browser origins allowed to call the API, e.g. ["http://localhost:5173"].
    # Not needed for /ui or the Vite dev server (it proxies the API).
    cors_origins: list[str] = Field(default_factory=list)

    # --- Live view (served by the worker, proxied by the API) ------------
    live_view_enabled: bool = True
    live_view_host: str = "127.0.0.1"
    live_view_port: int = Field(default=8001, ge=1, le=65535)
    live_view_jpeg_quality: int = Field(default=80, ge=10, le=100)

    @field_validator("analytics_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA time zone: {value!r}") from exc
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached after the first call)."""
    return Settings()
