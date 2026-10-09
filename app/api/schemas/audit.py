from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.security.types import AuditAction


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    user_id: int | None
    username: str | None
    action: AuditAction
    target_type: str | None
    target_id: int | None
    ip_address: str | None
    details: dict[str, Any]
