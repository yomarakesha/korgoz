"""Engine and session factory.

The engine is created lazily so that importing this module never opens a
connection (tests and tooling can import models without a database).
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        echo=settings.database_echo,
        pool_pre_ping=True,  # transparently replace connections dropped by PostgreSQL restarts
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def ping_database(engine: Engine) -> None:
    """Raise if the database is unreachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
