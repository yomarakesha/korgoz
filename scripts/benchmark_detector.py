"""Measure detector latency on this machine.

Usage:
    python -m scripts.benchmark_detector --source data/samples/vtest.avi
    python -m scripts.benchmark_detector --model models/yolox_tiny.onnx --threads 4
    python -m scripts.benchmark_detector --faces    # also YuNet face detection

Reports mean / p50 / p95 latency and single-stream throughput. These numbers
are for detection only (no capture, tracking or encoding).
"""

import argparse
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import cast

import cv2

from app.camera.types import Image
from app.detection.person_detector import YoloxPersonDetector
from app.recognition.detector import YuNetFaceDetector


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def load_frames(source: str, count: int) -> list[Image]:
    capture = cv2.VideoCapture(source)
    frames: list[Image] = []
    while len(frames) < count:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cast(Image, frame))
    capture.release()
    return frames


def report(name: str, timings: list[float]) -> None:
    ordered = sorted(timings)
    p95 = ordered[int(len(ordered) * 0.95) - 1]
    mean = statistics.mean(timings)
    print(
        f"{name:<28} mean {mean:6.1f} ms | p50 {statistics.median(timings):6.1f} ms | "
        f"p95 {p95:6.1f} ms | ~{1000 / mean:5.1f} FPS"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark KörGöz detectors")
    parser.add_argument("--source", default="data/samples/vtest.avi")
    parser.add_argument("--model", type=Path, default=Path("models/yolox_s.onnx"))
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--threads", type=int, default=0, help="ONNX threads, 0 = auto")
    parser.add_argument("--faces", action="store_true")
    args = parser.parse_args()

    frames = load_frames(args.source, args.frames)
    if not frames:
        print(f"Cannot read frames from {args.source}")
        return 1
    print(f"CPU: {cpu_name()} ({os.cpu_count()} logical cores)")
    print(f"Frames: {len(frames)} x {frames[0].shape[1]}x{frames[0].shape[0]} from {args.source}")

    detector = YoloxPersonDetector(args.model, num_threads=args.threads)
    detector.detect(frames[0])  # warm-up
    timings, persons = [], 0
    for frame in frames:
        started = time.perf_counter()
        persons += len(detector.detect(frame))
        timings.append((time.perf_counter() - started) * 1000)
    report(f"{detector.name} {detector.input_size[0]}px", timings)
    print(f"{'':<28} avg persons/frame: {persons / len(frames):.1f}")

    if args.faces:
        faces = YuNetFaceDetector(Path("models/face_detection_yunet_2023mar.onnx"))
        timings = []
        for frame in frames:
            started = time.perf_counter()
            faces.detect(frame)
            timings.append((time.perf_counter() - started) * 1000)
        report(faces.name, timings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
