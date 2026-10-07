from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.schemas.track import TrackRead
from app.database.models import Track

router = APIRouter(prefix="/tracks", tags=["tracks"])


@router.get("", response_model=list[TrackRead])
def list_tracks(
    db: DbSession,
    camera_id: int | None = None,
    active: Annotated[bool | None, Query(description="true = still visible")] = None,
    since: Annotated[datetime | None, Query(description="started at or after")] = None,
    until: Annotated[datetime | None, Query(description="started before")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TrackRead]:
    """Tracks, newest first."""
    query = select(Track)
    if camera_id is not None:
        query = query.where(Track.camera_id == camera_id)
    if active is not None:
        query = query.where(Track.ended_at.is_(None) if active else Track.ended_at.is_not(None))
    if since is not None:
        query = query.where(Track.started_at >= since)
    if until is not None:
        query = query.where(Track.started_at < until)
    query = query.order_by(Track.started_at.desc(), Track.id.desc()).limit(limit).offset(offset)
    return [TrackRead.from_model(t) for t in db.scalars(query)]


@router.get("/{track_id}", response_model=TrackRead)
def get_track(track_id: int, db: DbSession) -> TrackRead:
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Track not found")
    return TrackRead.from_model(track)
