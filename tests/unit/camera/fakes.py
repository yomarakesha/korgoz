"""Fake frame sources for worker/manager tests (no OpenCV, no hardware)."""

import numpy as np

from app.camera.stream import CameraConnectionError, EndOfStream
from app.camera.types import CameraConfig, Image


def blank_image() -> Image:
    return np.zeros((4, 4, 3), dtype=np.uint8)


class FakeSource:
    """Yields frames forever; can fail to open or start failing reads."""

    def __init__(
        self,
        *,
        fail_open: bool = False,
        fail_reads_after: int | None = None,
        frames: int | None = None,
        nominal_fps: float | None = None,
    ) -> None:
        self.fail_open = fail_open
        self.fail_reads_after = fail_reads_after
        self.frames = frames
        self._nominal_fps = nominal_fps
        self.reads = 0
        self.released = False

    @property
    def nominal_fps(self) -> float | None:
        return self._nominal_fps

    def open(self) -> None:
        if self.fail_open:
            raise CameraConnectionError("fake: cannot open")

    def read(self) -> Image | None:
        self.reads += 1
        if self.frames is not None and self.reads > self.frames:
            raise EndOfStream("fake")
        if self.fail_reads_after is not None and self.reads > self.fail_reads_after:
            return None
        return blank_image()

    def release(self) -> None:
        self.released = True


class SequenceFactory:
    """Returns the given sources one by one, then repeats the last one."""

    def __init__(self, *sources: FakeSource) -> None:
        self.sources = list(sources)
        self.calls = 0

    def __call__(self, _config: CameraConfig) -> FakeSource:
        source = self.sources[min(self.calls, len(self.sources) - 1)]
        self.calls += 1
        return source
