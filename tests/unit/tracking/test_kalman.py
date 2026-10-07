import pytest

from app.detection.base import BoundingBox
from app.tracking.kalman import KalmanBoxFilter, box_to_xyah, xyah_to_box


def test_xyah_roundtrip() -> None:
    box = BoundingBox(10, 20, 50, 100)
    back = xyah_to_box(box_to_xyah(box))
    assert (back.x1, back.y1, back.x2, back.y2) == pytest.approx((10, 20, 50, 100))


def test_learns_constant_velocity() -> None:
    kalman = KalmanBoxFilter(BoundingBox(0, 0, 20, 60))
    for step in range(1, 15):
        kalman.predict()
        kalman.update(BoundingBox(5 * step, 0, 5 * step + 20, 60))  # 5 px/frame to the right
    before = kalman.box.center[0]
    kalman.predict()
    assert kalman.box.center[0] - before == pytest.approx(5, abs=0.5)
    assert kalman.box.height == pytest.approx(60, abs=1)
