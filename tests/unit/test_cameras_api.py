from typing import Any

from sqlalchemy import Engine, create_engine

from app.camera.status_store import DatabaseStatusRecorder
from app.camera.types import CameraStatus

RTSP = "rtsp://admin:topsecret@192.168.1.10:554/stream1"


def test_create_and_get_camera_masks_credentials(api_client: Any) -> None:
    response = api_client.post("/cameras", json={"name": "Entrance", "stream_url": RTSP})
    assert response.status_code == 201
    body = response.json()
    assert "topsecret" not in response.text
    assert "stream_url" not in body
    assert body["stream_url_masked"] == "rtsp://***:***@192.168.1.10:554/stream1"
    assert body["source_kind"] == "network"
    assert body["status"] == "unknown"

    fetched = api_client.get(f"/cameras/{body['id']}")
    assert fetched.status_code == 200
    assert "topsecret" not in fetched.text

    listing = api_client.get("/cameras")
    assert [c["id"] for c in listing.json()] == [body["id"]]
    assert "topsecret" not in listing.text


def test_usb_camera(api_client: Any) -> None:
    body = api_client.post("/cameras", json={"name": "Webcam", "stream_url": "0"}).json()
    assert body["source_kind"] == "usb"
    assert body["stream_url_masked"] == "0"


def test_delete_camera(api_client: Any) -> None:
    camera_id = api_client.post("/cameras", json={"name": "c", "stream_url": "0"}).json()["id"]
    assert api_client.delete(f"/cameras/{camera_id}").status_code == 204
    assert api_client.get(f"/cameras/{camera_id}").status_code == 404
    assert api_client.delete(f"/cameras/{camera_id}").status_code == 404


def test_validation_errors(api_client: Any) -> None:
    assert api_client.post("/cameras", json={"name": "", "stream_url": "0"}).status_code == 422
    assert api_client.post("/cameras", json={"name": "x"}).status_code == 422
    unknown_location = {"name": "x", "stream_url": "0", "location_id": 999}
    assert api_client.post("/cameras", json=unknown_location).status_code == 422


def test_worker_status_reaches_api_and_health(api_client: Any, sqlite_engine: Engine) -> None:
    camera_id = api_client.post("/cameras", json={"name": "c", "stream_url": "0"}).json()["id"]
    recorder = DatabaseStatusRecorder(sqlite_engine)

    recorder(camera_id, CameraStatus.ONLINE)
    assert api_client.get(f"/cameras/{camera_id}").json()["status"] == "online"
    assert api_client.get("/health").json()["cameras"] == 1

    recorder(camera_id, CameraStatus.OFFLINE)
    assert api_client.get("/health").json()["cameras"] == 0


def test_status_recorder_ignores_unknown_camera_and_db_errors(sqlite_engine: Engine) -> None:
    DatabaseStatusRecorder(sqlite_engine)(12345, CameraStatus.ONLINE)  # no row: no error
    broken = create_engine("postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    DatabaseStatusRecorder(broken)(1, CameraStatus.ONLINE)  # unreachable DB: no error


def test_database_outage_returns_503(api_client: Any) -> None:
    from app.database.session import get_db

    broken = create_engine("postgresql+psycopg://nobody:secret-pw@127.0.0.1:1/none")

    def _broken_db() -> Any:
        from sqlalchemy.orm import Session

        with Session(broken) as session:
            yield session

    api_client.app.dependency_overrides[get_db] = _broken_db
    response = api_client.get("/cameras")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "secret-pw" not in response.text
