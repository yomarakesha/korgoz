"""Owns all camera workers. Adding a camera never touches the AI pipeline."""

import logging

from app.camera.buffer import FrameBuffer
from app.camera.types import CameraConfig, CameraStatus
from app.camera.worker import CameraWorker, SourceFactory, StatusListener, WorkerOptions

logger = logging.getLogger(__name__)


class CameraManager:
    def __init__(
        self,
        *,
        options: WorkerOptions | None = None,
        on_status: StatusListener | None = None,
        source_factory: SourceFactory | None = None,
    ) -> None:
        self._options = options or WorkerOptions()
        self._on_status = on_status
        self._source_factory = source_factory
        self._workers: dict[int, CameraWorker] = {}

    def add(self, config: CameraConfig, *, start: bool = False) -> CameraWorker:
        if config.camera_id in self._workers:
            raise ValueError(f"Camera {config.camera_id} is already managed")
        worker = CameraWorker(
            config,
            FrameBuffer(),
            options=self._options,
            source_factory=self._source_factory,
            on_status=self._on_status,
        )
        self._workers[config.camera_id] = worker
        if start:
            worker.start()
        return worker

    def remove(self, camera_id: int) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()

    def start_all(self) -> None:
        for worker in self._workers.values():
            worker.start()

    def stop_all(self, timeout: float = 10.0) -> None:
        # Signal every worker first so they shut down in parallel.
        for worker in self._workers.values():
            worker.request_stop()
        for worker in self._workers.values():
            worker.stop(timeout)

    def get(self, camera_id: int) -> CameraWorker:
        return self._workers[camera_id]

    def workers(self) -> list[CameraWorker]:
        return list(self._workers.values())

    def statuses(self) -> dict[int, CameraStatus]:
        return {camera_id: w.status for camera_id, w in self._workers.items()}

    @property
    def online_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status is CameraStatus.ONLINE)
