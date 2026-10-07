from datetime import datetime

from pydantic import BaseModel

from app.database.models import Track


class TrackRead(BaseModel):
    id: int
    camera_id: int
    track_identifier: str  # tracker-local number shown in live view ("Track #42")
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None
    active: bool
    duration_seconds: float

    @classmethod
    def from_model(cls, track: Track) -> "TrackRead":
        end = track.ended_at or track.last_seen_at
        return cls(
            id=track.id,
            camera_id=track.camera_id,
            track_identifier=track.track_identifier,
            started_at=track.started_at,
            last_seen_at=track.last_seen_at,
            ended_at=track.ended_at,
            active=track.ended_at is None,
            duration_seconds=round(max((end - track.started_at).total_seconds(), 0.0), 2),
        )
