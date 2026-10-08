"""PostgreSQL fixture for integration tests.

Set TEST_DATABASE_URL to an EMPTY, disposable database, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://korgoz:pw@localhost:5432/korgoz_test
Migrations run before each test and the schema is dropped after it.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def migrated_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except Exception:
        pytest.skip("PostgreSQL at TEST_DATABASE_URL is unreachable")

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    yield TEST_DATABASE_URL
    command.downgrade(config, "base")
    engine.dispose()
