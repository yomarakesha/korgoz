"""YOLOX person detector on ONNX Runtime (CPU by default).

Model: official YOLOX ONNX exports (Apache-2.0), e.g. `yolox_s.onnx` (640x640)
or `yolox_tiny.onnx` (416x416). The input size is read from the model file.
The exported graph returns raw grid offsets, decoded here (`decode_outputs`).
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from app.camera.types import Image
from app.detection.base import PERSON_CLASS_ID, BoundingBox, DetectionResult, Detector

logger = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float32]

_STRIDES = (8, 16, 32)
_PAD_VALUE = 114


class ModelLoadError(Exception):
    """The model file is missing or cannot be loaded."""


def letterbox(image: Image, size: tuple[int, int]) -> tuple[FloatArray, float]:
    """Resize keeping aspect ratio, pad bottom/right; return NCHW float32 tensor and scale."""
    target_h, target_w = size
    ratio = min(target_h / image.shape[0], target_w / image.shape[1])
    new_w, new_h = int(image.shape[1] * ratio), int(image.shape[0] * ratio)
    padded = np.full((target_h, target_w, 3), _PAD_VALUE, dtype=np.uint8)
    padded[:new_h, :new_w] = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    # YOLOX >= 0.1.1 expects BGR 0..255 without mean/std normalization.
    tensor = padded.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    return np.ascontiguousarray(tensor), ratio


def decode_outputs(raw: FloatArray, size: tuple[int, int]) -> FloatArray:
    """Turn per-cell offsets (N, 85) into absolute cx, cy, w, h in input pixels."""
    grids, strides = [], []
    for stride in _STRIDES:
        h, w = size[0] // stride, size[1] // stride
        xv, yv = np.meshgrid(np.arange(w), np.arange(h))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((h * w, 1), stride))
    grid = np.concatenate(grids).astype(np.float32)
    stride_arr = np.concatenate(strides).astype(np.float32)

    decoded = raw.copy()
    decoded[:, :2] = (raw[:, :2] + grid) * stride_arr
    decoded[:, 2:4] = np.exp(raw[:, 2:4]) * stride_arr
    return decoded


def select_persons(
    decoded: FloatArray,
    ratio: float,
    score_threshold: float,
    nms_threshold: float,
) -> list[DetectionResult]:
    """Filter person boxes by score, map back to the original frame, apply NMS."""
    scores = decoded[:, 4] * decoded[:, 5 + PERSON_CLASS_ID]  # objectness * class prob
    keep = scores >= score_threshold
    if not np.any(keep):
        return []
    boxes, scores = decoded[keep, :4] / ratio, scores[keep]

    # NMSBoxes takes (x, y, w, h).
    xywh = np.column_stack(
        (boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2, boxes[:, 2:4])
    )
    indices = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), score_threshold, nms_threshold)

    results = []
    for i in np.asarray(indices).reshape(-1):
        x, y, w, h = xywh[i]
        results.append(
            DetectionResult(
                bbox=BoundingBox(float(x), float(y), float(x + w), float(y + h)),
                confidence=float(scores[i]),
                class_id=PERSON_CLASS_ID,
            )
        )
    return results


class YoloxPersonDetector(Detector):
    def __init__(
        self,
        model_path: Path,
        *,
        score_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        num_threads: int = 0,
    ) -> None:
        if not model_path.is_file():
            raise ModelLoadError(f"Person detector model not found: {model_path}")
        options = ort.SessionOptions()
        if num_threads > 0:
            options.intra_op_num_threads = num_threads
        try:
            self._session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            raise ModelLoadError(f"Cannot load {model_path.name}: {exc}") from exc

        model_input = self._session.get_inputs()[0]
        self._input_name = model_input.name
        self._input_size: tuple[int, int] = (int(model_input.shape[2]), int(model_input.shape[3]))
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        self.name = f"yolox:{model_path.stem}"
        logger.info("Loaded %s, input %dx%d", self.name, *self._input_size)

    @property
    def input_size(self) -> tuple[int, int]:
        return self._input_size

    def detect(self, image: Image) -> list[DetectionResult]:
        tensor, ratio = letterbox(image, self._input_size)
        raw = self._session.run(None, {self._input_name: tensor})[0][0]
        decoded = decode_outputs(np.asarray(raw, dtype=np.float32), self._input_size)
        height, width = image.shape[:2]
        return [
            DetectionResult(r.bbox.clip(width, height), r.confidence, r.class_id)
            for r in select_persons(decoded, ratio, self._score_threshold, self._nms_threshold)
        ]
