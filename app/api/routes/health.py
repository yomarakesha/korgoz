from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.dependencies import EngineDep, SettingsDep
from app.core.health import ComponentStatus, build_report

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: ComponentStatus
    qdrant: ComponentStatus
    ai: ComponentStatus
    cameras: int


@router.get("/health", response_model=HealthResponse)
def health(engine: EngineDep, settings: SettingsDep, response: Response) -> HealthResponse:
    report = build_report(engine, settings)
    if report.status == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=report.status,
        database=report.database,
        qdrant=report.qdrant,
        ai=report.ai,
        cameras=report.cameras,
    )
