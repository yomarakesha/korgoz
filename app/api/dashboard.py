"""Serves the built React dashboard (frontend/dist) under /ui.

Same origin as the API: no CORS, and the auth cookie of Phase 9 will cover the
dashboard too. The dashboard lives under /ui because its page paths (/cameras,
/events, ...) would otherwise collide with the API's.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)

PREFIX = "/ui"


def mount_dashboard(app: FastAPI, dist: Path) -> bool:
    """Register the dashboard routes; False (and nothing registered) if it isn't built."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        logger.info("Dashboard not built (%s missing): run `npm run build` in frontend/", index)
        return False

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(f"{PREFIX}/")

    @app.get(PREFIX, include_in_schema=False)
    def ui_root() -> RedirectResponse:
        return RedirectResponse(f"{PREFIX}/")

    @app.get(PREFIX + "/{path:path}", include_in_schema=False)
    def ui(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        if candidate.is_file():
            # Vite puts a content hash in asset names, so they can be cached forever.
            cache = (
                "public, max-age=31536000, immutable" if "/assets/" in f"/{path}" else "no-cache"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if path.startswith("assets/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        # Client-side routes (/ui/persons/5, ...) are all handled by index.html.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    logger.info("Dashboard served at %s/", PREFIX)
    return True
