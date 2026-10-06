from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.schemas.camera import CameraCreate, CameraRead
from app.database.models import Camera, Location

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
def create_camera(payload: CameraCreate, db: DbSession) -> CameraRead:
    if payload.location_id is not None and db.get(Location, payload.location_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Location does not exist")
    camera = Camera(**payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return CameraRead.from_model(camera)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(camera_id: int, db: DbSession) -> CameraRead:
    return CameraRead.from_model(_get_or_404(db, camera_id))


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, db: DbSession) -> None:
    db.delete(_get_or_404(db, camera_id))
    db.commit()
