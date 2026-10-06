from collections.abc import Iterator

import cv2
import httpx
import numpy as np
import pytest

from app.detection.base import BoundingBox, DetectionResult
from app.pipeline.annotate import annotate
from app.pipeline.live_view import BOUNDARY, LiveViewHub, LiveViewServer
from app.pipeline.types import FrameAnalysis

from .fakes import make_frame


def analysis(index: int = 0) -> FrameAnalysis:
    person = DetectionResult(BoundingBox(5, 5, 40, 45), 0.9)
    return FrameAnalysis(frame=make_frame(index), persons=[person], fresh=True)


def test_annotate_draws_on_a_copy() -> None:
    item = analysis()
    drawn = annotate(item)
    assert drawn.shape == item.frame.image.shape
    assert drawn.any()  # boxes and text were drawn
    assert not item.frame.image.any()  # original untouched


def test_hub_encodes_once_per_frame() -> None:
    hub = LiveViewHub()
    hub(analysis(0))
    first = hub.wait_jpeg(1, after_index=-1, timeout=1)
    again = hub.wait_jpeg(1, after_index=-1, timeout=1)
    assert first is not None and again is first  # served from cache
    assert hub.wait_jpeg(1, after_index=0, timeout=0.05) is None  # nothing newer
    assert hub.wait_jpeg(99, after_index=-1, timeout=0.05) is None  # unknown camera


@pytest.fixture
def server() -> Iterator[tuple[LiveViewHub, str]]:
    hub = LiveViewHub()
    live = LiveViewServer(hub, "127.0.0.1", 0, status_provider=lambda: {"ai": {"status": "ok"}})
    live.start()
    yield hub, f"http://127.0.0.1:{live.port}"
    live.stop()


def test_status_and_snapshot(server: tuple[LiveViewHub, str]) -> None:
    hub, base = server
    hub(analysis())
    assert httpx.get(f"{base}/status").json() == {"ai": {"status": "ok"}}

    response = httpx.get(f"{base}/cameras/1/snapshot.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None and image.shape == (48, 64, 3)


def test_unknown_routes_and_cameras(server: tuple[LiveViewHub, str]) -> None:
    _, base = server
    assert httpx.get(f"{base}/cameras/7/snapshot.jpg", timeout=5).status_code == 404
    assert httpx.get(f"{base}/nope").status_code == 404


def test_mjpeg_stream(server: tuple[LiveViewHub, str]) -> None:
    hub, base = server
    hub(analysis(0))
    with httpx.stream("GET", f"{base}/cameras/1/stream.mjpg", timeout=5) as response:
        assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
        chunk = next(response.iter_bytes())
    assert chunk.startswith(f"--{BOUNDARY}".encode())
