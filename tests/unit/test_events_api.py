from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.database.models import Camera, Event, Location, Person, Track, TrackSession
from app.events.types import EventType as E
from app.ontology.relations import Ontology

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def seed(engine: Engine) -> None:
    """Alice (person 1) visits camera 1 on track 1; an unknown visitor uses track 2."""
    with Session(engine) as session:
        session.add_all(
            [
                Location(id=1, name="Hall"),
                Camera(id=1, name="entrance", stream_url="0", location_id=1),
                Camera(id=2, name="yard", stream_url="1"),
                Person(id=1, name="Alice"),
                Person(id=2, name="Bob"),
            ]
        )
        session.flush()  # tracks have no ORM relationship to cameras: insert parents first
        session.add_all(
            [
                Track(
                    id=1, camera_id=1, track_identifier="1", started_at=at(0), last_seen_at=at(5)
                ),
                Track(
                    id=2, camera_id=2, track_identifier="1", started_at=at(1), last_seen_at=at(2)
                ),
                TrackSession(id=1, track_id=1, camera_id=1, started_at=at(0), ended_at=at(5)),
            ]
        )
        session.flush()
        rows = [
            (E.CAMERA_ONLINE, 1, None, None, -1),
            (E.PERSON_ENTERED, 1, 1, None, 0),  # id 2: before recognition, no person yet
            (E.PERSON_RECOGNIZED, 1, 1, 1, 0.5),  # id 3
            (E.PERSON_ENTERED, 2, 2, None, 1),  # id 4
            (E.PERSON_UNKNOWN, 2, 2, None, 1.5),  # id 5
            (E.PERSON_LEFT, 1, 1, 1, 5),  # id 6
        ]
        for event_type, camera, track, person, minutes in rows:
            session.add(
                Event(
                    event_type=event_type,
                    camera_id=camera,
                    location_id=1 if camera == 1 else None,
                    track_id=track,
                    person_id=person,
                    timestamp=at(minutes),
                    confidence=0.9 if event_type is E.PERSON_RECOGNIZED else None,
                    metadata_={},
                )
            )
        session.commit()


def ids(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [e["id"] for e in response.json()]


def test_events_newest_first(api_client: Any, sqlite_engine: Engine) -> None:
    seed(sqlite_engine)
    body = api_client.get("/events").json()
    assert [e["id"] for e in body] == [6, 5, 4, 3, 2, 1]
    assert body[3] == {
        "id": 3,
        "event_type": "PERSON_RECOGNIZED",
        "timestamp": body[3]["timestamp"],
        "camera_id": 1,
        "location_id": 1,
        "person_id": 1,
        "track_id": 1,
        "confidence": 0.9,
        "metadata": {},
    }


def test_event_filters(api_client: Any, sqlite_engine: Engine) -> None:
    seed(sqlite_engine)
    assert ids(api_client.get("/events?camera_id=2")) == [5, 4]
    assert ids(api_client.get("/events?location_id=1")) == [6, 3, 2, 1]
    assert ids(api_client.get("/events?person_id=1")) == [6, 3]
    assert ids(api_client.get("/events?track_id=2")) == [5, 4]
    assert ids(api_client.get("/events?event_type=PERSON_ENTERED&event_type=PERSON_LEFT")) == [
        6,
        4,
        2,
    ]
    since = at(1).isoformat().replace("+00:00", "Z")
    until = at(5).isoformat().replace("+00:00", "Z")
    assert ids(api_client.get(f"/events?since={since}&until={until}")) == [5, 4]
    assert ids(api_client.get("/events?limit=2&offset=1")) == [5, 4]
    assert api_client.get("/events?event_type=NOPE").status_code == 422


def test_get_event(api_client: Any, sqlite_engine: Engine) -> None:
    seed(sqlite_engine)
    assert api_client.get("/events/5").json()["event_type"] == "PERSON_UNKNOWN"
    assert api_client.get("/events/99").status_code == 404


def test_person_timeline_includes_the_whole_visit(api_client: Any, sqlite_engine: Engine) -> None:
    seed(sqlite_engine)
    body = api_client.get("/persons/1/timeline").json()
    # PERSON_ENTERED (id 2) has no person_id, but belongs to the track Alice was recognised on.
    assert [e["event_id"] for e in body] == [6, 3, 2]
    assert body[1]["camera"] == {"id": 1, "name": "entrance"}
    assert body[1]["location"] == {"id": 1, "name": "Hall"}
    assert body[1]["event_type"] == "PERSON_RECOGNIZED"


def test_timeline_of_person_never_seen_and_missing_person(
    api_client: Any, sqlite_engine: Engine
) -> None:
    seed(sqlite_engine)
    assert api_client.get("/persons/2/timeline").json() == []
    assert api_client.get("/persons/99/timeline").status_code == 404


def test_ontology_relations(sqlite_engine: Engine) -> None:
    seed(sqlite_engine)
    with Session(sqlite_engine) as session:
        ontology = Ontology(session)
        assert [t.id for t in ontology.tracks_of_person(1)] == [1]
        assert [e.id for e in ontology.events_in_session(1)] == [2, 3, 6]
        event = ontology.events_of_person(1)[0]
        assert ontology.camera_of(event).name == "entrance"
        location = ontology.location_of(event)
        assert location is not None and location.name == "Hall"
        assert ontology.events_in_session(99) == []
