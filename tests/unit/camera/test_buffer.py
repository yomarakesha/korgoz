import threading
from datetime import UTC, datetime

from app.camera.buffer import FrameBuffer
from app.camera.types import Frame

from .fakes import blank_image


def frame(index: int) -> Frame:
    return Frame(camera_id=1, index=index, timestamp=datetime.now(UTC), image=blank_image())


def test_keeps_only_latest_frame() -> None:
    buffer = FrameBuffer()
    assert buffer.latest() is None
    buffer.put(frame(0))
    buffer.put(frame(1))
    latest = buffer.latest()
    assert latest is not None and latest.index == 1
    assert buffer.overwritten == 1


def test_consumed_frames_are_not_counted_as_overwritten() -> None:
    buffer = FrameBuffer()
    buffer.put(frame(0))
    assert buffer.wait_next(after_index=-1, timeout=0.1) is not None
    buffer.put(frame(1))
    assert buffer.overwritten == 0


def test_wait_next_times_out_without_new_frame() -> None:
    buffer = FrameBuffer()
    buffer.put(frame(0))
    assert buffer.wait_next(after_index=0, timeout=0.05) is None


def test_wait_next_wakes_up_on_put() -> None:
    buffer = FrameBuffer()
    threading.Timer(0.05, buffer.put, args=(frame(0),)).start()
    received = buffer.wait_next(after_index=-1, timeout=2.0)
    assert received is not None and received.index == 0
