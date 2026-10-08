"""Runs migrations against a real PostgreSQL (see conftest.py for TEST_DATABASE_URL)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database.models import Camera, Event
from app.events.types import EventType

pytestmark = pytest.mark.integration


def test_migrations_create_all_tables(migrated_url: str) -> None:
    tables = set(inspect(create_engine(migrated_url)).get_table_names())
    assert {
        "persons",
        "face_embeddings",
        "cameras",
        "locations",
        "tracks",
        "events",
        "sessions",
    } <= tables


def test_event_jsonb_roundtrip(migrated_url: str) -> None:
    with Session(create_engine(migrated_url)) as db:
        camera = Camera(name="Cam", stream_url="0")
        db.add(camera)
        db.flush()
        db.add(
            Event(
                event_type=EventType.CAMERA_ONLINE,
                camera_id=camera.id,
                timestamp=datetime.now(UTC),
                metadata_={"fps": 15},
            )
        )
        db.commit()
        event = db.scalars(select(Event)).one()
        assert event.metadata_ == {"fps": 15}
        assert event.timestamp.tzinfo is not None
