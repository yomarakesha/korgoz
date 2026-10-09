"""Roles and audit actions.

Stored as plain strings (like `EventType`), so new members need no migration.
"""

from enum import StrEnum


class UserRole(StrEnum):
    # Full access: writes, user management, the audit log.
    ADMIN = "admin"
    # Read-only: dashboard, live view, events, analytics.
    USER = "user"


class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105  (an action name)
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DELETED = "USER_DELETED"
    CAMERA_CREATED = "CAMERA_CREATED"
    CAMERA_UPDATED = "CAMERA_UPDATED"
    CAMERA_DELETED = "CAMERA_DELETED"
    LOCATION_CREATED = "LOCATION_CREATED"
    LOCATION_DELETED = "LOCATION_DELETED"
    PERSON_REGISTERED = "PERSON_REGISTERED"
    PERSON_DELETED = "PERSON_DELETED"
