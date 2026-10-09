"""Shared fixtures.

Unit tests run against in-memory SQLite and never need external services.
"""

import os
from collections.abc import Iterator
from typing import Any

# Must be set before `app.main` is imported anywhere (it builds settings at import time).
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from argon2 import PasswordHasher
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import models  # registers all tables on Base.metadata
from app.database.base import Base
from app.security import passwords

ADMIN_PASSWORD = "admin-password-1"


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real argon2id, but cheap parameters: production ones cost ~50 ms per hash."""
    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=256, parallelism=1)
    )


def add_user(engine: Engine, username: str, password: str, role: str = "user") -> int:
    with Session(engine) as session:
        user = models.User(
            username=username,
            password_hash=passwords.hash_password(password),
            role=models.UserRole(role),
        )
        session.add(user)
        session.commit()
        return user.id


def login(client: Any, username: str, password: str) -> Any:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


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
def anonymous_client_factory(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    """Makes independent TestClients (own cookies, not logged in) on the same database."""
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
    clients: list[TestClient] = []

    def make() -> TestClient:
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def anonymous_client(anonymous_client_factory: Any) -> Any:
    """TestClient (not logged in) on the in-memory SQLite engine; Qdrant reported OK."""
    return anonymous_client_factory()


@pytest.fixture
def api_client(anonymous_client: Any, sqlite_engine: Engine) -> Any:
    """`anonymous_client` logged in as an admin (the session cookie is kept)."""
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    login(anonymous_client, "admin", ADMIN_PASSWORD)
    return anonymous_client
