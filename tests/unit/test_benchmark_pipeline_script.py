from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.camera.types import Frame
from app.pipeline.types import FrameAnalysis
from scripts.benchmark_pipeline import (
    LatencyProbe,
    ResourceMeter,
    parse_cameras,
    percentile,
    render,
    summarize,
)

CAPTURED = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _analysis(camera_id: int, *, fresh: bool, detection_ms: float = 0.0) -> FrameAnalysis:
    frame = Frame(camera_id, 0, CAPTURED, np.zeros((2, 2, 3), dtype=np.uint8))
    return FrameAnalysis(frame=frame, fresh=fresh, detection_ms=detection_ms)


def test_percentile_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.5) == 50.0
    assert percentile(values, 0.95) == 95.0
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.5) == 0.0


def test_probe_records_only_while_recording() -> None:
    probe = LatencyProbe(clock=lambda: CAPTURED + timedelta(milliseconds=40))
    probe(_analysis(1, fresh=True, detection_ms=30.0))  # warm-up: ignored
    probe.recording.set()
    probe(_analysis(1, fresh=True, detection_ms=30.0))
    probe(_analysis(1, fresh=False))
    probe(_analysis(2, fresh=False))
    assert probe.latency_ms == [40.0, 40.0, 40.0]
    assert probe.detection_ms == [30.0]  # reused detections are not timed
    assert probe.frames == {1: 2, 2: 1}


def test_summarize_counts_dropped_frames_per_camera() -> None:
    probe = LatencyProbe(clock=lambda: CAPTURED + timedelta(milliseconds=100))
    probe.recording.set()
    for _ in range(15):
        probe(_analysis(1, fresh=True, detection_ms=50.0))
    result = summarize(probe, 20, cameras=2, seconds=1.0, cpu_percent=250.0, rss_mb=None, events=3)
    assert result.capture_fps == 10.0
    assert result.processing_fps == 7.5
    assert result.dropped_percent == 25.0
    assert (result.latency_p50_ms, result.detection_p95_ms) == (100.0, 50.0)


def test_render_markdown_and_plain() -> None:
    probe = LatencyProbe()
    result = summarize(probe, 0, cameras=1, seconds=1.0, cpu_percent=0.0, rss_mb=None, events=0)
    markdown = render([result], markdown=True).splitlines()
    assert markdown[0].startswith("| Cameras |")
    assert markdown[1] == "|" + "---|" * 9
    assert "n/a" in markdown[2]
    assert render([result], markdown=False).splitlines()[1].split()[0] == "1"


def test_parse_cameras() -> None:
    assert parse_cameras("1,2,4") == [1, 2, 4]
    with pytest.raises(Exception, match="camera counts"):
        parse_cameras("0")


def test_resource_meter() -> None:
    meter = ResourceMeter()
    sum(range(100_000))
    assert meter.cpu_percent() >= 0.0
    rss = ResourceMeter.rss_mb()
    assert rss is None or rss > 0
