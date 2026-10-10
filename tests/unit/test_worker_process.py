import threading
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app import worker as worker_process
from app.camera.manager import CameraManager
from app.camera.types import CameraConfig, CameraStatus
from app.config import Settings
from app.database.base import Base
from app.database.models import Camera
from app.pipeline.factory import AIComponents
from tests.unit.camera.fakes import FakeSource


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, database_url="sqlite://", **values)


@pytest.fixture
def db_cameras(sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    with Session(sqlite_engine) as session:
        session.add_all(
            [
                Camera(id=1, name="Entrance", stream_url="rtsp://a:b@h/1"),
                Camera(id=2, name="Hall", stream_url="1"),
                Camera(id=3, name="Disabled", stream_url="2", enabled=False),
            ]
        )
        session.commit()
    monkeypatch.setattr(worker_process, "get_engine", lambda: sqlite_engine)
    return sqlite_engine


def test_loads_enabled_cameras_from_database(db_cameras: Engine) -> None:
    configs = worker_process.load_camera_configs(settings())
    assert configs is not None
    assert sorted(c.camera_id for c in configs) == [1, 2]


def test_env_camera_overrides_database_source(db_cameras: Engine) -> None:
    loaded = worker_process.load_camera_configs(settings(camera_id=2, camera_url="video.mp4"))
    assert loaded is not None
    configs = {c.camera_id: c for c in loaded}
    assert configs[2].source == "video.mp4"
    assert configs[2].name == "Hall"


def test_env_camera_works_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable() -> Engine:
        raise ConnectionError("db down")

    monkeypatch.setattr(worker_process, "get_engine", unreachable)
    configs = worker_process.load_camera_configs(settings(camera_url="0"))
    assert configs is not None
    assert [(c.camera_id, c.source) for c in configs] == [(1, "0")]


def test_unreachable_database_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """None (not []) so the worker keeps its cameras instead of stopping them all."""

    def unreachable() -> Engine:
        raise ConnectionError("db down")

    monkeypatch.setattr(worker_process, "get_engine", unreachable)
    assert worker_process.load_camera_configs(settings()) is None


def _wait_for(condition: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


@pytest.fixture
def file_cameras(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Like `db_cameras`, but in a file: the runtime uses the DB from several threads,
    and the shared in-memory SQLite connection is not safe for that."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Camera(id=1, name="Entrance", stream_url="rtsp://a:b@h/1"),
                Camera(id=2, name="Hall", stream_url="1"),
                Camera(id=3, name="Disabled", stream_url="2", enabled=False),
            ]
        )
        session.commit()
    monkeypatch.setattr(worker_process, "get_engine", lambda: engine)
    yield engine
    engine.dispose()


@pytest.fixture
def runtime(file_cameras: Engine, monkeypatch: pytest.MonkeyPatch) -> Any:
    fake_manager = partial(CameraManager, source_factory=lambda _config: FakeSource())
    monkeypatch.setattr(worker_process, "CameraManager", fake_manager)
    configs = worker_process.load_camera_configs(settings())
    assert configs is not None
    runtime = worker_process.WorkerRuntime(
        settings(live_view_enabled=False), configs, AIComponents()
    )
    runtime.start()
    yield runtime
    runtime.stop()


def _statuses(engine: Engine) -> dict[int, CameraStatus]:
    with Session(engine) as session:
        return {c.id: c.status for c in session.query(Camera)}


def test_sync_starts_new_and_stops_removed_cameras(runtime: Any, file_cameras: Engine) -> None:
    assert sorted(runtime.processors) == [1, 2]
    _wait_for(lambda: runtime.manager.online_count == 2)

    with Session(file_cameras) as session, session.begin():
        hall = session.get(Camera, 2)
        assert hall is not None
        hall.enabled = False
        disabled = session.get(Camera, 3)
        assert disabled is not None
        disabled.enabled = True
    runtime.sync_cameras(worker_process.load_camera_configs(settings()))

    assert sorted(runtime.processors) == [1, 3]
    assert sorted(c.config.camera_id for c in runtime.manager.workers()) == [1, 3]
    _wait_for(lambda: _statuses(file_cameras)[3] is CameraStatus.ONLINE)
    assert _statuses(file_cameras)[2] is CameraStatus.OFFLINE
    assert sorted(runtime.status()["cameras"]) == ["1", "3"]


def test_sync_restarts_a_camera_whose_source_changed(runtime: Any) -> None:
    before = runtime.processors[1]
    changed = CameraConfig(1, "Entrance", "rtsp://a:b@h/2", 15.0, True)
    runtime.sync_cameras([changed, runtime._configs[2]])
    assert runtime.processors[1] is not before
    assert runtime.processors[1].is_alive
    assert not before.is_alive
    runtime.sync_cameras([changed, runtime._configs[2]])  # unchanged: nothing restarts
    assert runtime.processors[1].is_alive


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def heartbeat(self) -> None:
        self.calls.append("heartbeat")

    def sync_cameras(self, _configs: list[CameraConfig]) -> None:
        self.calls.append("sync")

    def log_stats(self) -> None:
        self.calls.append("stats")


def test_periodic_heartbeat_reload_and_stats(
    db_cameras: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_process, "TICK_SECONDS", 0.0)
    fake = _FakeRuntime()
    shutdown = threading.Event()
    ticks = iter([0.0, 5.0, 10.0, 15.0, 20.0])

    def clock() -> float:
        try:
            return next(ticks)
        except StopIteration:
            shutdown.set()
            return 20.0

    worker_process.run_periodic(
        fake,  # type: ignore[arg-type]
        settings(camera_reload_interval_seconds=10, camera_heartbeat_seconds=10),
        shutdown,
        clock,
    )
    # t=5: heartbeat; t=10: sync + stats; t=15: heartbeat; t=20: sync + stats
    assert fake.calls == ["heartbeat", "sync", "stats", "heartbeat", "sync", "stats"]
