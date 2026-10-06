import pytest

from app.camera.manager import CameraManager
from app.camera.types import CameraConfig, CameraStatus
from app.camera.worker import WorkerOptions

from .fakes import FakeSource
from .helpers import wait_until


def factory(config: CameraConfig) -> FakeSource:
    # Camera 2 is permanently broken; the others work.
    return FakeSource(fail_open=config.camera_id == 2)


def test_broken_camera_does_not_affect_others() -> None:
    manager = CameraManager(
        options=WorkerOptions(
            reconnect_initial_delay_seconds=0.01, reconnect_max_delay_seconds=0.02
        ),
        source_factory=factory,
    )
    for camera_id in (1, 2, 3):
        manager.add(CameraConfig(camera_id=camera_id, name=f"cam{camera_id}", source="fake"))
    manager.start_all()
    try:
        assert wait_until(
            lambda: manager.statuses()
            == {1: CameraStatus.ONLINE, 2: CameraStatus.OFFLINE, 3: CameraStatus.ONLINE}
        )
        assert manager.online_count == 2
        assert manager.get(1).buffer.latest() is not None
        assert manager.get(2).buffer.latest() is None
    finally:
        manager.stop_all()
    assert not any(w.is_alive for w in manager.workers())


def test_duplicate_camera_is_rejected() -> None:
    manager = CameraManager(source_factory=factory)
    manager.add(CameraConfig(camera_id=1, name="a", source="fake"))
    with pytest.raises(ValueError):
        manager.add(CameraConfig(camera_id=1, name="b", source="fake"))


def test_remove_stops_worker() -> None:
    manager = CameraManager(source_factory=factory)
    worker = manager.add(CameraConfig(camera_id=1, name="a", source="fake"), start=True)
    assert wait_until(lambda: worker.status is CameraStatus.ONLINE)
    manager.remove(1)
    assert not worker.is_alive
    assert manager.statuses() == {}
