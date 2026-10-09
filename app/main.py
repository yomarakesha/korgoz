"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.auth import authorize, require_admin
from app.api.dashboard import mount_dashboard
from app.api.errors import register_error_handlers
from app.api.routes import (
    analytics,
    audit,
    auth,
    cameras,
    events,
    health,
    live_view,
    locations,
    persons,
    tracks,
    users,
)
from app.api.routes import (
    settings as settings_routes,
)
from app.config import get_settings
from app.core.logging import setup_logging
from app.core.security_headers import SecurityHeadersMiddleware
from app.database.session import get_engine
from app.security.login_limiter import LoginLimiter

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
    app.state.login_limiter = LoginLimiter(settings.auth_lockout_seconds)
    # Public: health checks (systemd, monitoring) and login.
    app.include_router(health.router)
    app.include_router(auth.router)
    # Any logged-in user may read; only admins may change (see app/api/auth.py).
    signed_in = [Depends(authorize)]
    for module in (
        cameras,
        live_view,
        tracks,
        persons,
        events,
        analytics,
        locations,
        settings_routes,
    ):
        app.include_router(module.router, dependencies=signed_in)
    admin_only = [Depends(require_admin)]
    app.include_router(users.router, dependencies=admin_only)
    app.include_router(audit.router, dependencies=admin_only)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    mount_dashboard(app, settings.dashboard_dir)
    return app


app = create_app()
