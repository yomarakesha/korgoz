"""Quick check of a video source, independent of the database and the API.

Usage:
    python -m scripts.check_camera --source 0
    python -m scripts.check_camera --source "rtsp://user:pass@192.168.1.10:554/stream1"
    python -m scripts.check_camera --source data/videos/demo.mp4 --frames 200

Prints resolution and measured FPS and saves the last frame as a JPEG snapshot.
"""

import argparse
import sys
import time
from pathlib import Path

import cv2

from app.camera.stream import CameraConnectionError, EndOfStream, VideoStream
from app.core.logging import redact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="USB index, RTSP/HTTP URL or file path")
    parser.add_argument("--frames", type=int, default=100, help="frames to read")
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshot.jpg"))
    args = parser.parse_args()

    stream = VideoStream(args.source, loop_video=False)
    print(f"Source: {redact(args.source)} ({stream.kind.value})")
    try:
        stream.open()
    except CameraConnectionError as exc:
        print(f"FAIL: {exc}")
        return 1

    image = None
    read = failed = 0
    started = time.monotonic()
    try:
        while read < args.frames and failed < 20:
            try:
                frame = stream.read()
            except EndOfStream:
                break
            if frame is None:
                failed += 1
                continue
            image = frame
            read += 1
    finally:
        stream.release()
    elapsed = time.monotonic() - started

    if image is None:
        print("FAIL: connected but no frames received")
        return 1
    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.snapshot), image)
    print(f"OK: {read} frames, {image.shape[1]}x{image.shape[0]}, {read / elapsed:.1f} FPS")
    print(f"    failed reads: {failed}, snapshot: {args.snapshot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
