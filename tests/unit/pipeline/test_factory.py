from pathlib import Path
from typing import Any

from app.config import Settings
from app.pipeline.factory import build_ai_components


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, database_url="sqlite://", **values)


def test_missing_models_are_reported_not_raised(tmp_path: Path) -> None:
    components = build_ai_components(
        settings(
            vision_mode="recognition",
            person_detector_model_path=tmp_path / "none.onnx",
            face_detector_model_path=tmp_path / "none2.onnx",
        )
    )
    assert components.person_detector is None
    assert components.status == "error"
    assert len(components.describe()["errors"]) == 2  # type: ignore[arg-type]


def test_anonymous_mode_never_loads_face_detector(tmp_path: Path) -> None:
    components = build_ai_components(
        settings(
            person_detector_enabled=False,
            face_detector_model_path=tmp_path / "none.onnx",  # would error if loaded
        )
    )
    assert components.face_detector is None
    assert components.status == "not_configured"
