"""Draw analysis results on a copy of the frame (for live view only, never stored)."""

import cv2

from app.camera.types import Image
from app.detection.base import BoundingBox
from app.pipeline.types import FrameAnalysis

PERSON_COLOR = (80, 200, 60)  # BGR
FACE_COLOR = (230, 160, 40)
TEXT_COLOR = (255, 255, 255)
# OpenCV 5 built-in Unicode font: Hershey fonts render Cyrillic names as "???".
_FONT = cv2.FontFace("sans")
_LABEL_SIZE = 15
_HEADER_SIZE = 18


def _text_box(text: str, size: int) -> tuple[int, int, int]:
    """(width, ascent, height) of `text` in pixels; the baseline is `ascent` below the top."""
    _x, y, width, height = cv2.getTextSize((0, 0), text, (0, 0), _FONT, size)
    return width, -y, height


def _box(image: Image, bbox: BoundingBox, label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = bbox.as_int_tuple()
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    text_w, ascent, text_h = _text_box(label, _LABEL_SIZE)
    top = max(y1 - text_h - 2, 0)
    cv2.rectangle(image, (x1, top), (x1 + text_w + 4, top + text_h + 2), color, -1)
    cv2.putText(image, label, (x1 + 2, top + ascent + 1), TEXT_COLOR, _FONT, _LABEL_SIZE)


def annotate(analysis: FrameAnalysis, labels: dict[int, str] | None = None) -> Image:
    """`labels`: track_id -> text from recognition ("Name 0.87"); default "Track #N"."""
    image = analysis.frame.image.copy()
    labels = labels or {}
    if analysis.tracks:
        for track in analysis.tracks:
            label = labels.get(track.track_id, f"Track #{track.track_id}")
            _box(image, track.bbox, label, PERSON_COLOR)
    else:
        for person in analysis.persons:
            _box(image, person.bbox, f"Person {person.confidence:.2f}", PERSON_COLOR)
    for face in analysis.faces:
        _box(image, face.bbox, f"Face {face.confidence:.2f}", FACE_COLOR)
    visible = len(analysis.tracks) if analysis.tracks else len(analysis.persons)
    header = f"Camera {analysis.frame.camera_id} | persons: {visible}"
    text_w, ascent, text_h = _text_box(header, _HEADER_SIZE)
    cv2.rectangle(image, (0, 0), (text_w + 16, text_h + 12), (30, 30, 30), -1)
    cv2.putText(image, header, (8, ascent + 6), TEXT_COLOR, _FONT, _HEADER_SIZE)
    return image
