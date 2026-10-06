import pytest

from app.detection.base import BoundingBox


def test_geometry() -> None:
    box = BoundingBox(10, 20, 50, 100)
    assert (box.width, box.height, box.area) == (40, 80, 3200)
    assert box.center == (30, 60)
    assert box.as_int_tuple() == (10, 20, 50, 100)


def test_degenerate_box_has_zero_area() -> None:
    assert BoundingBox(50, 50, 10, 10).area == 0


def test_clip() -> None:
    assert BoundingBox(-5, -5, 700, 500).clip(640, 480) == BoundingBox(0, 0, 640, 480)


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (BoundingBox(0, 0, 10, 10), 1.0),
        (BoundingBox(5, 0, 15, 10), 50 / 150),
        (BoundingBox(20, 20, 30, 30), 0.0),
    ],
)
def test_iou(other: BoundingBox, expected: float) -> None:
    assert BoundingBox(0, 0, 10, 10).iou(other) == pytest.approx(expected)
