"""Detector abstraction.

The rest of the system depends only on `Detector` and `DetectionResult`, never on
a concrete model, so YOLOX can be swapped for another detector without touching
tracking, events or the API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.camera.types import Image

PERSON_CLASS_ID = 0  # COCO "person"


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in pixel coordinates of the original frame."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def clip(self, width: int, height: int) -> "BoundingBox":
        return BoundingBox(
            min(max(self.x1, 0.0), width),
            min(max(self.y1, 0.0), height),
            min(max(self.x2, 0.0), width),
            min(max(self.y2, 0.0), height),
        )

    def iou(self, other: "BoundingBox") -> float:
        inter = BoundingBox(
            max(self.x1, other.x1),
            max(self.y1, other.y1),
            min(self.x2, other.x2),
            min(self.y2, other.y2),
        ).area
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def as_int_tuple(self) -> tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2), int(self.y2)


@dataclass(frozen=True, slots=True)
class DetectionResult:
    bbox: BoundingBox
    confidence: float
    class_id: int = PERSON_CLASS_ID


class Detector(ABC):
    """Finds objects in a single BGR frame."""

    name: str

    @abstractmethod
    def detect(self, image: Image) -> list[DetectionResult]: ...
