from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.schemas.location import LocationCreate, LocationRead
from app.database.models import Location

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[LocationRead])
def list_locations(db: DbSession) -> list[Location]:
    return list(db.scalars(select(Location).order_by(Location.name)))


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, db: DbSession) -> Location:
    if db.scalar(select(Location.id).where(Location.name == payload.name)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Location with this name already exists")
    location = Location(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: int, db: DbSession) -> None:
    """Cameras and past events keep existing, without a location."""
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    db.delete(location)
    db.commit()
