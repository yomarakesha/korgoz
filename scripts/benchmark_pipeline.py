"""Measure the whole camera pipeline on this machine with 1..N cameras.

Usage:
    python -m scripts.benchmark_pipeline                       # 1, 2 and 4 cameras, 30 s each
    python -m scripts.benchmark_pipeline --cameras 1,3 --seconds 60
    python -m scripts.benchmark_pipeline --model models/yolox_tiny.onnx --interval 1
    python -m scripts.benchmark_pipeline --live-view           # + one live view viewer per camera
    python -m scripts.benchmark_pipeline --recognition         # + face analysis (needs Qdrant)
    python -m scripts.benchmark_pipeline --markdown            # table for docs/benchmarks.md

Every camera reads the same source (a video file is paced to its native FPS, so it
behaves like a real camera). Frames go through the same components as in the
worker: capture -> FrameBuffer -> detection -> ByteTrack -> EventEngine
(-> recognition) (-> live view JPEG). Nothing is written to the database: in the
worker database writes run in a separate thread and are not on the frame path.

Latency = time from capture of a frame until the last sink has processed it.
Frames the processing thread could not keep up with are counted as dropped.
"""

import argparse
import os
import platform
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.camera.manager import CameraManager
from app.camera.types import CameraConfig
from app.camera.worker import CameraWorker
from app.config import Settings, VisionMode, get_settings
from app.events.engine import EventEngine, EventRecord
from app.pipeline.factory import build_ai_components, build_tracker
from app.pipeline.live_view import LiveViewHub
from app.pipeline.processor import FrameProcessor
from app.pipeline.types import AnalysisSink, FrameAnalysis
from app.recognition.sink import RecognitionSink

WARMUP_SECONDS = 5.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile; 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(fraction * len(ordered))))
    return ordered[rank - 1]


class LatencyProbe:
    """Last sink of the pipeline: records frame age and detection time.

    Collects only while `recording` is set, so warm-up frames are not counted.
    """

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.recording = threading.Event()
        self.latency_ms: list[float] = []
        self.detection_ms: list[float] = []
        self.frames: dict[int, int] = {}  # camera_id -> processed frames

    def __call__(self, analysis: FrameAnalysis) -> None:
        if not self.recording.is_set():
            return
        age = (self._clock() - analysis.frame.timestamp).total_seconds() * 1000
        with self._lock:
            self.latency_ms.append(age)
            if analysis.fresh:
                self.detection_ms.append(analysis.detection_ms)
            camera_id = analysis.frame.camera_id
            self.frames[camera_id] = self.frames.get(camera_id, 0) + 1


class EventCounter:
    """Stands in for `EventStore`: counts events instead of writing them."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, _record: EventRecord) -> None:
        self.count += 1


class ResourceMeter:
    """CPU time and memory of this process (CPU % is of one core: 400% = 4 cores busy)."""

    def __init__(self) -> None:
        self._wall = time.monotonic()
        self._cpu = time.process_time()

    def cpu_percent(self) -> float:
        wall = time.monotonic() - self._wall
        return 100.0 * (time.process_time() - self._cpu) / wall if wall > 0 else 0.0

    @staticmethod
    def rss_mb() -> float | None:
        """Resident memory from /proc (Linux); None elsewhere."""
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except (OSError, ValueError, IndexError):
            pass
        return None


@dataclass
class RunResult:
    cameras: int
    seconds: float
    capture_fps: float  # per camera
    processing_fps: float  # per camera
    dropped_percent: float
    latency_p50_ms: float
    latency_p95_ms: float
    detection_p50_ms: float
    detection_p95_ms: float
    cpu_percent: float
    rss_mb: float | None
    events: int


def summarize(
    probe: LatencyProbe,
    published: int,
    *,
    cameras: int,
    seconds: float,
    cpu_percent: float,
    rss_mb: float | None,
    events: int,
) -> RunResult:
    processed = sum(probe.frames.values())
    dropped = max(0, published - processed)
    return RunResult(
        cameras=cameras,
        seconds=seconds,
        capture_fps=published / seconds / cameras,
        processing_fps=processed / seconds / cameras,
        dropped_percent=100.0 * dropped / published if published else 0.0,
        latency_p50_ms=percentile(probe.latency_ms, 0.5),
        latency_p95_ms=percentile(probe.latency_ms, 0.95),
        detection_p50_ms=percentile(probe.detection_ms, 0.5),
        detection_p95_ms=percentile(probe.detection_ms, 0.95),
        cpu_percent=cpu_percent,
        rss_mb=rss_mb,
        events=events,
    )


def _view_live(hub: LiveViewHub, camera_id: int, stop: threading.Event) -> None:
    """One live view client: encodes every new frame like an open MJPEG stream."""
    index = -1
    while not stop.is_set():
        result = hub.wait_jpeg(camera_id, index, timeout=0.5)
        if result is not None:
            index = result[0]


def run(
    settings: Settings, source: str, cameras: int, seconds: float, *, live_view: bool
) -> RunResult:
    ai = build_ai_components(settings)
    if ai.errors or ai.person_detector is None:
        raise SystemExit(f"Cannot load models: {ai.errors or 'person detector disabled'}")
    counter = EventCounter()
    events = EventEngine(
        counter,
        cooldown_seconds=settings.event_cooldown_seconds,
        unknown_after_attempts=settings.unknown_after_attempts,
    )
    sinks: list[AnalysisSink] = [events]
    if ai.recognition is not None:
        sinks.append(
            RecognitionSink(
                ai.recognition,
                interval_seconds=settings.recognition_interval_seconds,
                on_result=events.on_recognition,
            )
        )
    hub = LiveViewHub(settings.live_view_jpeg_quality)
    if live_view:
        sinks.append(hub)
    probe = LatencyProbe()
    sinks.append(probe)

    manager = CameraManager()
    workers: list[CameraWorker] = []
    processors: list[FrameProcessor] = []
    for camera_id in range(1, cameras + 1):
        worker = manager.add(
            CameraConfig(camera_id, f"bench-{camera_id}", source, settings.camera_max_fps, True)
        )
        workers.append(worker)
        processors.append(
            FrameProcessor(
                camera_id,
                worker.buffer,
                detector=ai.person_detector,
                face_detector=ai.face_detector,
                detection_interval=settings.detection_interval,
                sinks=sinks,
                tracker=build_tracker(settings),
                min_person_confidence=settings.person_confidence_threshold,
            )
        )

    stop_viewers = threading.Event()
    viewers = [
        threading.Thread(target=_view_live, args=(hub, cid, stop_viewers), daemon=True)
        for cid in range(1, cameras + 1)
        if live_view
    ]
    for processor in processors:
        processor.start()
    manager.start_all()
    for viewer in viewers:
        viewer.start()
    try:
        time.sleep(WARMUP_SECONDS)
        published_before = sum(w.stats.frames_published for w in workers)
        events_before = counter.count
        meter = ResourceMeter()
        probe.recording.set()
        time.sleep(seconds)
        probe.recording.clear()
        cpu = meter.cpu_percent()
        rss = ResourceMeter.rss_mb()
        published = sum(w.stats.frames_published for w in workers) - published_before
    finally:
        stop_viewers.set()
        for viewer in viewers:
            # A daemon thread still inside cv2.imencode at exit aborts the interpreter.
            viewer.join()
        for processor in processors:
            processor.request_stop()
        manager.stop_all()
        for processor in processors:
            processor.stop()
    return summarize(
        probe,
        published,
        cameras=cameras,
        seconds=seconds,
        cpu_percent=cpu,
        rss_mb=rss,
        events=counter.count - events_before,
    )


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


HEADER = (
    "Cameras",
    "Capture FPS",
    "Processed FPS",
    "Dropped",
    "Latency p50/p95",
    "Detection p50/p95",
    "CPU",
    "RAM",
    "Events",
)


def format_row(result: RunResult) -> tuple[str, ...]:
    return (
        str(result.cameras),
        f"{result.capture_fps:.1f}",
        f"{result.processing_fps:.1f}",
        f"{result.dropped_percent:.0f}%",
        f"{result.latency_p50_ms:.0f} / {result.latency_p95_ms:.0f} ms",
        f"{result.detection_p50_ms:.0f} / {result.detection_p95_ms:.0f} ms",
        f"{result.cpu_percent:.0f}%",
        f"{result.rss_mb:.0f} MB" if result.rss_mb is not None else "n/a",
        str(result.events),
    )


def render(results: list[RunResult], markdown: bool) -> str:
    rows = [HEADER, *(format_row(r) for r in results)]
    if markdown:
        lines = ["| " + " | ".join(row) + " |" for row in rows]
        lines.insert(1, "|" + "---|" * len(HEADER))
        return "\n".join(lines)
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEADER))]
    return "\n".join(
        "  ".join(cell.rjust(w) for cell, w in zip(row, widths, strict=True)) for row in rows
    )


def parse_cameras(value: str) -> list[int]:
    counts = [int(part) for part in value.split(",") if part.strip()]
    if not counts or min(counts) < 1:
        raise argparse.ArgumentTypeError("expected camera counts like 1,2,4")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the KörGöz camera pipeline")
    parser.add_argument("--source", default="data/samples/vtest.avi")
    parser.add_argument("--cameras", type=parse_cameras, default=[1, 2, 4])
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--model", type=Path, help="default: PERSON_DETECTOR_MODEL_PATH")
    parser.add_argument("--interval", type=int, help="default: DETECTION_INTERVAL")
    parser.add_argument("--threads", type=int, help="ONNX threads, default: ONNX_NUM_THREADS")
    parser.add_argument("--live-view", action="store_true", help="one viewer per camera")
    parser.add_argument("--recognition", action="store_true", help="face analysis (Qdrant)")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    update: dict[str, object] = {
        "vision_mode": VisionMode.RECOGNITION if args.recognition else VisionMode.ANONYMOUS
    }
    if args.model is not None:
        update["person_detector_model_path"] = args.model
    if args.interval is not None:
        update["detection_interval"] = args.interval
    if args.threads is not None:
        update["onnx_num_threads"] = args.threads
    settings = get_settings().model_copy(update=update)

    print(f"CPU: {cpu_name()} ({os.cpu_count()} logical cores), Python {platform.python_version()}")
    print(
        f"Source: {args.source} | model: {settings.person_detector_model_path.name} | "
        f"DETECTION_INTERVAL={settings.detection_interval} | "
        f"ONNX threads: {settings.onnx_num_threads or 'auto'} | "
        f"mode: {settings.vision_mode.value} | live view: {'on' if args.live_view else 'off'}"
    )
    results = []
    for count in args.cameras:
        print(f"Running {count} camera(s): {WARMUP_SECONDS:.0f} s warm-up + {args.seconds:.0f} s")
        results.append(run(settings, args.source, count, args.seconds, live_view=args.live_view))
    print(render(results, args.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
