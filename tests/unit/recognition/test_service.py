import numpy as np
import pytest

from app.recognition.detector import FaceDetection
from app.recognition.service import Match, RegistrationError, Unknown
from tests.unit.recognition.fakes import (
    FakeEmbedder,
    InMemoryVectorStore,
    make_face,
    make_service,
    noise_image,
    unit,
)


def test_unknown_when_nobody_is_registered() -> None:
    service = make_service()
    assert service.identify(noise_image(), make_face()) == Unknown(score=0.0)


def test_match_above_threshold() -> None:
    store = InMemoryVectorStore()
    store.add_embedding(7, unit(1, 0, 0), "fake")
    identity = make_service(store=store).identify(noise_image(), make_face())
    assert isinstance(identity, Match)
    assert identity.person_id == 7
    assert identity.score == pytest.approx(1.0)


def test_closest_person_below_threshold_is_unknown_not_forced() -> None:
    store = InMemoryVectorStore()
    store.add_embedding(7, unit(1, 1, 0), "fake")  # cosine with (1,0,0) ~ 0.71
    service = make_service(store=store, threshold=0.8)
    identity = service.identify(noise_image(), make_face())
    assert isinstance(identity, Unknown)
    assert identity.score == pytest.approx(0.707, abs=1e-3)


def test_low_quality_face_is_not_embedded() -> None:
    embedder = FakeEmbedder()
    service = make_service(embedder=embedder)
    assert service.identify(noise_image(), make_face(size=20)) is None
    assert embedder.calls == 0


def test_registration_returns_the_embedding() -> None:
    vector = make_service().registration_embedding(noise_image())
    assert vector.tolist() == pytest.approx([1.0, 0.0, 0.0])


@pytest.mark.parametrize(
    ("faces", "message"),
    [
        ([], "No face"),
        ([make_face(), make_face(x=150)], "found 2"),
        ([make_face(size=60)], "too small"),
        ([make_face(nose_offset=0.9)], "not frontal"),
    ],
)
def test_registration_errors(faces: list[FaceDetection], message: str) -> None:
    with pytest.raises(RegistrationError, match=message):
        make_service(faces=faces).registration_embedding(noise_image())


def test_registration_rejects_blurry_photo() -> None:
    flat = np.full((240, 320, 3), 100, dtype=np.uint8)
    with pytest.raises(RegistrationError, match="blurry"):
        make_service().registration_embedding(flat)
