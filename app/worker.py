"""Camera worker process.

Run:  python -m app.worker

For every camera (enabled cameras from the database plus the optional
CAMERA_URL camera) it runs a capture thread and a processing thread:

    CameraWorker -> FrameBuffer -> FrameProcessor (detection) -> LiveViewHub

Camera status goes to the database; live view and worker status are served on
LIVE_VIEW_HOST:LIVE_VIEW_PORT for the API to proxy.
"""

import logging
import signal
import threading
from types import FrameType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.camera.manager import CameraManager
from app.camera.status_store import DatabaseStatusRecorder
from app.camera.types import CameraConfig, CameraStatus
from app.camera.worker import WorkerOptions
from app.config import Settings, get_settings
from app.core.logging import setup_logging
from app.database.models import Camera
from app.database.session import get_engine
from app.pipeline.factory import AIComponents, build_ai_components
from app.pipeline.live_view import LiveViewHub, LiveViewServer
from app.pipeline.processor import FrameProcessor

logger = logging.getLogger("app.worker")

STATS_INTERVAL_SECONDS = 10.0


def load_camera_configs(settings: Settings) -> list[CameraConfig]:
    configs: dict[int, CameraConfig] = {}
    try:
        with Session(get_engine()) as session:
            for camera in session.scalars(select(Camera).where(Camera.enabled.is_(True))):
                configs[camera.id] = CameraConfig(
                    camera_id=camera.id,
                    name=camera.name,
                    source=camera.stream_url,
                    max_fps=settings.camera_max_fps,
                    loop_video=settings.camera_loop_video,
                )
    except Exception as exc:
        logger.error("Cannot load cameras from the database: %s", type(exc).__name__)

    if settings.camera_url is not None:
        configs[settings.camera_id] = CameraConfig(
            camera_id=settings.camera_id,
            name=configs[settings.camera_id].name if settings.camera_id in configs else "env",
            source=settings.camera_url.get_secret_value(),
            max_fps=settings.camera_max_fps,
            loop_video=settings.camera_loop_video,
        )
    return list(configs.values())


def worker_options(settings: Settings) -> WorkerOptions:
    return WorkerOptions(
        reconnect_initial_delay_seconds=settings.camera_reconnect_initial_delay_seconds,
        reconnect_max_delay_seconds=settings.camera_reconnect_max_delay_seconds,
        read_failure_threshold=settings.camera_read_failure_threshold,
        open_timeout_seconds=settings.camera_open_timeout_seconds,
        read_timeout_seconds=settings.camera_read_timeout_seconds,
    )


class WorkerRuntime:
    """Wires cameras, processors and live view together."""

    def __init__(self, settings: Settings, configs: list[CameraConfig], ai: AIComponents) -> None:
        self.settings = settings
        self.ai = ai
        self.recorder = DatabaseStatusRecorder(get_engine())
        self.manager = CameraManager(options=worker_options(settings), on_status=self.recorder)
        self.hub = LiveViewHub(settings.live_view_jpeg_quality)
        self.processors: dict[int, FrameProcessor] = {}
        for config in configs:
            capture = self.manager.add(config)
            self.processors[config.camera_id] = FrameProcessor(
                config.camera_id,
                capture.buffer,
                detector=ai.person_detector,
                face_detector=ai.face_detector,
                detection_interval=settings.detection_interval,
                sinks=[self.hub] if settings.live_view_enabled else [],
            )
        self.server: LiveViewServer | None = None
        if settings.live_view_enabled:
            try:
                self.server = LiveViewServer(
                    self.hub, settings.live_view_host, settings.live_view_port, self.status
                )
            except OSError as exc:
                logger.error(
                    "Live view disabled: cannot bind %s:%d (%s)",
                    settings.live_view_host,
                    settings.live_view_port,
                    exc.strerror,
                )

    def status(self) -> dict[str, Any]:
        cameras = {}
        for worker in self.manager.workers():
            processor = self.processors[worker.config.camera_id]
            latest = worker.buffer.latest()
            cameras[str(worker.config.camera_id)] = {
                "status": worker.status.value,
                "capture_fps": round(worker.stats.measured_fps, 1),
                "processing_fps": round(processor.stats.processing_fps, 1),
                "detection_ms": round(processor.stats.avg_detection_ms, 1),
                "resolution": (
                    f"{latest.image.shape[1]}x{latest.image.shape[0]}" if latest else None
                ),
            }
        return {
            "mode": self.settings.vision_mode.value,
            "ai": self.ai.describe(),
            "cameras": cameras,
        }

    def start(self) -> None:
        if self.server is not None:
            self.server.start()
        for processor in self.processors.values():
            processor.start()
        self.manager.start_all()

    def stop(self) -> None:
        for processor in self.processors.values():
            processor.request_stop()
        self.manager.stop_all()
        for processor in self.processors.values():
            processor.stop()
        if self.server is not None:
            self.server.stop()
        # Threads report OFFLINE when they exit; make sure the DB agrees even if one hung.
        for camera_id in self.manager.statuses():
            self.recorder(camera_id, CameraStatus.OFFLINE)

    def log_stats(self) -> None:
        for camera_id, info in self.status()["cameras"].items():
            processor = self.processors[int(camera_id)]
            logger.info(
                "Camera %s: status=%s capture_fps=%.1f processing_fps=%.1f "
                "detection=%.0fms detections=%d size=%s",
                camera_id,
                info["status"],
                info["capture_fps"],
                info["processing_fps"],
                info["detection_ms"],
                processor.stats.detections_run,
                info["resolution"] or "-",
            )


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level.value)

    configs = load_camera_configs(settings)
    if not configs:
        logger.error("No cameras configured: add one via POST /cameras or set CAMERA_URL")
        return

    runtime = WorkerRuntime(settings, configs, build_ai_components(settings))
    shutdown = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "Starting %d camera(s), mode=%s, ai=%s",
        len(configs),
        settings.vision_mode.value,
        runtime.ai.status,
    )
    runtime.start()
    while not shutdown.wait(STATS_INTERVAL_SECONDS):
        runtime.log_stats()
    runtime.stop()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
