"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routes import cameras, events, health, live_view, persons, tracks
from app.config import get_settings
from app.core.logging import setup_logging
from app.database.session import get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Starting %s %s (environment=%s, mode=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        settings.vision_mode.value,
    )
    yield
    get_engine().dispose()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level.value)

    app = FastAPI(
        title="KörGöz API",
        description="KörGöz — Intelligent Vision & Situational Analytics Platform",
        version=__version__,
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(cameras.router)
    app.include_router(live_view.router)
    app.include_router(tracks.router)
    app.include_router(persons.router)
    app.include_router(events.router)
    return app


app = create_app()
