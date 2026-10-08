from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dashboard import mount_dashboard
from app.config import get_settings
from app.main import create_app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<div id=root></div>")
    (root / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside dist")
    return root


def client_for(dist: Path) -> TestClient:
    app = FastAPI()
    assert mount_dashboard(app, dist)
    return TestClient(app)


def test_index_assets_and_client_side_routes(dist: Path) -> None:
    client = client_for(dist)
    assert client.get("/ui/").text == "<div id=root></div>"
    asset = client.get("/ui/assets/index-abc.js")
    assert asset.text == "console.log(1)"
    assert "immutable" in asset.headers["cache-control"]
    # React Router pages are served by index.html.
    page = client.get("/ui/persons/5")
    assert page.text == "<div id=root></div>"
    assert page.headers["cache-control"] == "no-cache"


def test_missing_asset_is_404_not_index(dist: Path) -> None:
    assert client_for(dist).get("/ui/assets/old-hash.js").status_code == 404


def test_path_traversal_is_blocked(dist: Path) -> None:
    client = client_for(dist)
    for path in ("/ui/../secret.txt", "/ui/%2e%2e/secret.txt", "/ui/..%2fsecret.txt"):
        assert "outside dist" not in client.get(path).text


def test_root_redirects_to_dashboard(dist: Path) -> None:
    client = client_for(dist)
    assert client.get("/", follow_redirects=False).headers["location"] == "/ui/"
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/ui/"


def test_not_built_means_no_routes(tmp_path: Path) -> None:
    app = FastAPI()
    assert not mount_dashboard(app, tmp_path / "missing")
    assert TestClient(app).get("/ui/").status_code == 404


def test_cors_only_when_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DASHBOARD_DIR", str(tmp_path))
    get_settings.cache_clear()
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    plain = TestClient(create_app()).options("/health", headers=headers)
    assert "access-control-allow-origin" not in plain.headers

    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:5173"]')
    get_settings.cache_clear()
    allowed = TestClient(create_app()).options("/health", headers=headers)
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_public_settings_have_no_secrets(api_client: Any) -> None:
    body = api_client.get("/settings").json()
    assert body["vision_mode"] == "anonymous"
    assert body["person_detector_model"] == "yolox_s.onnx"
    text = str(body).lower()
    for secret in ("sqlite", "database", "qdrant", "camera_url", "6333", "api_key"):
        assert secret not in text
