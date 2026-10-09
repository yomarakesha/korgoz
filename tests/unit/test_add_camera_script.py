from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Camera
from scripts.add_camera import ensure_camera


def test_adds_once_and_audits_without_the_url(db_session: Session) -> None:
    camera, created = ensure_camera(db_session, "Entrance", "rtsp://u:secret@cam/1")
    assert created
    again, created = ensure_camera(db_session, "Entrance", "something else")
    assert not created
    assert again.id == camera.id
    assert db_session.scalars(select(Camera.stream_url)).all() == ["rtsp://u:secret@cam/1"]
    entry = db_session.scalars(select(AuditLog)).one()
    assert (entry.username, entry.target_id) == ("(cli)", camera.id)
    assert "secret" not in str(entry.details)
