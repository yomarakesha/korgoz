"""Shared FastAPI dependencies.

Routes depend on these functions instead of importing globals directly, so
tests can swap them via `app.dependency_overrides`.
"""

from functools import cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.session import get_db, get_engine
from app.detection.person_detector import ModelLoadError
from app.recognition.service import FaceRecognitionService
from app.vector_store.base import VectorStore

SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
DbSession = Annotated[Session, Depends(get_db)]


@cache
def _recognition_service() -> FaceRecognitionService:
    from app.pipeline.factory import build_recognition_service

    return build_recognition_service(get_settings())


def get_recognition_service() -> FaceRecognitionService:
    """Face models for registration, loaded on first use and kept for the process."""
    try:
        return _recognition_service()
    except ModelLoadError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Face models are missing: run python -m scripts.download_models",
        ) from exc


RecognitionDep = Annotated[FaceRecognitionService, Depends(get_recognition_service)]


def get_vector_store(settings: Annotated[Settings, Depends(get_settings)]) -> VectorStore:
    from app.pipeline.factory import build_vector_store

    return build_vector_store(settings)


VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
