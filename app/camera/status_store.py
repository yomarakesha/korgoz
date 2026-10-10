"""Persists camera status changes so the API (a separate process) can see them."""

import logging
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, update
from sqlalchemy.orm import Session

from app.camera.types import CameraStatus
from app.database.models import Camera

logger = logging.getLogger(__name__)


def effective_status(
    status: CameraStatus, last_seen_at: datetime | None, now: datetime, stale_after_seconds: float
) -> CameraStatus:
    """ONLINE only while the worker keeps the heartbeat fresh.

    A worker killed with `kill -9` (or a power cut) never writes OFFLINE; without
    this check such a camera would stay "online" forever.
    """
    if status is not CameraStatus.ONLINE:
        return status
    if last_seen_at is None:
        return CameraStatus.OFFLINE
    if last_seen_at.tzinfo is None:  # SQLite returns naive UTC
        last_seen_at = last_seen_at.replace(tzinfo=UTC)
    if now - last_seen_at > timedelta(seconds=stale_after_seconds):
        return CameraStatus.OFFLINE
    return status


class DatabaseStatusRecorder:
    """`StatusListener` that writes `cameras.status` and the heartbeat; never raises."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __call__(self, camera_id: int, status: CameraStatus) -> None:
        values: dict[str, Any] = {"status": status}
        if status is CameraStatus.ONLINE:
            values["last_seen_at"] = datetime.now(UTC)
        try:
            with Session(self._engine) as session, session.begin():
                statement = update(Camera).where(Camera.id == camera_id).values(**values)
                result = cast(CursorResult[Any], session.execute(statement))
            if result.rowcount == 0:
                logger.debug("Camera %s is not in the database; status not stored", camera_id)
        except Exception as exc:
            logger.warning("Cannot store status of camera %s: %s", camera_id, type(exc).__name__)

    def heartbeat(self, camera_ids: Collection[int]) -> None:
        """Mark these (online) cameras as alive now."""
        if not camera_ids:
            return
        try:
            with Session(self._engine) as session, session.begin():
                session.execute(
                    update(Camera)
                    .where(Camera.id.in_(camera_ids))
                    .values(last_seen_at=datetime.now(UTC))
                )
        except Exception as exc:
            logger.warning("Cannot store camera heartbeat: %s", type(exc).__name__)
