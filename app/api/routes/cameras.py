from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.auth import AuditDep
from app.api.dependencies import DbSession
from app.api.schemas.camera import CameraCreate, CameraRead, CameraUpdate
from app.database.models import Camera, Location
from app.security.types import AuditAction

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _get_or_404(db: DbSession, camera_id: int) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return camera


@router.get("", response_model=list[CameraRead])
def list_cameras(db: DbSession) -> list[CameraRead]:
    cameras = db.scalars(select(Camera).order_by(Camera.id))
    return [CameraRead.from_model(c) for c in cameras]


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(payload: CameraCreate, db: DbSession, record: AuditDep) -> CameraRead:
    if payload.location_id is not None and db.get(Location, payload.location_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Location does not exist")
    camera = Camera(**payload.model_dump())
    db.add(camera)
    db.flush()
    # Never the stream URL: it may contain the camera password.
    record(AuditAction.CAMERA_CREATED, "camera", camera.id, name=camera.name)
    db.commit()
    db.refresh(camera)
    return CameraRead.from_model(camera)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(camera_id: int, db: DbSession) -> CameraRead:
    return CameraRead.from_model(_get_or_404(db, camera_id))


@router.patch("/{camera_id}", response_model=CameraRead)
def update_camera(
    camera_id: int, payload: CameraUpdate, db: DbSession, record: AuditDep
) -> CameraRead:
    """Rename, move to another location (`location_id: null` = none) or enable/disable.

    The worker reads cameras at start: restart it for `enabled` to take effect.
    """
    camera = _get_or_404(db, camera_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("location_id") is not None and db.get(Location, changes["location_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Location does not exist")
    for field, value in changes.items():
        if field != "location_id" and value is None:
            continue  # name/enabled can't be cleared
        setattr(camera, field, value)
    record(AuditAction.CAMERA_UPDATED, "camera", camera.id, **changes)
    db.commit()
    db.refresh(camera)
    return CameraRead.from_model(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, db: DbSession, record: AuditDep) -> None:
    camera = _get_or_404(db, camera_id)
    record(AuditAction.CAMERA_DELETED, "camera", camera.id, name=camera.name)
    db.delete(camera)
    db.commit()
