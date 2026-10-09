"""Audit log writer.

Entries are added to the caller's session and committed together with the change they
describe, so a rolled-back change leaves no audit entry. Never put credentials, stream
URLs or biometric data into `details`.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import AuditLog, User
from app.security.types import AuditAction


def record(
    db: Session,
    action: AuditAction,
    *,
    user: User | None,
    ip_address: str | None,
    target_type: str | None = None,
    target_id: int | None = None,
    username: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry; `username` defaults to the user's (set it for failed logins)."""
    db.add(
        AuditLog(
            timestamp=datetime.now(UTC),
            user_id=user.id if user else None,
            username=username if username is not None else (user.username if user else None),
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            details=details or {},
        )
    )
