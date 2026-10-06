"""YOLOX pre/post-processing tested without loading a model."""

from pathlib import Path

import numpy as np
import pytest

from app.detection.person_detector import (
    ModelLoadError,
    YoloxPersonDetector,
    decode_outputs,
    letterbox,
    select_persons,
)

SIZE = (64, 64)  # grid: 8x8 (stride 8) + 4x4 (16) + 2x2 (32) = 84 cells
CELLS = 84


def test_letterbox_keeps_aspect_ratio_and_pads() -> None:
    image = np.full((32, 64, 3), 200, dtype=np.uint8)  # wide image
    tensor, ratio = letterbox(image, SIZE)
    assert tensor.shape == (1, 3, 64, 64)
    assert tensor.dtype == np.float32
    assert ratio == 1.0
    assert tensor[0, 0, 0, 0] == 200  # image area
    assert tensor[0, 0, 63, 0] == 114  # bottom padding


def test_decode_uses_grid_and_stride() -> None:
    raw = np.zeros((CELLS, 85), dtype=np.float32)
    decoded = decode_outputs(raw, SIZE)
    # Cell (x=1, y=0) at stride 8: centre = (1 + 0) * 8, size = exp(0) * 8.
    assert decoded[1, :4].tolist() == [8, 0, 8, 8]
    # First stride-16 cell starts after the 64 stride-8 cells.
    assert decoded[64, 2] == 16


def person_row(cx: float, cy: float, w: float, h: float, score: float) -> list[float]:
    row = [cx, cy, w, h, 1.0, score] + [0.0] * 79
    return row


def test_select_persons_scales_back_and_applies_nms() -> None:
    decoded = np.array(
        [
            person_row(20, 20, 10, 20, 0.9),
            person_row(21, 20, 10, 20, 0.8),  # duplicate of the first -> suppressed
            person_row(50, 50, 8, 8, 0.7),
            person_row(10, 10, 4, 4, 0.2),  # below threshold
        ],
        dtype=np.float32,
    )
    results = select_persons(decoded, ratio=0.5, score_threshold=0.5, nms_threshold=0.45)
    assert [round(r.confidence, 1) for r in results] == [0.9, 0.7]
    first = results[0].bbox
    # Coordinates are divided by the letterbox ratio (0.5) -> doubled.
    assert (first.x1, first.y1, first.x2, first.y2) == (30, 20, 50, 60)


def test_non_person_classes_are_ignored() -> None:
    row = [20, 20, 10, 10, 1.0, 0.0, 0.95] + [0.0] * 78  # class 1 = bicycle
    decoded = np.array([row], dtype=np.float32)
    assert select_persons(decoded, 1.0, 0.5, 0.45) == []


def test_missing_model_file(tmp_path: Path) -> None:
    with pytest.raises(ModelLoadError):
        YoloxPersonDetector(tmp_path / "missing.onnx")
