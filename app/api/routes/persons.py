"""Registered persons (recognition mode).

Registration: one photo -> one face -> one embedding. The vector goes to
Qdrant, PostgreSQL keeps only the person and a reference to the vector. The
photo is decoded in memory and never written to disk.
"""

import logging
from datetime import datetime
from typing import Annotated, cast

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.auth import AuditDep
from app.api.dependencies import DbSession, RecognitionDep, SettingsDep, VectorStoreDep
from app.api.schemas.event import TimelineEntry
from app.api.schemas.person import PersonRead
from app.camera.types import Image
from app.config import Settings, VisionMode
from app.database.models import FaceEmbedding, Person
from app.events.timeline import PersonNotFoundError, TimelineService
from app.recognition.service import RegistrationError
from app.security.types import AuditAction
from app.vector_store.base import VectorStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persons", tags=["persons"])

# Larger photos are scaled down before face detection (faster, same result).
MAX_IMAGE_SIDE = 1600
_QDRANT_DOWN = "Vector store (Qdrant) unavailable"


def _require_recognition_mode(settings: Settings) -> None:
    if settings.vision_mode is not VisionMode.RECOGNITION:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Face registration requires VISION_MODE=recognition"
        )


def decode_image(data: bytes) -> Image:
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:  # e.g. above OPENCV_IO_MAX_IMAGE_PIXELS (see app/__init__.py)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Image dimensions are too large"
        ) from None
    if image is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is not an image")
    scale = MAX_IMAGE_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cast(Image, image)


def _get_or_404(db: DbSession, person_id: int) -> Person:
    person = db.get(Person, person_id, options=[selectinload(Person.embeddings)])
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return person


@router.post("", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def register_person(
    db: DbSession,
    settings: SettingsDep,
    service: RecognitionDep,
    record: AuditDep,
    name: Annotated[str, Form(min_length=1, max_length=255)],
    photo: Annotated[UploadFile, File(description="JPEG/PNG with exactly one face")],
    external_id: Annotated[str | None, Form(max_length=255)] = None,
    description: Annotated[str | None, Form()] = None,
) -> PersonRead:
    _require_recognition_mode(settings)
    # Sync route: FastAPI runs it in a thread pool, so model inference doesn't block the loop.
    data = photo.file.read(settings.face_upload_max_bytes + 1)
    if len(data) > settings.face_upload_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Photo is too large")
    image = decode_image(data)
    del data
    if external_id and db.scalar(select(Person.id).where(Person.external_id == external_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "external_id already registered")
    try:
        vector = service.registration_embedding(image)
    except RegistrationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    person = Person(name=name, external_id=external_id or None, description=description)
    db.add(person)
    db.flush()  # assigns person.id; nothing is committed yet
    # Vector first: if Qdrant fails, the transaction is simply rolled back.
    try:
        vector_id = service.store.add_embedding(person.id, vector, service.embedder.name)
    except VectorStoreError:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _QDRANT_DOWN) from None
    db.add(
        FaceEmbedding(person_id=person.id, vector_id=vector_id, model_name=service.embedder.name)
    )
    # Only the id: the person's name and face stay out of the audit log.
    record(AuditAction.PERSON_REGISTERED, "person", person.id)
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Don't leave an orphan vector that could match a person who doesn't exist.
        try:
            service.store.delete_embedding(vector_id)
        except VectorStoreError:
            logger.error("Orphan vector %s left in Qdrant", vector_id)
        raise
    logger.info("Registered person %s", person.id)
    return PersonRead.from_model(_get_or_404(db, person.id))


@router.get("", response_model=list[PersonRead])
def list_persons(db: DbSession) -> list[PersonRead]:
    query = select(Person).options(selectinload(Person.embeddings)).order_by(Person.id)
    return [PersonRead.from_model(p) for p in db.scalars(query)]


@router.get("/{person_id}", response_model=PersonRead)
def get_person(person_id: int, db: DbSession) -> PersonRead:
    return PersonRead.from_model(_get_or_404(db, person_id))


@router.get("/{person_id}/timeline", response_model=list[TimelineEntry])
def person_timeline(
    person_id: int,
    db: DbSession,
    since: Annotated[datetime | None, Query(description="at or after (ISO 8601)")] = None,
    until: Annotated[datetime | None, Query(description="before (ISO 8601)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TimelineEntry]:
    """Where and when the person was seen, newest first."""
    try:
        events = TimelineService(db).person_timeline(
            person_id, since=since, until=until, limit=limit, offset=offset
        )
    except PersonNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found") from None
    return [TimelineEntry.from_object(e) for e in events]


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(person_id: int, db: DbSession, store: VectorStoreDep, record: AuditDep) -> None:
    """Delete the person and all their face vectors (right to be forgotten)."""
    person = _get_or_404(db, person_id)
    # Vectors first: if Qdrant is down, keep the person so the delete can be retried.
    try:
        store.delete_person(person.id)
    except VectorStoreError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _QDRANT_DOWN) from None
    record(AuditAction.PERSON_DELETED, "person", person.id)
    db.delete(person)
    db.commit()
    logger.info("Deleted person %s", person_id)
