from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.database.models import Track

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def seed(api_client: Any, engine: Engine) -> None:
    for name in ("a", "b"):
        api_client.post("/cameras", json={"name": name, "stream_url": "0"})
    with Session(engine) as session:
        session.add_all(
            [
                Track(
                    camera_id=1,
                    track_identifier="1",
                    started_at=T0,
                    last_seen_at=T0 + timedelta(seconds=40),
                    ended_at=T0 + timedelta(seconds=42),
                ),
                Track(
                    camera_id=1,
                    track_identifier="2",
                    started_at=T0 + timedelta(minutes=5),
                    last_seen_at=T0 + timedelta(minutes=6),
                ),
                Track(
                    camera_id=2,
                    track_identifier="1",
                    started_at=T0 + timedelta(minutes=10),
                    last_seen_at=T0 + timedelta(minutes=10),
                ),
            ]
        )
        session.commit()


def test_list_newest_first_with_duration(api_client: Any, sqlite_engine: Engine) -> None:
    seed(api_client, sqlite_engine)
    body = api_client.get("/tracks").json()
    assert [t["id"] for t in body] == [3, 2, 1]
    finished = body[2]
    assert finished["active"] is False
    assert finished["duration_seconds"] == 42
    assert body[1]["active"] is True
    assert body[1]["duration_seconds"] == 60  # still open: measured to last_seen


def test_filters(api_client: Any, sqlite_engine: Engine) -> None:
    seed(api_client, sqlite_engine)
    assert [t["id"] for t in api_client.get("/tracks?camera_id=1").json()] == [2, 1]
    assert [t["id"] for t in api_client.get("/tracks?active=false").json()] == [1]
    since = (T0 + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    assert [t["id"] for t in api_client.get(f"/tracks?since={since}").json()] == [3, 2]
    assert len(api_client.get("/tracks?limit=1").json()) == 1
    assert api_client.get("/tracks?limit=0").status_code == 422


def test_get_track(api_client: Any, sqlite_engine: Engine) -> None:
    seed(api_client, sqlite_engine)
    assert api_client.get("/tracks/2").json()["track_identifier"] == "2"
    assert api_client.get("/tracks/99").status_code == 404
