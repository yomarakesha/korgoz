import pytest

from app.camera.buffer import FrameBuffer
from app.pipeline.processor import FrameProcessor
from app.pipeline.types import FrameAnalysis

from ..camera.helpers import wait_until
from .fakes import CountingDetector, make_frame


def test_detection_runs_every_nth_frame_and_is_reused_between() -> None:
    detector = CountingDetector()
    processor = FrameProcessor(1, FrameBuffer(), detector=detector, detection_interval=3)
    analyses = [processor.process(make_frame(i)) for i in range(7)]
    assert detector.calls == 3  # frames 0, 3, 6
    assert [a.fresh for a in analyses] == [True, False, False, True, False, False, True]
    assert analyses[1].persons == analyses[0].persons
    assert analyses[3].persons != analyses[0].persons
    assert processor.stats.detections_run == 3


def test_detector_failure_keeps_previous_detections() -> None:
    processor = FrameProcessor(
        1, FrameBuffer(), detector=CountingDetector(fail_on_call=2), detection_interval=1
    )
    first = processor.process(make_frame(0))
    second = processor.process(make_frame(1))
    assert second.persons == first.persons
    assert processor.stats.detection_errors == 1


def test_failing_sink_does_not_block_other_sinks() -> None:
    received: list[FrameAnalysis] = []

    def broken(_analysis: FrameAnalysis) -> None:
        raise RuntimeError("sink bug")

    processor = FrameProcessor(
        1, FrameBuffer(), detector=CountingDetector(), sinks=[broken, received.append]
    )
    processor.process(make_frame(0))
    assert len(received) == 1


def test_works_without_detector() -> None:
    analysis = FrameProcessor(1, FrameBuffer(), detector=None).process(make_frame(0))
    assert analysis.persons == [] and analysis.faces == []


def test_invalid_interval() -> None:
    with pytest.raises(ValueError):
        FrameProcessor(1, FrameBuffer(), detector=None, detection_interval=0)


def test_thread_consumes_frames_from_buffer() -> None:
    buffer = FrameBuffer()
    received: list[FrameAnalysis] = []
    processor = FrameProcessor(1, buffer, detector=CountingDetector(), sinks=[received.append])
    processor.start()
    try:
        for i in range(3):
            buffer.put(make_frame(i))
            assert wait_until(lambda i=i: len(received) == i + 1)  # type: ignore[misc]
    finally:
        processor.stop()
    assert [a.frame.index for a in received] == [0, 1, 2]
    assert not processor.is_alive
