"""Live view: latest annotated frame per camera, served as JPEG / MJPEG.

`LiveViewHub` is an `AnalysisSink`: it only keeps a reference to the newest
analysis (cheap). Annotation and JPEG encoding happen lazily when someone is
watching, and are cached per frame so several viewers share the work.

`LiveViewServer` is a tiny stdlib HTTP server inside the worker process. It
binds to localhost; browsers reach it through the API proxy, which will enforce
authentication (Phase 9). Nothing is written to disk.
"""

import json
import logging
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import cv2

from app.pipeline.annotate import annotate
from app.pipeline.types import FrameAnalysis

logger = logging.getLogger(__name__)

BOUNDARY = "korgozframe"
_ROUTE = re.compile(r"^/cameras/(\d+)/(snapshot\.jpg|stream\.mjpg)$")


class LiveViewHub:
    def __init__(self, jpeg_quality: int = 80) -> None:
        self._condition = threading.Condition()
        self._latest: dict[int, FrameAnalysis] = {}
        self._jpeg_cache: dict[int, tuple[int, bytes]] = {}  # camera -> (frame index, jpeg)
        self._quality = jpeg_quality

    def __call__(self, analysis: FrameAnalysis) -> None:
        with self._condition:
            self._latest[analysis.frame.camera_id] = analysis
            self._condition.notify_all()

    def cameras(self) -> list[int]:
        with self._condition:
            return sorted(self._latest)

    def wait_jpeg(
        self, camera_id: int, after_index: int, timeout: float
    ) -> tuple[int, bytes] | None:
        """Newest JPEG with frame index > after_index; None on timeout or unknown camera."""
        with self._condition:
            ready = self._condition.wait_for(
                lambda: camera_id in self._latest
                and self._latest[camera_id].frame.index > after_index,
                timeout=timeout,
            )
            if not ready:
                return None
            analysis = self._latest[camera_id]
            cached = self._jpeg_cache.get(camera_id)
            if cached is not None and cached[0] == analysis.frame.index:
                return cached
        # Encode outside the lock: it is the expensive part.
        ok, buffer = cv2.imencode(
            ".jpg", annotate(analysis), [cv2.IMWRITE_JPEG_QUALITY, self._quality]
        )
        if not ok:
            return None
        result = (analysis.frame.index, buffer.tobytes())
        with self._condition:
            self._jpeg_cache[camera_id] = result
        return result


StatusProvider = Callable[[], dict[str, Any]]


class LiveViewServer:
    def __init__(
        self,
        hub: LiveViewHub,
        host: str,
        port: int,
        status_provider: StatusProvider | None = None,
    ) -> None:
        handler = _make_handler(hub, status_provider or dict)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="live-view", daemon=True
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()
        logger.info("Live view server on %s:%d", *self._server.server_address[:2])

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _make_handler(
    hub: LiveViewHub, status_provider: StatusProvider
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("live view: " + format, *args)

        def do_GET(self) -> None:
            if self.path == "/status":
                self._send(200, "application/json", json.dumps(status_provider()).encode())
                return
            match = _ROUTE.match(self.path)
            if match is None:
                self._send(404, "text/plain", b"not found")
                return
            camera_id = int(match.group(1))
            if match.group(2) == "snapshot.jpg":
                self._snapshot(camera_id)
            else:
                self._stream(camera_id)

        def _send(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _snapshot(self, camera_id: int) -> None:
            result = hub.wait_jpeg(camera_id, after_index=-1, timeout=2.0)
            if result is None:
                self._send(404, "text/plain", b"no frames for this camera")
                return
            self._send(200, "image/jpeg", result[1])

        def _stream(self, camera_id: int) -> None:
            first = hub.wait_jpeg(camera_id, after_index=-1, timeout=2.0)
            if first is None:
                self._send(404, "text/plain", b"no frames for this camera")
                return
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            result: tuple[int, bytes] | None = first
            last_index = -1
            try:
                while True:
                    if result is not None:
                        last_index, jpeg = result
                        self.wfile.write(
                            f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                            f"Content-Length: {len(jpeg)}\r\n\r\n".encode() + jpeg + b"\r\n"
                        )
                        self.wfile.flush()
                    result = hub.wait_jpeg(camera_id, last_index, timeout=5.0)
            except (BrokenPipeError, ConnectionResetError):
                pass  # viewer closed the page

    return Handler
