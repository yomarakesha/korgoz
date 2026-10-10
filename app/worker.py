"""Camera worker process.

Run:  python -m app.worker

For every camera (enabled cameras from the database plus the optional
CAMERA_URL camera) it runs a capture thread and a processing thread:

    CameraWorker -> FrameBuffer -> FrameProcessor (detection, tracking)
        -> TrackStore -> EventEngine -> RecognitionSink -> LiveViewHub

Tracks, sessions and events are written by one DatabaseWriter thread.

Camera status goes to the database; live view and worker status are served on
LIVE_VIEW_HOST:LIVE_VIEW_PORT for the API to proxy.
"""

import logging
import signal
import threading
import time
from collections.abc import Callable
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
from app.database.models import Camera, Person
from app.database.session import get_engine
from app.database.writer import DatabaseWriter
from app.events.engine import EventEngine
from app.events.store import EventStore
from app.pipeline.factory import AIComponents, build_ai_components, build_tracker
from app.pipeline.live_view import LiveViewHub, LiveViewServer
from app.pipeline.processor import FrameProcessor
from app.pipeline.types import AnalysisSink
from app.recognition.sink import RecognitionSink
from app.tracking.store import TrackStore

logger = logging.getLogger("app.worker")

STATS_INTERVAL_SECONDS = 10.0
TICK_SECONDS = 1.0


def load_camera_configs(settings: Settings) -> list[CameraConfig] | None:
    """Enabled cameras plus the CAMERA_URL camera; None if the database is unreachable."""
    configs: dict[int, CameraConfig] = {}
    database_ok = True
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
        database_ok = False

    if settings.camera_url is not None:
        configs[settings.camera_id] = CameraConfig(
            camera_id=settings.camera_id,
            name=configs[settings.camera_id].name if settings.camera_id in configs else "env",
            source=settings.camera_url.get_secret_value(),
            max_fps=settings.camera_max_fps,
            loop_video=settings.camera_loop_video,
        )
    elif not database_ok:
        return None
    return list(configs.values())


class PersonNames:
    """person_id -> name from the database, cached (names are only shown in live view)."""

    def __init__(self) -> None:
        self._cache: dict[int, str] = {}

    def __call__(self, person_id: int) -> str | None:
        if person_id in self._cache:
            return self._cache[person_id]
        try:
            with Session(get_engine()) as session:
                person = session.get(Person, person_id)
        except Exception as exc:
            logger.warning("Cannot load person name: %s", type(exc).__name__)
            return None
        if person is None:
            return None
        self._cache[person_id] = person.name
        return person.name


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
        # One writer thread for tracks, sessions and events keeps them in order
        # (an event's track row is always written before the event).
        self.writer = DatabaseWriter(get_engine())
        self.events: EventEngine | None = None
        if settings.events_enabled:
            self.events = EventEngine(
                EventStore(self.writer),
                cooldown_seconds=settings.event_cooldown_seconds,
                unknown_after_attempts=settings.unknown_after_attempts,
            )
        self.manager = CameraManager(options=worker_options(settings), on_status=self._on_status)
        self.track_store: TrackStore | None = None
        self.recognition: RecognitionSink | None = None
        sinks: list[AnalysisSink] = []
        if settings.tracking_enabled:
            self.track_store = TrackStore(
                get_engine(), settings.track_flush_interval_seconds, writer=self.writer
            )
            sinks.append(self.track_store)
        if self.events is not None:
            # After TrackStore (its track rows are queued first) and before recognition
            # (a track's TRACK_STARTED comes before its PERSON_RECOGNIZED).
            sinks.append(self.events)
        if ai.recognition is not None and settings.tracking_enabled:
            # Recognition is per track, so it needs tracking.
            self.recognition = RecognitionSink(
                ai.recognition,
                interval_seconds=settings.recognition_interval_seconds,
                resolve_name=PersonNames(),
                on_result=self.events.on_recognition if self.events else None,
            )
            sinks.append(self.recognition)
        elif ai.recognition is not None:
            logger.warning("Recognition needs TRACKING_ENABLED=true; faces will not be identified")
        self.hub = LiveViewHub(
            settings.live_view_jpeg_quality,
            labels=self.recognition.labels if self.recognition else None,
        )
        if settings.live_view_enabled:
            sinks.append(self.hub)
        self.sinks = sinks

        # Cameras are added and removed while the live view thread reads `status()`.
        self._lock = threading.Lock()
        self._configs: dict[int, CameraConfig] = {}
        self.processors: dict[int, FrameProcessor] = {}
        for config in configs:
            self._add(config)
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

    def _add(self, config: CameraConfig) -> FrameProcessor:
        capture = self.manager.add(config)
        processor = FrameProcessor(
            config.camera_id,
            capture.buffer,
            detector=self.ai.person_detector,
            face_detector=self.ai.face_detector,
            detection_interval=self.settings.detection_interval,
            sinks=self.sinks,
            tracker=build_tracker(self.settings),
            min_person_confidence=self.settings.person_confidence_threshold,
        )
        with self._lock:
            self._configs[config.camera_id] = config
            self.processors[config.camera_id] = processor
        return processor

    def _close_tracks(self, camera_id: int, processor: FrameProcessor) -> None:
        closed = processor.close_tracks()
        if self.track_store is not None:
            self.track_store.end_tracks(camera_id, closed)
        if self.events is not None:
            self.events.end_tracks(camera_id, closed)

    def remove_camera(self, camera_id: int) -> None:
        """Stop one camera, end its open tracks and mark it offline."""
        with self._lock:
            processor = self.processors.pop(camera_id)
            self._configs.pop(camera_id)
        processor.request_stop()
        self.manager.remove(camera_id)  # joins the capture thread
        processor.stop()
        self._close_tracks(camera_id, processor)
        self.hub.forget(camera_id)
        self.recorder(camera_id, CameraStatus.OFFLINE)

    def add_camera(self, config: CameraConfig) -> None:
        if self.track_store is not None:
            self.track_store.close_orphans([config.camera_id])
        processor = self._add(config)
        processor.start()
        self.manager.get(config.camera_id).start()

    def sync_cameras(self, configs: list[CameraConfig]) -> None:
        """Apply the current camera list: start new, stop removed, restart changed ones."""
        wanted = {config.camera_id: config for config in configs}
        with self._lock:
            current = dict(self._configs)
        for camera_id, config in current.items():
            if wanted.get(camera_id) != config:
                logger.info("Camera %s removed, disabled or changed: stopping", camera_id)
                self.remove_camera(camera_id)
        for camera_id, config in wanted.items():
            if current.get(camera_id) != config:
                logger.info("Starting camera %s (%s)", camera_id, config.name)
                self.add_camera(config)

    def heartbeat(self) -> None:
        online = [
            camera_id
            for camera_id, status in self.manager.statuses().items()
            if status is CameraStatus.ONLINE
        ]
        self.recorder.heartbeat(online)

    def status(self) -> dict[str, Any]:
        cameras = {}
        with self._lock:
            processors = dict(self.processors)
        for worker in self.manager.workers():
            processor = processors.get(worker.config.camera_id)
            if processor is None:
                continue  # being added or removed right now
            latest = worker.buffer.latest()
            cameras[str(worker.config.camera_id)] = {
                "status": worker.status.value,
                "capture_fps": round(worker.stats.measured_fps, 1),
                "processing_fps": round(processor.stats.processing_fps, 1),
                "detection_ms": round(processor.stats.avg_detection_ms, 1),
                "active_tracks": processor.active_tracks,
                "resolution": (
                    f"{latest.image.shape[1]}x{latest.image.shape[0]}" if latest else None
                ),
            }
        return {
            "mode": self.settings.vision_mode.value,
            "ai": self.ai.describe(),
            "cameras": cameras,
        }

    def _on_status(self, camera_id: int, status: CameraStatus) -> None:
        self.recorder(camera_id, status)
        if self.events is not None:
            self.events.on_camera_status(camera_id, status)

    def start(self) -> None:
        if self.track_store is not None:
            self.track_store.close_orphans(list(self.processors))
        self.writer.start()
        if self.server is not None:
            self.server.start()
        for processor in self.processors.values():
            processor.start()
        self.manager.start_all()

    def stop(self) -> None:
        for processor in self.processors.values():
            processor.request_stop()
        self.manager.stop_all()
        for camera_id, processor in self.processors.items():
            processor.stop()
            self._close_tracks(camera_id, processor)
        self.writer.stop()  # writes everything still queued
        if self.server is not None:
            self.server.stop()
        # Threads report OFFLINE when they exit; make sure the DB agrees even if one hung.
        for camera_id in self.manager.statuses():
            self.recorder(camera_id, CameraStatus.OFFLINE)

    def log_stats(self) -> None:
        with self._lock:
            processors = dict(self.processors)
        for camera_id, info in self.status()["cameras"].items():
            processor = processors[int(camera_id)]
            logger.info(
                "Camera %s: status=%s capture_fps=%.1f processing_fps=%.1f "
                "detection=%.0fms detections=%d tracks=%d size=%s",
                camera_id,
                info["status"],
                info["capture_fps"],
                info["processing_fps"],
                info["detection_ms"],
                processor.stats.detections_run,
                info["active_tracks"],
                info["resolution"] or "-",
            )


def run_periodic(
    runtime: WorkerRuntime,
    settings: Settings,
    shutdown: threading.Event,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Stats, heartbeat and camera reload until `shutdown` is set."""
    reload_every = settings.camera_reload_interval_seconds
    now = clock()
    next_stats = now + STATS_INTERVAL_SECONDS
    next_heartbeat = now  # right away: status ONLINE needs a fresh heartbeat
    next_reload = now + reload_every
    while not shutdown.wait(TICK_SECONDS):
        now = clock()
        if now >= next_heartbeat:
            runtime.heartbeat()
            next_heartbeat = now + settings.camera_heartbeat_seconds
        if reload_every > 0 and now >= next_reload:
            configs = load_camera_configs(settings)
            if configs is not None:  # database down: keep the cameras that run
                runtime.sync_cameras(configs)
            next_reload = now + reload_every
        if now >= next_stats:
            runtime.log_stats()
            next_stats = now + STATS_INTERVAL_SECONDS


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level.value)

    configs = load_camera_configs(settings) or []
    if not configs:
        if settings.camera_reload_interval_seconds == 0:
            logger.error("No cameras configured: add one via POST /cameras or set CAMERA_URL")
            return
        logger.warning("No cameras yet: waiting for one to be added via POST /cameras")

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
    run_periodic(runtime, settings, shutdown)
    runtime.stop()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
