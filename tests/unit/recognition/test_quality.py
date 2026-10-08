import numpy as np
import pytest

from app.camera.types import Image
from app.recognition.detector import FaceDetection
from app.recognition.quality import (
    FaceQualityChecker,
    QualityIssue,
    QualityThresholds,
    estimate_yaw,
)
from tests.unit.recognition.fakes import make_face, noise_image

CHECKER = FaceQualityChecker(QualityThresholds(min_size=40, min_sharpness=30.0, max_yaw=0.5))


def test_yaw_is_zero_for_a_frontal_face_and_grows_with_turn() -> None:
    assert estimate_yaw(make_face()) == pytest.approx(0.0)
    assert estimate_yaw(make_face(nose_offset=0.3)) == pytest.approx(0.3)
    assert estimate_yaw(make_face(nose_offset=-2.0)) == 1.0  # clipped


def test_good_face_passes() -> None:
    report = CHECKER.check(noise_image(), make_face())
    assert report.ok
    assert report.size == 100


@pytest.mark.parametrize(
    ("face", "image", "issue"),
    [
        (make_face(size=30), noise_image(), QualityIssue.TOO_SMALL),
        (make_face(), np.full((240, 320, 3), 128, dtype=np.uint8), QualityIssue.BLURRY),
        (make_face(nose_offset=0.8), noise_image(), QualityIssue.NOT_FRONTAL),
    ],
)
def test_bad_faces_are_rejected(face: FaceDetection, image: Image, issue: QualityIssue) -> None:
    report = CHECKER.check(image, face)
    assert not report.ok
    assert report.issue is issue


def test_face_outside_the_image_is_blurry_not_a_crash() -> None:
    report = CHECKER.check(noise_image(50, 50), make_face(x=100, y=100))
    assert report.sharpness == 0.0
