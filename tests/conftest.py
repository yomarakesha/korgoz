"""Shared fixtures.

Unit tests run against in-memory SQLite and never need external services.
"""

import os
from collections.abc import Iterator
from typing import Any

# Must be set before `app.main` is imported anywhere (it builds settings at import time).
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database.base import Base


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection so the in-memory DB survives
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=sqlite_engine)() as session:
        yield session


@pytest.fixture
def api_client(sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """TestClient whose database is the in-memory SQLite engine; Qdrant reported OK."""
    from fastapi.testclient import TestClient

    from app.core import health as health_module
    from app.core.health import ComponentStatus
    from app.database.session import get_db, get_engine
    from app.main import create_app

    monkeypatch.setattr(health_module, "check_qdrant", lambda _settings: ComponentStatus.OK)
    monkeypatch.setattr(health_module, "check_ai", lambda _settings: ComponentStatus.OK)
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_engine] = lambda: sqlite_engine
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client
