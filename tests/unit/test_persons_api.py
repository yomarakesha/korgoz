from collections.abc import Iterator
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_recognition_service, get_vector_store
from app.config import get_settings
from app.database.models import FaceEmbedding, Person
from app.database.session import get_db, get_engine
from app.main import create_app
from app.recognition.detector import FaceDetection
from app.recognition.service import FaceRecognitionService
from tests.conftest import ADMIN_PASSWORD, add_user, login
from tests.unit.recognition.fakes import (
    InMemoryVectorStore,
    make_face,
    make_service,
    noise_image,
)


def jpeg() -> bytes:
    ok, buffer = cv2.imencode(".jpg", noise_image(), [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return buffer.tobytes()


class Env:
    def __init__(self, client: TestClient, store: InMemoryVectorStore, engine: Engine) -> None:
        self.client = client
        self.store = store
        self.engine = engine
        self.service: FaceRecognitionService = make_service(store=store)

    def register(self, name: str = "Alice", photo: bytes | None = None, **form: str) -> Any:
        return self.client.post(
            "/persons",
            data={"name": name, **form},
            files={"photo": ("a.jpg", jpeg() if photo is None else photo, "image/jpeg")},
        )

    def count(self, model: Any) -> int:
        with Session(self.engine) as session:
            return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def env(sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv("VISION_MODE", "recognition")
    get_settings.cache_clear()
    store = InMemoryVectorStore()
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    with TestClient(app) as client:
        holder = Env(client, store, sqlite_engine)
        app.dependency_overrides[get_engine] = lambda: sqlite_engine
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_recognition_service] = lambda: holder.service
        app.dependency_overrides[get_vector_store] = lambda: store
        add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
        login(client, "admin", ADMIN_PASSWORD)
        yield holder


def test_register_stores_vector_in_store_and_reference_in_db(env: Env) -> None:
    response = env.register("Alice", external_id="emp-1")
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alice"
    assert body["external_id"] == "emp-1"
    assert body["embeddings"] == 1
    assert "vector" not in str(body).lower()  # vectors never leave the store
    with Session(env.engine) as session:
        row = session.scalars(select(FaceEmbedding)).one()
    assert env.store.points[row.vector_id][0] == body["id"]
    assert row.model_name == "fake-embedder"


@pytest.mark.parametrize(
    ("faces", "message"),
    [
        ([], "No face"),
        ([make_face(), make_face(x=150)], "found 2"),
        ([make_face(size=60)], "too small"),
        ([make_face(nose_offset=0.9)], "not frontal"),
    ],
)
def test_bad_photos_are_rejected(env: Env, faces: list[FaceDetection], message: str) -> None:
    env.service = make_service(store=env.store, faces=faces)
    response = env.register()
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert env.count(Person) == 0
    assert env.store.points == {}


def test_not_an_image(env: Env) -> None:
    response = env.register(photo=b"definitely not a jpeg")
    assert response.status_code == 422
    assert response.json()["detail"] == "File is not an image"


def test_photo_too_large(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACE_UPLOAD_MAX_BYTES", "1024")
    get_settings.cache_clear()
    assert env.register().status_code == 413


def test_duplicate_external_id(env: Env) -> None:
    assert env.register(external_id="emp-1").status_code == 201
    assert env.register("Bob", external_id="emp-1").status_code == 409
    assert len(env.store.points) == 1


def test_qdrant_down_leaves_no_person(env: Env) -> None:
    env.store.down = True
    response = env.register()
    assert response.status_code == 503
    assert env.count(Person) == 0


def test_registration_disabled_in_anonymous_mode(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODE", "anonymous")
    get_settings.cache_clear()
    assert env.register().status_code == 409


def test_list_get_delete(env: Env) -> None:
    alice = env.register("Alice").json()["id"]
    bob = env.register("Bob").json()["id"]
    assert [p["name"] for p in env.client.get("/persons").json()] == ["Alice", "Bob"]
    assert env.client.get(f"/persons/{bob}").json()["name"] == "Bob"

    assert env.client.delete(f"/persons/{alice}").status_code == 204
    assert env.client.get(f"/persons/{alice}").status_code == 404
    assert [pid for pid, _ in env.store.points.values()] == [bob]
    assert env.count(FaceEmbedding) == 1
    assert env.client.delete("/persons/999").status_code == 404


def test_registration_and_deletion_are_audited_by_id_only(env: Env) -> None:
    env.store.down = True
    env.register("Alice")  # failed: no audit entry
    env.store.down = False
    alice = env.register("Alice").json()["id"]
    env.client.delete(f"/persons/{alice}")
    entries = env.client.get("/audit", params={"action": ["PERSON_REGISTERED", "PERSON_DELETED"]})
    assert [(e["action"], e["target_id"]) for e in entries.json()] == [
        ("PERSON_DELETED", alice),
        ("PERSON_REGISTERED", alice),
    ]
    assert "Alice" not in entries.text


def test_delete_keeps_person_when_qdrant_is_down(env: Env) -> None:
    person = env.register().json()["id"]
    env.store.down = True
    assert env.client.delete(f"/persons/{person}").status_code == 503
    assert env.client.get(f"/persons/{person}").status_code == 200


def test_decompression_bomb_is_rejected(env: Env) -> None:
    # ~45 Mpx of zeros compresses to a few hundred KB but would decode to 135 MB.
    ok, bomb = cv2.imencode(".png", np.zeros((9000, 5000), dtype=np.uint8))
    assert ok and len(bomb) < 1_000_000
    response = env.register(photo=bomb.tobytes())
    assert response.status_code == 422
    assert response.json()["detail"] == "Image dimensions are too large"
