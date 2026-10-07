"""Constant-velocity Kalman filter for bounding boxes (as in SORT / ByteTrack).

State: [cx, cy, a, h, vcx, vcy, va, vh] where (cx, cy) is the box centre,
a = width / height and h the height. Noise scales with box height, so large
(near) and small (far) people are tracked equally well.
"""

import numpy as np
import numpy.typing as npt

from app.detection.base import BoundingBox

Vector = npt.NDArray[np.float64]
Matrix = npt.NDArray[np.float64]

_STD_POSITION = 1.0 / 20
_STD_VELOCITY = 1.0 / 160


def box_to_xyah(box: BoundingBox) -> Vector:
    cx, cy = box.center
    height = max(box.height, 1e-6)
    return np.array([cx, cy, box.width / height, height], dtype=np.float64)


def xyah_to_box(xyah: Vector) -> BoundingBox:
    cx, cy, aspect, height = (float(v) for v in xyah[:4])
    width = aspect * height
    return BoundingBox(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


class KalmanBoxFilter:
    _motion = np.eye(8)
    _motion[:4, 4:] = np.eye(4)  # position += velocity (one step = one frame)
    _observation = np.eye(4, 8)

    def __init__(self, box: BoundingBox) -> None:
        measurement = box_to_xyah(box)
        self.mean: Vector = np.concatenate([measurement, np.zeros(4)])
        h = measurement[3]
        std = [
            2 * _STD_POSITION * h,
            2 * _STD_POSITION * h,
            1e-2,
            2 * _STD_POSITION * h,
            10 * _STD_VELOCITY * h,
            10 * _STD_VELOCITY * h,
            1e-5,
            10 * _STD_VELOCITY * h,
        ]
        self.covariance: Matrix = np.diag(np.square(std))

    @property
    def box(self) -> BoundingBox:
        return xyah_to_box(self.mean)

    def predict(self) -> None:
        h = self.mean[3]
        std = [
            _STD_POSITION * h,
            _STD_POSITION * h,
            1e-2,
            _STD_POSITION * h,
            _STD_VELOCITY * h,
            _STD_VELOCITY * h,
            1e-5,
            _STD_VELOCITY * h,
        ]
        self.mean = self._motion @ self.mean
        self.covariance = self._motion @ self.covariance @ self._motion.T + np.diag(np.square(std))
        self.mean[3] = max(self.mean[3], 1e-3)  # height must stay positive

    def update(self, box: BoundingBox) -> None:
        h = self.mean[3]
        noise = np.diag(np.square([_STD_POSITION * h, _STD_POSITION * h, 1e-1, _STD_POSITION * h]))
        projected_cov = self._observation @ self.covariance @ self._observation.T + noise
        gain = self.covariance @ self._observation.T @ np.linalg.inv(projected_cov)
        innovation = box_to_xyah(box) - self._observation @ self.mean
        self.mean = self.mean + gain @ innovation
        self.covariance = self.covariance - gain @ projected_cov @ gain.T
