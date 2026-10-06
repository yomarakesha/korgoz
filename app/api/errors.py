"""Translate infrastructure failures into clean HTTP responses."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)


async def _database_unavailable(_request: Request, exc: Exception) -> JSONResponse:
    # The exception text can include the connection URL; log only its type.
    logger.error("Database unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database unavailable"},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OperationalError, _database_unavailable)
