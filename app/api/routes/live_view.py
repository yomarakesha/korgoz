"""Live view proxy: the worker serves frames on localhost, the API exposes them.

Keeping a single public entry point means authentication (Phase 9) and CORS
apply to video as well, and the worker port never has to be opened.
"""

from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.api.dependencies import DbSession, SettingsDep
from app.config import Settings
from app.database.models import Camera

router = APIRouter(prefix="/cameras", tags=["live view"])

_NO_STORE = {"Cache-Control": "no-store"}
_WORKER_DOWN = "Live view unavailable: camera worker is not running"


def _worker_url(settings: Settings, path: str) -> str:
    return f"http://{settings.live_view_host}:{settings.live_view_port}{path}"


async def _ensure_camera(db: DbSession, camera_id: int) -> None:
    if await run_in_threadpool(db.get, Camera, camera_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")


@router.get(
    "/{camera_id}/snapshot",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def camera_snapshot(camera_id: int, db: DbSession, settings: SettingsDep) -> Response:
    """Latest annotated frame as JPEG."""
    await _ensure_camera(db, camera_id)
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            upstream = await client.get(_worker_url(settings, f"/cameras/{camera_id}/snapshot.jpg"))
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _WORKER_DOWN) from exc
    if upstream.status_code != status.HTTP_200_OK:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No frames from this camera yet")
    return Response(upstream.content, media_type="image/jpeg", headers=_NO_STORE)


@router.get(
    "/{camera_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"multipart/x-mixed-replace": {}}}},
)
async def camera_stream(camera_id: int, db: DbSession, settings: SettingsDep) -> StreamingResponse:
    """MJPEG stream with bounding boxes; usable directly as `<img src=...>`."""
    await _ensure_camera(db, camera_id)
    client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=None), trust_env=False)
    request = client.build_request(
        "GET", _worker_url(settings, f"/cameras/{camera_id}/stream.mjpg")
    )
    try:
        upstream = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _WORKER_DOWN) from exc
    if upstream.status_code != status.HTTP_200_OK:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No frames from this camera yet")

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(), media_type=upstream.headers["content-type"], headers=_NO_STORE
    )
