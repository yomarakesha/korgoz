"""Draw analysis results on a copy of the frame (for live view only, never stored)."""

import cv2

from app.camera.types import Image
from app.detection.base import BoundingBox
from app.pipeline.types import FrameAnalysis

PERSON_COLOR = (80, 200, 60)  # BGR
FACE_COLOR = (230, 160, 40)
TEXT_COLOR = (255, 255, 255)
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _box(image: Image, bbox: BoundingBox, label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = bbox.as_int_tuple()
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    (text_w, text_h), baseline = cv2.getTextSize(label, _FONT, 0.5, 1)
    top = max(y1 - text_h - baseline - 2, 0)
    cv2.rectangle(image, (x1, top), (x1 + text_w + 4, top + text_h + baseline + 2), color, -1)
    cv2.putText(image, label, (x1 + 2, top + text_h + 1), _FONT, 0.5, TEXT_COLOR, 1, cv2.LINE_AA)


def annotate(analysis: FrameAnalysis) -> Image:
    image = analysis.frame.image.copy()
    if analysis.tracks:
        for track in analysis.tracks:
            _box(image, track.bbox, f"Track #{track.track_id}", PERSON_COLOR)
    else:
        for person in analysis.persons:
            _box(image, person.bbox, f"Person {person.confidence:.2f}", PERSON_COLOR)
    for face in analysis.faces:
        _box(image, face.bbox, f"Face {face.confidence:.2f}", FACE_COLOR)
    visible = len(analysis.tracks) if analysis.tracks else len(analysis.persons)
    header = f"Camera {analysis.frame.camera_id} | persons: {visible}"
    (text_w, text_h), baseline = cv2.getTextSize(header, _FONT, 0.6, 1)
    cv2.rectangle(image, (0, 0), (text_w + 16, text_h + baseline + 12), (30, 30, 30), -1)
    cv2.putText(image, header, (8, text_h + 6), _FONT, 0.6, TEXT_COLOR, 1, cv2.LINE_AA)
    return image
