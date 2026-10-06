"""One background thread per camera: connect, read, pace, publish, reconnect.

Every failure is contained inside the thread, so one broken camera never
affects the others.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.camera.buffer import FrameBuffer
from app.camera.stream import EndOfStream, FrameSource, VideoStream
from app.camera.types import CameraConfig, CameraStatus, Frame, Image
from app.core.logging import redact
from app.core.metrics import RateMeter

logger = logging.getLogger(__name__)

StatusListener = Callable[[int, CameraStatus], None]
SourceFactory = Callable[[CameraConfig], FrameSource]


@dataclass(frozen=True)
class WorkerOptions:
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    # Consecutive failed reads before the connection is considered lost.
    read_failure_threshold: int = 10
    open_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 5.0


@dataclass
class WorkerStats:
    frames_published: int = 0
    frames_skipped: int = 0  # dropped by the max_fps limit
    reconnects: int = 0
    measured_fps: float = 0.0  # smoothed published FPS
    last_frame_at: datetime | None = None


class CameraWorker:
    def __init__(
        self,
        config: CameraConfig,
        buffer: FrameBuffer | None = None,
        *,
        options: WorkerOptions | None = None,
        source_factory: SourceFactory | None = None,
        on_status: StatusListener | None = None,
    ) -> None:
        self.config = config
        self.buffer = buffer or FrameBuffer()
        self.options = options or WorkerOptions()
        self.stats = WorkerStats()
        self._source_factory = source_factory or self._default_source
        self._on_status = on_status
        self._status = CameraStatus.UNKNOWN
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_index = 0

    # --- lifecycle ---------------------------------------------------------

    @property
    def status(self) -> CameraStatus:
        return self._status

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"camera-{self.config.camera_id}", daemon=True
        )
        self._thread.start()

    def request_stop(self) -> None:
        """Signal the thread to finish without waiting for it."""
        self._stop.set()

    def stop(self, timeout: float = 10.0) -> None:
        self.request_stop()
        if self._thread is not None:
            self._thread.join(timeout)

    # --- internals ---------------------------------------------------------

    def _default_source(self, config: CameraConfig) -> FrameSource:
        return VideoStream(
            config.source,
            loop_video=config.loop_video,
            open_timeout_seconds=self.options.open_timeout_seconds,
            read_timeout_seconds=self.options.read_timeout_seconds,
        )

    def _set_status(self, status: CameraStatus) -> None:
        if status is self._status:
            return
        self._status = status
        logger.info("Camera %s (%s) is %s", self.config.camera_id, self.config.name, status.value)
        if self._on_status is not None:
            try:
                self._on_status(self.config.camera_id, status)
            except Exception:
                logger.exception("Status listener failed for camera %s", self.config.camera_id)

    def _run(self) -> None:
        try:
            self._connection_loop()
        except Exception:
            # Last-resort guard: a bug must not silently kill the thread.
            logger.exception("Camera %s worker crashed", self.config.camera_id)
            self._set_status(CameraStatus.ERROR)
        else:
            self._set_status(CameraStatus.OFFLINE)

    def _connection_loop(self) -> None:
        delay = self.options.reconnect_initial_delay_seconds
        while not self._stop.is_set():
            source = self._source_factory(self.config)
            try:
                source.open()
            except Exception as exc:
                source.release()
                logger.warning(
                    "Camera %s: cannot connect to %s (%s); retry in %.0fs",
                    self.config.camera_id,
                    redact(self.config.source),
                    type(exc).__name__,
                    delay,
                )
                self._set_status(CameraStatus.OFFLINE)
                self._stop.wait(delay)
                delay = min(delay * 2, self.options.reconnect_max_delay_seconds)
                continue

            delay = self.options.reconnect_initial_delay_seconds
            self._set_status(CameraStatus.ONLINE)
            try:
                finished = self._read_loop(source)
            finally:
                source.release()
            if finished:
                return
            self.stats.reconnects += 1
            self._set_status(CameraStatus.OFFLINE)

    def _read_loop(self, source: FrameSource) -> bool:
        """Read until stopped (True), end of file (True) or connection loss (False)."""
        failures = 0
        min_interval = 1.0 / self.config.max_fps if self.config.max_fps else 0.0
        rate = RateMeter()
        next_allowed = 0.0
        next_due = time.monotonic()

        while not self._stop.is_set():
            try:
                image = source.read()
            except EndOfStream:
                logger.info("Camera %s: end of video file", self.config.camera_id)
                return True
            except Exception:
                logger.exception("Camera %s: read error", self.config.camera_id)
                image = None

            if image is None:
                failures += 1
                if failures >= self.options.read_failure_threshold:
                    logger.warning(
                        "Camera %s: %d failed reads, reconnecting", self.config.camera_id, failures
                    )
                    return False
                continue
            failures = 0

            # Files are read faster than real time unless paced to their native FPS.
            if source.nominal_fps:
                next_due += 1.0 / source.nominal_fps
                wait = next_due - time.monotonic()
                if wait > 0:
                    self._stop.wait(wait)
                else:
                    next_due = time.monotonic()

            now = time.monotonic()
            if now < next_allowed:
                self.stats.frames_skipped += 1
                continue
            # Advance a schedule instead of measuring the gap to the previous frame:
            # a source slightly below max_fps with jittery timing loses no frames,
            # while a faster source is still capped at max_fps (at most one catch-up frame).
            next_allowed = max(next_allowed, now - min_interval) + min_interval
            rate.tick(now)
            self.stats.measured_fps = rate.rate
            self._publish(image)
        return True

    def _publish(self, image: Image) -> None:
        timestamp = datetime.now(UTC)
        self.buffer.put(
            Frame(
                camera_id=self.config.camera_id,
                index=self._frame_index,
                timestamp=timestamp,
                image=image,
            )
        )
        self._frame_index += 1
        self.stats.frames_published += 1
        self.stats.last_frame_at = timestamp
