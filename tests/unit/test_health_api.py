from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.config import get_settings
from app.core import health as health_module
from app.core.health import ComponentStatus
from app.database.session import get_engine
from app.main import create_app

OK, DOWN = ComponentStatus.OK, ComponentStatus.UNAVAILABLE
ClientFactory = Callable[..., TestClient]


@pytest.fixture
def client_factory(monkeypatch: pytest.MonkeyPatch) -> ClientFactory:
    def build(
        engine: Engine,
        *,
        qdrant: ComponentStatus = OK,
        ai: ComponentStatus = OK,
        mode: str = "anonymous",
    ) -> TestClient:
        monkeypatch.setenv("VISION_MODE", mode)
        get_settings.cache_clear()
        monkeypatch.setattr(health_module, "check_qdrant", lambda _settings: qdrant)
        monkeypatch.setattr(health_module, "check_ai", lambda _settings: ai)
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: engine
        return TestClient(app)

    return build


def test_health_ok(client_factory: ClientFactory, sqlite_engine: Engine) -> None:
    response = client_factory(sqlite_engine).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "qdrant": "ok",
        "ai": "ok",
        "cameras": 0,
    }


def test_qdrant_not_required_in_anonymous_mode(
    client_factory: ClientFactory, sqlite_engine: Engine
) -> None:
    body = client_factory(sqlite_engine, qdrant=DOWN).get("/health").json()
    assert body["status"] == "ok"
    assert body["qdrant"] == "unavailable"


def test_degraded_without_qdrant_in_recognition_mode(
    client_factory: ClientFactory, sqlite_engine: Engine
) -> None:
    response = client_factory(sqlite_engine, qdrant=DOWN, mode="recognition").get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_degraded_when_worker_unreachable(
    client_factory: ClientFactory, sqlite_engine: Engine
) -> None:
    body = client_factory(sqlite_engine, ai=DOWN).get("/health").json()
    assert body["status"] == "degraded"
    assert body["ai"] == "unavailable"


def test_health_error_without_database(client_factory: ClientFactory) -> None:
    broken = create_engine("postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    response = client_factory(broken).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["database"] == "unavailable"


def test_check_ai_reports_unreachable_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_VIEW_PORT", "1")
    get_settings.cache_clear()
    assert health_module.check_ai(get_settings()) is ComponentStatus.UNAVAILABLE
