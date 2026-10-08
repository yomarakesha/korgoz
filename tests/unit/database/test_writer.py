import threading
from functools import partial
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Location
from app.database.writer import DatabaseWriter


def file_engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(engine)
    return engine


def add_location(session: Session, name: str) -> None:
    session.add(Location(name=name))


def names(engine: Engine) -> list[str]:
    with Session(engine) as session:
        return list(session.scalars(select(Location.name).order_by(Location.id)))


def test_writes_in_order_and_drains_on_stop(tmp_path: Path) -> None:
    engine = file_engine(tmp_path)
    writer = DatabaseWriter(engine)
    writer.start()
    for i in range(20):
        writer.submit("location", partial(add_location, name=f"l{i}"))
    writer.stop()
    assert names(engine) == [f"l{i}" for i in range(20)]
    assert not writer.is_alive


def test_failed_write_is_dropped_and_rolled_back(tmp_path: Path) -> None:
    engine = file_engine(tmp_path)
    writer = DatabaseWriter(engine)
    writer.start()

    def broken(session: Session) -> None:
        session.add(Location(name="half-written"))
        session.flush()
        raise RuntimeError("boom")

    writer.submit("broken", broken)
    writer.submit("ok", lambda s: s.add(Location(name="after")))
    writer.stop()
    assert names(engine) == ["after"]


def test_periodic_work_runs_when_due(tmp_path: Path) -> None:
    ran = threading.Event()
    writer = DatabaseWriter(file_engine(tmp_path))
    writer.every(0.02, "tick", lambda _s: ran.set())
    writer.start()
    assert ran.wait(2)
    writer.stop()


def test_periodic_work_runs_once_more_on_stop(tmp_path: Path) -> None:
    calls: list[int] = []
    writer = DatabaseWriter(file_engine(tmp_path))
    writer.every(3600, "flush", lambda _s: calls.append(1))  # never due while running
    writer.start()
    writer.stop()
    assert calls == [1]
