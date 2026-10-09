"""Read the audit log (admin only; enforced where the router is included)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.api.schemas.audit import AuditRead
from app.database.models import AuditLog
from app.security.types import AuditAction

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditRead])
def list_audit(
    db: DbSession,
    user_id: int | None = None,
    action: Annotated[
        list[AuditAction] | None, Query(description="repeat to select several actions")
    ] = None,
    since: Annotated[datetime | None, Query(description="at or after (ISO 8601)")] = None,
    until: Annotated[datetime | None, Query(description="before (ISO 8601)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLog]:
    """Audit entries, newest first."""
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action.in_(action))
    if since is not None:
        query = query.where(AuditLog.timestamp >= since)
    if until is not None:
        query = query.where(AuditLog.timestamp < until)
    query = (
        query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
    )
    return list(db.scalars(query))
