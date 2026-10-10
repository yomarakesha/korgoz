"""Persists track lifecycle (start / last seen / end) and sessions.

`tracks` gets a row when a track is confirmed; `last_seen_at` is refreshed every
TRACK_FLUSH_INTERVAL_SECONDS; when the track ends, `ended_at` is set and a
`sessions` row with the stay duration is added. All writes go through the
`DatabaseWriter` thread, so the pipeline never waits for the database.
"""

import logging
import threading
from datetime import datetime
from functools import partial

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.database.models import Camera, TrackSession
from app.database.models import Track as TrackRow
from app.database.writer import DatabaseWriter
from app.pipeline.types import FrameAnalysis
from app.tracking.tracker import TrackedObject

logger = logging.getLogger(__name__)

TrackKey = tuple[int, int]  # (camera_id, tracker-local track_id)


def _session_row(row: TrackRow, started_at: datetime, ended_at: datetime) -> TrackSession:
    # Times are passed in from the same source: SQLite returns naive datetimes,
    # so mixing a loaded value with an in-memory aware one would fail.
    return TrackSession(
        track_id=row.id,
        camera_id=row.camera_id,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=max((ended_at - started_at).total_seconds(), 0.0),
    )


class TrackStore:
    def __init__(
        self,
        engine: Engine,
        flush_interval_seconds: float = 5.0,
        writer: DatabaseWriter | None = None,
    ) -> None:
        self._engine = engine
        # Without a shared writer the store runs (and stops) its own.
        self._owns_writer = writer is None
        self._writer = writer or DatabaseWriter(engine, name="track-store")
        self._writer.every(flush_interval_seconds, "track last-seen times", self._flush_last_seen)
        self._row_ids: dict[TrackKey, int] = {}  # used only in the writer thread
        self._last_seen: dict[TrackKey, datetime] = {}
        self._last_seen_lock = threading.Lock()

    # --- producer side (pipeline threads) ------------------------------------

    def __call__(self, analysis: FrameAnalysis) -> None:
        """`AnalysisSink`: enqueue lifecycle changes, remember last-seen times."""
        camera_id = analysis.frame.camera_id
        for track in analysis.tracks_started:
            self._submit_start(camera_id, track)
        with self._last_seen_lock:
            for track in analysis.tracks:
                self._last_seen[(camera_id, track.track_id)] = track.last_seen_at
        self.end_tracks(camera_id, analysis.tracks_ended)

    def end_tracks(self, camera_id: int, tracks: list[TrackedObject]) -> None:
        for track in tracks:
            self._writer.submit(
                f"end of track {track.track_id} (camera {camera_id})",
                partial(self._end, camera_id=camera_id, track=track),
            )

    def _submit_start(self, camera_id: int, track: TrackedObject) -> None:
        self._writer.submit(
            f"track {track.track_id} (camera {camera_id})",
            partial(self._start, camera_id=camera_id, track=track),
        )

    # --- lifecycle -------------------------------------------------------------

    def start(self, camera_ids: list[int]) -> None:
        self.close_orphans(camera_ids)
        if self._owns_writer:
            self._writer.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Write everything still queued, then stop (own writer only)."""
        if self._owns_writer:
            self._writer.stop(timeout)

    # --- writer thread -----------------------------------------------------------

    def _start(self, session: Session, camera_id: int, track: TrackedObject) -> None:
        if session.get(Camera, camera_id) is None:
            return  # camera deleted; the worker stops it on the next reload
        row = TrackRow(
            camera_id=camera_id,
            track_identifier=str(track.track_id),
            started_at=track.started_at,
            last_seen_at=track.last_seen_at,
        )
        session.add(row)
        session.flush()
        self._row_ids[(camera_id, track.track_id)] = row.id

    def _end(self, session: Session, camera_id: int, track: TrackedObject) -> None:
        key = (camera_id, track.track_id)
        row_id = self._row_ids.pop(key, None)
        with self._last_seen_lock:
            self._last_seen.pop(key, None)
        if row_id is None:
            return  # its start was never stored
        row = session.get(TrackRow, row_id)
        if row is None:
            return
        row.ended_at = track.last_seen_at
        row.last_seen_at = track.last_seen_at
        session.add(_session_row(row, track.started_at, track.last_seen_at))

    def _flush_last_seen(self, session: Session) -> None:
        with self._last_seen_lock:
            pending = {
                self._row_ids[key]: seen
                for key, seen in self._last_seen.items()
                if key in self._row_ids
            }
        for row_id, seen in pending.items():
            session.execute(update(TrackRow).where(TrackRow.id == row_id).values(last_seen_at=seen))

    def close_orphans(self, camera_ids: list[int]) -> None:
        """Tracks left open by a crashed worker end at their last-seen time."""
        if not camera_ids:
            return
        try:
            with Session(self._engine) as session, session.begin():
                orphans = session.scalars(
                    select(TrackRow).where(
                        TrackRow.ended_at.is_(None), TrackRow.camera_id.in_(camera_ids)
                    )
                )
                for row in orphans:
                    row.ended_at = row.last_seen_at
                    session.add(_session_row(row, row.started_at, row.last_seen_at))
        except Exception as exc:
            logger.warning("Cannot close orphaned tracks: %s", type(exc).__name__)
