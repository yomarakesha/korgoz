"""Video sources.

`FrameSource` is the minimal interface the worker needs; `VideoStream` implements
it with OpenCV. Tests use fake sources, and a future 360° source (dewarping)
can implement the same interface.
"""

import logging
import sys
from typing import Protocol
from urllib.parse import urlparse

import cv2

from app.camera.types import Image, SourceKind
from app.core.logging import redact

logger = logging.getLogger(__name__)

_NETWORK_SCHEMES = {"rtsp", "rtsps", "rtmp", "http", "https", "udp", "tcp"}


class CameraConnectionError(Exception):
    """The source could not be opened."""


class EndOfStream(Exception):
    """A non-looping video file has no more frames."""


class FrameSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> Image | None:
        """Return the next frame, or None on a (possibly transient) read failure."""
        ...

    def release(self) -> None: ...

    @property
    def nominal_fps(self) -> float | None:
        """Playback rate for files (used for real-time pacing); None for live sources."""
        ...


def usb_backend(platform: str = sys.platform) -> int:
    """OpenCV capture backend for local (USB) cameras on this OS."""
    if platform.startswith("linux"):
        return int(cv2.CAP_V4L2)
    if platform == "win32":
        # DirectShow opens much faster than the default Media Foundation backend.
        return int(cv2.CAP_DSHOW)
    if platform == "darwin":
        return int(cv2.CAP_AVFOUNDATION)
    return int(cv2.CAP_ANY)


def detect_source_kind(source: str) -> SourceKind:
    if source.strip().isdigit():
        return SourceKind.USB
    if urlparse(source).scheme.lower() in _NETWORK_SCHEMES:
        return SourceKind.NETWORK
    return SourceKind.FILE


class VideoStream:
    def __init__(
        self,
        source: str,
        *,
        loop_video: bool = True,
        open_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 5.0,
    ) -> None:
        self._source = source
        self._kind = detect_source_kind(source)
        self._loop_video = loop_video
        self._open_timeout_ms = int(open_timeout_seconds * 1000)
        self._read_timeout_ms = int(read_timeout_seconds * 1000)
        self._capture: cv2.VideoCapture | None = None
        self._nominal_fps: float | None = None

    @property
    def kind(self) -> SourceKind:
        return self._kind

    @property
    def nominal_fps(self) -> float | None:
        return self._nominal_fps

    def open(self) -> None:
        self.release()
        if self._kind is SourceKind.USB:
            capture = cv2.VideoCapture(int(self._source), usb_backend())
        else:
            # Without explicit timeouts a dead RTSP camera can block read() for ~30 s.
            params = [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                self._open_timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                self._read_timeout_ms,
            ]
            capture = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG, params)

        if not capture.isOpened():
            capture.release()
            raise CameraConnectionError(f"Cannot open video source {redact(self._source)}")

        if self._kind is SourceKind.NETWORK:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # prefer fresh frames over buffered ones
        fps = capture.get(cv2.CAP_PROP_FPS)
        self._nominal_fps = fps if self._kind is SourceKind.FILE and fps > 0 else None
        self._capture = capture

    def read(self) -> Image | None:
        if self._capture is None:
            return None
        ok, image = self._capture.read()
        if not ok and self._kind is SourceKind.FILE:
            if not self._loop_video:
                raise EndOfStream(redact(self._source))
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, image = self._capture.read()
        return image if ok else None  # type: ignore[return-value]

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
