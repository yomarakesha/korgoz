from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Camera,
    CameraStatus,
    Event,
    FaceEmbedding,
    Location,
    Person,
    PersonStatus,
    Track,
    TrackSession,
)
from app.events.types import EventType


def _camera(db: Session) -> Camera:
    location = Location(name="Entrance")
    camera = Camera(name="Cam 01", stream_url="rtsp://admin:secret@10.0.0.5/s1", location=location)
    db.add(camera)
    db.commit()
    return camera


def test_person_defaults(db_session: Session) -> None:
    person = Person(name="Alice", external_id="EMP-1")
    db_session.add(person)
    db_session.commit()
    assert person.id is not None
    assert person.status is PersonStatus.ACTIVE
    assert person.created_at is not None


def test_camera_repr_hides_stream_url(db_session: Session) -> None:
    camera = _camera(db_session)
    assert camera.status is CameraStatus.UNKNOWN
    assert camera.enabled is True
    assert "secret" not in repr(camera)


def test_deleting_person_removes_embeddings_and_detaches_events(db_session: Session) -> None:
    camera = _camera(db_session)
    person = Person(name="Bob")
    person.embeddings.append(FaceEmbedding(vector_id="vec-1", model_name="test-model"))
    db_session.add(person)
    db_session.flush()
    db_session.add(
        Event(
            event_type=EventType.PERSON_RECOGNIZED,
            person_id=person.id,
            camera_id=camera.id,
            location_id=camera.location_id,
            timestamp=datetime.now(UTC),
            confidence=0.91,
        )
    )
    db_session.commit()

    db_session.delete(person)
    db_session.commit()
    db_session.expire_all()

    assert db_session.scalars(select(FaceEmbedding)).all() == []
    event = db_session.scalars(select(Event)).one()
    assert event.person_id is None


def test_event_metadata_and_type_roundtrip(db_session: Session) -> None:
    camera = _camera(db_session)
    now = datetime.now(UTC)
    track = Track(camera_id=camera.id, track_identifier="42", started_at=now, last_seen_at=now)
    db_session.add(track)
    db_session.flush()
    db_session.add(TrackSession(track_id=track.id, camera_id=camera.id, started_at=now))
    db_session.add(
        Event(
            event_type=EventType.TRACK_STARTED,
            track_id=track.id,
            camera_id=camera.id,
            timestamp=now,
            metadata_={"bbox": [1, 2, 3, 4]},
        )
    )
    db_session.commit()
    db_session.expire_all()

    event = db_session.scalars(select(Event)).one()
    assert event.event_type is EventType.TRACK_STARTED
    assert event.metadata_ == {"bbox": [1, 2, 3, 4]}
    assert db_session.scalars(select(TrackSession)).one().ended_at is None
