"""Persists track lifecycle (start / last seen / end) to the `tracks` table.

Writes happen in one background thread fed by a queue, so database latency or
an outage never slows down video processing. On failure a write is logged and
dropped; tracking itself keeps working.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.database.models import Track as TrackRow
from app.pipeline.types import FrameAnalysis
from app.tracking.tracker import TrackedObject

logger = logging.getLogger(__name__)

TrackKey = tuple[int, int]  # (camera_id, tracker-local track_id)


@dataclass(frozen=True)
class _Start:
    camera_id: int
    track: TrackedObject


@dataclass(frozen=True)
class _End:
    camera_id: int
    track: TrackedObject


_Operation = _Start | _End


class TrackStore:
    def __init__(self, engine: Engine, flush_interval_seconds: float = 5.0) -> None:
        self._engine = engine
        self._flush_interval = flush_interval_seconds
        self._queue: queue.Queue[_Operation] = queue.Queue()
        self._row_ids: dict[TrackKey, int] = {}
        self._last_seen: dict[TrackKey, datetime] = {}
        self._last_seen_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="track-store", daemon=True)

    # --- producer side (pipeline threads) ------------------------------------

    def __call__(self, analysis: FrameAnalysis) -> None:
        """`AnalysisSink`: enqueue lifecycle changes, remember last-seen times."""
        camera_id = analysis.frame.camera_id
        for track in analysis.tracks_started:
            self._queue.put(_Start(camera_id, track))
        with self._last_seen_lock:
            for track in analysis.tracks:
                self._last_seen[(camera_id, track.track_id)] = track.last_seen_at
        for track in analysis.tracks_ended:
            self._queue.put(_End(camera_id, track))

    def end_tracks(self, camera_id: int, tracks: list[TrackedObject]) -> None:
        for track in tracks:
            self._queue.put(_End(camera_id, track))

    # --- lifecycle -------------------------------------------------------------

    def start(self, camera_ids: list[int]) -> None:
        self._close_orphans(camera_ids)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Write everything still queued, then stop."""
        self._stop.set()
        self._thread.join(timeout)

    # --- consumer side (store thread) -----------------------------------------

    def _run(self) -> None:
        next_flush = time.monotonic() + self._flush_interval
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                operation = self._queue.get(timeout=0.5)
            except queue.Empty:
                operation = None
            if operation is not None:
                self._apply(operation)
            if time.monotonic() >= next_flush:
                self._flush_last_seen()
                next_flush = time.monotonic() + self._flush_interval
        self._flush_last_seen()

    def _apply(self, operation: _Operation) -> None:
        key = (operation.camera_id, operation.track.track_id)
        try:
            with Session(self._engine) as session, session.begin():
                if isinstance(operation, _Start):
                    row = TrackRow(
                        camera_id=operation.camera_id,
                        track_identifier=str(operation.track.track_id),
                        started_at=operation.track.started_at,
                        last_seen_at=operation.track.last_seen_at,
                    )
                    session.add(row)
                    session.flush()
                    self._row_ids[key] = row.id
                else:
                    row_id = self._row_ids.pop(key, None)
                    with self._last_seen_lock:
                        self._last_seen.pop(key, None)
                    if row_id is None:
                        return  # its start was never stored
                    session.execute(
                        update(TrackRow)
                        .where(TrackRow.id == row_id)
                        .values(
                            ended_at=operation.track.last_seen_at,
                            last_seen_at=operation.track.last_seen_at,
                        )
                    )
        except Exception as exc:
            logger.warning(
                "Cannot store track %s of camera %s: %s",
                operation.track.track_id,
                operation.camera_id,
                type(exc).__name__,
            )

    def _flush_last_seen(self) -> None:
        with self._last_seen_lock:
            pending = {
                self._row_ids[key]: seen
                for key, seen in self._last_seen.items()
                if key in self._row_ids
            }
        if not pending:
            return
        try:
            with Session(self._engine) as session, session.begin():
                for row_id, seen in pending.items():
                    session.execute(
                        update(TrackRow).where(TrackRow.id == row_id).values(last_seen_at=seen)
                    )
        except Exception as exc:
            logger.warning("Cannot update track last-seen times: %s", type(exc).__name__)

    def _close_orphans(self, camera_ids: list[int]) -> None:
        """Tracks left open by a crashed worker end at their last-seen time."""
        if not camera_ids:
            return
        try:
            with Session(self._engine) as session, session.begin():
                session.execute(
                    update(TrackRow)
                    .where(TrackRow.ended_at.is_(None), TrackRow.camera_id.in_(camera_ids))
                    .values(ended_at=TrackRow.last_seen_at)
                )
        except Exception as exc:
            logger.warning("Cannot close orphaned tracks: %s", type(exc).__name__)
