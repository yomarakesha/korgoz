"""Shared FastAPI dependencies.

Routes depend on these functions instead of importing globals directly, so
tests can swap them via `app.dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.session import get_db, get_engine

SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
DbSession = Annotated[Session, Depends(get_db)]
