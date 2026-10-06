"""Latest-frame buffer between a camera worker (producer) and the pipeline (consumer).

Only the newest frame is kept. If processing is slower than the camera, old
frames are overwritten instead of queueing up, so analysis never drifts behind
real time.
"""

import threading

from app.camera.types import Frame


class FrameBuffer:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: Frame | None = None
        self._overwritten = 0
        self._consumed_index = -1

    def put(self, frame: Frame) -> None:
        with self._condition:
            if self._frame is not None and self._frame.index > self._consumed_index:
                self._overwritten += 1  # previous frame was never picked up
            self._frame = frame
            self._condition.notify_all()

    def latest(self) -> Frame | None:
        with self._condition:
            return self._frame

    def wait_next(self, after_index: int, timeout: float) -> Frame | None:
        """Block until a frame newer than `after_index` exists; None on timeout."""
        with self._condition:
            has_new = self._condition.wait_for(
                lambda: self._frame is not None and self._frame.index > after_index,
                timeout=timeout,
            )
            if not has_new or self._frame is None:
                return None
            self._consumed_index = self._frame.index
            return self._frame

    @property
    def overwritten(self) -> int:
        """Frames dropped because the consumer was too slow."""
        with self._condition:
            return self._overwritten
