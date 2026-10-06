from collections.abc import Iterator
from typing import Any

import pytest

from app.config import get_settings
from app.pipeline.live_view import LiveViewHub, LiveViewServer

from .pipeline.test_live_view import analysis


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[LiveViewHub]:
    hub = LiveViewHub()
    server = LiveViewServer(hub, "127.0.0.1", 0)
    server.start()
    monkeypatch.setenv("LIVE_VIEW_PORT", str(server.port))
    get_settings.cache_clear()
    yield hub
    server.stop()


def test_snapshot_is_proxied(api_client: Any, worker: LiveViewHub) -> None:
    camera_id = api_client.post("/cameras", json={"name": "c", "stream_url": "0"}).json()["id"]
    worker(analysis())  # the fake frame belongs to camera 1
    assert camera_id == 1
    response = api_client.get("/cameras/1/snapshot")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8")  # JPEG magic


def test_unknown_camera_is_404(api_client: Any, worker: LiveViewHub) -> None:
    assert api_client.get("/cameras/42/snapshot").status_code == 404
    assert api_client.get("/cameras/42/stream").status_code == 404


def test_worker_down_is_503(api_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_VIEW_PORT", "1")
    get_settings.cache_clear()
    api_client.post("/cameras", json={"name": "c", "stream_url": "0"})
    assert api_client.get("/cameras/1/snapshot").status_code == 503
    assert api_client.get("/cameras/1/stream").status_code == 503
