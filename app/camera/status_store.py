"""Persists camera status changes so the API (a separate process) can see them."""

import logging
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, update
from sqlalchemy.orm import Session

from app.camera.types import CameraStatus
from app.database.models import Camera

logger = logging.getLogger(__name__)


class DatabaseStatusRecorder:
    """`StatusListener` that writes `cameras.status`; never raises."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __call__(self, camera_id: int, status: CameraStatus) -> None:
        try:
            with Session(self._engine) as session, session.begin():
                statement = update(Camera).where(Camera.id == camera_id).values(status=status)
                result = cast(CursorResult[Any], session.execute(statement))
            if result.rowcount == 0:
                logger.debug("Camera %s is not in the database; status not stored", camera_id)
        except Exception as exc:
            logger.warning("Cannot store status of camera %s: %s", camera_id, type(exc).__name__)
