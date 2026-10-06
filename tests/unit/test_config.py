from typing import Any

import pytest
from pydantic import ValidationError

from app.config import LogLevel, Settings, VisionMode


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"database_url": "postgresql+psycopg://u:p@localhost/db"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_defaults() -> None:
    settings = make()
    assert settings.vision_mode is VisionMode.ANONYMOUS
    assert settings.log_level is LogLevel.INFO
    assert settings.detection_interval >= 1
    assert 0.0 <= settings.face_match_threshold <= 1.0


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACE_MATCH_THRESHOLD", "0.6")
    monkeypatch.setenv("VISION_MODE", "recognition")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    settings = Settings(_env_file=None)
    assert settings.face_match_threshold == 0.6
    assert settings.vision_mode is VisionMode.RECOGNITION
    assert settings.log_level is LogLevel.DEBUG


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("face_match_threshold", 1.5),
        ("face_match_threshold", -0.1),
        ("detection_interval", 0),
        ("event_cooldown_seconds", -1),
        ("vision_mode", "spy"),
    ],
)
def test_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_secrets_are_not_exposed_in_repr() -> None:
    settings = make(
        database_url="postgresql+psycopg://u:db-secret@localhost/db",
        camera_url="rtsp://admin:cam-secret@10.0.0.5/stream",
    )
    text = repr(settings) + str(settings.model_dump())
    assert "db-secret" not in text
    assert "cam-secret" not in text
