"""Authentication and role checks as FastAPI dependencies.

A request is authenticated by the session cookie (dashboard, `<img>` live view) or by
`Authorization: Bearer <token>` (scripts). Roles: `user` may only read (GET/HEAD),
`admin` may do everything. See docs/security.md.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from app.api.dependencies import DbSession
from app.database.models import User
from app.security import audit
from app.security.passwords import password_problem
from app.security.sessions import resolve_session
from app.security.types import AuditAction, UserRole

SESSION_COOKIE = "korgoz_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def session_token(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and credentials:
        return credentials.strip()
    return request.cookies.get(SESSION_COOKIE) or None


def client_ip(request: Request) -> str | None:
    # Behind a reverse proxy run uvicorn with --proxy-headers so this is the real client.
    return request.client.host if request.client else None


def get_current_user(request: Request, db: DbSession) -> User:
    token = session_token(request)
    user = resolve_session(db, token, datetime.now(UTC)) if token else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def authorize(request: Request, user: CurrentUser) -> None:
    """Router-level default: any user may read, only admins may change anything.

    Secure by default: a new POST/PATCH/DELETE route on such a router is admin-only
    without anyone having to remember it.
    """
    if request.method not in SAFE_METHODS and user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")


class Auditor:
    """Writes audit entries for the current request (user and client IP filled in)."""

    def __init__(self, db: DbSession, request: Request, user: CurrentUser) -> None:
        self._db = db
        self._ip = client_ip(request)
        self._user = user

    def __call__(
        self,
        action: AuditAction,
        target_type: str | None = None,
        target_id: int | None = None,
        **details: Any,
    ) -> None:
        audit.record(
            self._db,
            action,
            user=self._user,
            ip_address=self._ip,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )


AuditDep = Annotated[Auditor, Depends()]


def check_new_password(password: str, min_length: int, username: str) -> None:
    problem = password_problem(password, min_length, username)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
