"""Runs migrations against a real PostgreSQL.

Set TEST_DATABASE_URL to an EMPTY, disposable database, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://korgoz:pw@localhost:5432/korgoz_test
The schema is dropped at the end of the test.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database.models import Camera, Event
from app.events.types import EventType

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def migrated_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except Exception:
        pytest.skip("PostgreSQL at TEST_DATABASE_URL is unreachable")

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    yield TEST_DATABASE_URL
    command.downgrade(config, "base")
    engine.dispose()


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
