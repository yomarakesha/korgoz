"""Background database writer for the worker process.

One thread applies writes in the order they were submitted, each in its own
transaction. Video processing only enqueues work, so database latency or an
outage never slows it down. A failed write is logged (exception type only) and
dropped.

Order matters: a track row is submitted before the events that reference it,
so both must go through the same writer.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

Work = Callable[[Session], None]


@dataclass(frozen=True)
class _Task:
    label: str
    work: Work


@dataclass
class _Periodic:
    label: str
    interval: float
    work: Work
    due: float = 0.0


class DatabaseWriter:
    def __init__(self, engine: Engine, name: str = "db-writer") -> None:
        self.engine = engine
        self._queue: queue.Queue[_Task] = queue.Queue()
        self._periodic: list[_Periodic] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def submit(self, label: str, work: Work) -> None:
        """Run `work(session)` in the writer thread, inside a transaction."""
        self._queue.put(_Task(label, work))

    def every(self, interval_seconds: float, label: str, work: Work) -> None:
        """Run `work` periodically, and once more on stop. Register before start()."""
        self._periodic.append(_Periodic(label, interval_seconds, work))

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        now = time.monotonic()
        for periodic in self._periodic:
            periodic.due = now + periodic.interval
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Write everything still queued, run periodic work a last time, then stop."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        wait = min([0.5, *(p.interval for p in self._periodic)])
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                task = self._queue.get(timeout=wait)
            except queue.Empty:
                task = None
            if task is not None:
                self._apply(task.label, task.work)
            now = time.monotonic()
            for periodic in self._periodic:
                if now >= periodic.due:
                    self._apply(periodic.label, periodic.work)
                    periodic.due = time.monotonic() + periodic.interval
        for periodic in self._periodic:
            self._apply(periodic.label, periodic.work)

    def _apply(self, label: str, work: Work) -> None:
        try:
            with Session(self.engine) as session, session.begin():
                work(session)
        except Exception as exc:
            logger.warning("Cannot store %s: %s", label, type(exc).__name__)
