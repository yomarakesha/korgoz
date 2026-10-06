from pathlib import Path

import cv2
import numpy as np
import pytest

from app.camera.stream import CameraConnectionError, EndOfStream, VideoStream, detect_source_kind
from app.camera.types import SourceKind


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("0", SourceKind.USB),
        (" 2 ", SourceKind.USB),
        ("rtsp://admin:pw@10.0.0.5:554/s1", SourceKind.NETWORK),
        ("http://cam.local/mjpeg", SourceKind.NETWORK),
        ("data/videos/demo.mp4", SourceKind.FILE),
        ("/abs/path/video.avi", SourceKind.FILE),
    ],
)
def test_detect_source_kind(source: str, kind: SourceKind) -> None:
    assert detect_source_kind(source) is kind


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), 10.0, (64, 48))
    assert writer.isOpened()
    for i in range(5):
        writer.write(np.full((48, 64, 3), i * 40, dtype=np.uint8))
    writer.release()
    return path


def test_reads_video_file_then_ends(video_file: Path) -> None:
    stream = VideoStream(str(video_file), loop_video=False)
    stream.open()
    assert stream.nominal_fps == pytest.approx(10.0)
    frames = []
    with pytest.raises(EndOfStream):
        while True:
            image = stream.read()
            assert image is not None
            frames.append(image)
    stream.release()
    assert len(frames) == 5
    assert frames[0].shape == (48, 64, 3)


def test_looping_file_rewinds(video_file: Path) -> None:
    stream = VideoStream(str(video_file), loop_video=True)
    stream.open()
    images = [stream.read() for _ in range(12)]
    stream.release()
    assert all(image is not None for image in images)


def test_missing_file_raises_connection_error(tmp_path: Path) -> None:
    stream = VideoStream(str(tmp_path / "missing.mp4"), open_timeout_seconds=1)
    with pytest.raises(CameraConnectionError) as error:
        stream.open()
    assert "missing.mp4" in str(error.value)


def test_error_message_hides_credentials() -> None:
    stream = VideoStream("rtsp://admin:topsecret@127.0.0.1:1/none", open_timeout_seconds=1)
    with pytest.raises(CameraConnectionError) as error:
        stream.open()
    assert "topsecret" not in str(error.value)


def test_read_before_open_returns_none() -> None:
    assert VideoStream("0").read() is None
