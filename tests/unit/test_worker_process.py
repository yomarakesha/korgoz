from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import worker as worker_process
from app.config import Settings
from app.database.models import Camera


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
    assert sorted(c.camera_id for c in configs) == [1, 2]


def test_env_camera_overrides_database_source(db_cameras: Engine) -> None:
    configs = {
        c.camera_id: c
        for c in worker_process.load_camera_configs(settings(camera_id=2, camera_url="video.mp4"))
    }
    assert configs[2].source == "video.mp4"
    assert configs[2].name == "Hall"


def test_env_camera_works_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable() -> Engine:
        raise ConnectionError("db down")

    monkeypatch.setattr(worker_process, "get_engine", unreachable)
    configs = worker_process.load_camera_configs(settings(camera_url="0"))
    assert [(c.camera_id, c.source) for c in configs] == [(1, "0")]
