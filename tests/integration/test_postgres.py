"""Runs migrations against a real PostgreSQL (see conftest.py for TEST_DATABASE_URL)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Camera, Event, User
from app.events.types import EventType
from app.security import audit
from app.security.sessions import create_session, resolve_session
from app.security.types import AuditAction

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
        "users",
        "auth_sessions",
        "audit_log",
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


def test_sessions_and_audit_on_postgres(migrated_url: str) -> None:
    now = datetime.now(UTC)
    with Session(create_engine(migrated_url)) as db:
        user = User(username="admin", password_hash="x")
        db.add(user)
        db.flush()
        token = create_session(db, user, timedelta(hours=1), now)
        audit.record(db, AuditAction.LOGIN, user=user, ip_address="127.0.0.1")
        db.commit()
        assert resolve_session(db, token, now + timedelta(minutes=59)) == user
        assert resolve_session(db, token, now + timedelta(hours=1)) is None
        db.delete(user)
        db.commit()
        entry = db.scalars(select(AuditLog)).one()
        assert (entry.user_id, entry.username) == (None, "admin")  # history survives
