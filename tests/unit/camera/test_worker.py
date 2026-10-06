import time

from app.camera.types import CameraConfig, CameraStatus, Image
from app.camera.worker import CameraWorker, WorkerOptions

from .fakes import FakeSource, SequenceFactory
from .helpers import wait_until

FAST = WorkerOptions(
    reconnect_initial_delay_seconds=0.01,
    reconnect_max_delay_seconds=0.02,
    read_failure_threshold=3,
)


def make_worker(
    factory: SequenceFactory, **config: object
) -> tuple[CameraWorker, list[CameraStatus]]:
    statuses: list[CameraStatus] = []
    worker = CameraWorker(
        CameraConfig(camera_id=7, name="test", source="fake", **config),  # type: ignore[arg-type]
        options=FAST,
        source_factory=factory,
        on_status=lambda _id, status: statuses.append(status),
    )
    return worker, statuses


def test_publishes_frames_and_goes_online() -> None:
    worker, statuses = make_worker(SequenceFactory(FakeSource()))
    worker.start()
    try:
        assert wait_until(lambda: worker.stats.frames_published >= 5)
        latest = worker.buffer.latest()
        assert latest is not None and latest.camera_id == 7
        assert wait_until(lambda: worker.status is CameraStatus.ONLINE)
    finally:
        worker.stop()
    assert statuses[0] is CameraStatus.ONLINE
    assert worker.status is CameraStatus.OFFLINE
    assert not worker.is_alive


def test_retries_until_camera_becomes_available() -> None:
    factory = SequenceFactory(FakeSource(fail_open=True), FakeSource(fail_open=True), FakeSource())
    worker, statuses = make_worker(factory)
    worker.start()
    try:
        assert wait_until(lambda: worker.status is CameraStatus.ONLINE)
    finally:
        worker.stop()
    assert factory.calls >= 3
    assert statuses[:2] == [CameraStatus.OFFLINE, CameraStatus.ONLINE]
    assert all(s.released for s in factory.sources[:2])


def test_reconnects_after_lost_connection() -> None:
    broken = FakeSource(fail_reads_after=2)
    factory = SequenceFactory(broken, FakeSource())
    worker, statuses = make_worker(factory)
    worker.start()
    try:
        assert wait_until(
            lambda: worker.stats.reconnects >= 1 and worker.stats.frames_published > 2
        )
    finally:
        worker.stop()
    assert broken.released
    assert statuses[:3] == [CameraStatus.ONLINE, CameraStatus.OFFLINE, CameraStatus.ONLINE]


def test_max_fps_skips_frames() -> None:
    worker, _ = make_worker(SequenceFactory(FakeSource()), max_fps=20.0)
    worker.start()
    try:
        assert wait_until(lambda: worker.stats.frames_skipped > 100)
    finally:
        worker.stop()
    # Fake source is far faster than 20 FPS, so almost everything is skipped.
    assert worker.stats.frames_published < worker.stats.frames_skipped


def test_end_of_file_stops_worker() -> None:
    worker, _ = make_worker(SequenceFactory(FakeSource(frames=3)), loop_video=False)
    worker.start()
    assert wait_until(lambda: not worker.is_alive)
    assert worker.stats.frames_published == 3
    assert worker.status is CameraStatus.OFFLINE


def test_failing_status_listener_does_not_kill_worker() -> None:
    def explode(_id: int, _status: CameraStatus) -> None:
        raise RuntimeError("listener bug")

    worker = CameraWorker(
        CameraConfig(camera_id=1, name="t", source="fake"),
        options=FAST,
        source_factory=SequenceFactory(FakeSource()),
        on_status=explode,
    )
    worker.start()
    try:
        assert wait_until(lambda: worker.stats.frames_published >= 3)
    finally:
        worker.stop()


def test_source_config_is_not_in_repr() -> None:
    config = CameraConfig(camera_id=1, name="t", source="rtsp://a:secret@h/s")
    assert "secret" not in repr(config)


class JitterySource(FakeSource):
    """~16.7 FPS on average, but frame gaps alternate between 40 ms and 80 ms."""

    def read(self) -> Image | None:
        time.sleep(0.04 if self.reads % 2 else 0.08)
        return super().read()


def test_jitter_below_max_fps_does_not_drop_frames() -> None:
    worker, _ = make_worker(SequenceFactory(JitterySource()), max_fps=20.0)
    worker.start()
    try:
        assert wait_until(lambda: worker.stats.frames_published >= 15)
    finally:
        worker.stop()
    # Measuring only the gap to the previous frame would drop every 40 ms frame (~half).
    assert worker.stats.frames_skipped <= 2
