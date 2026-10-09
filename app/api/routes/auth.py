"""Login, logout, current user, own password change."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.auth import (
    SESSION_COOKIE,
    AuditDep,
    CurrentUser,
    check_new_password,
    client_ip,
    session_token,
)
from app.api.dependencies import DbSession, SettingsDep
from app.api.schemas.user import LoginRequest, LoginResponse, PasswordChange, UserRead
from app.database.models import User
from app.security import audit
from app.security.login_limiter import LoginLimiter
from app.security.passwords import (
    burn_verification_time,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.security.sessions import create_session, revoke_session, revoke_user_sessions
from app.security.types import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_CREDENTIALS = "Invalid username or password"


def _limiter(request: Request) -> LoginLimiter:
    limiter: LoginLimiter = request.app.state.login_limiter
    return limiter


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
) -> LoginResponse:
    """Check the password, open a session and set the HttpOnly session cookie."""
    username = payload.username.strip().lower()
    ip = client_ip(request)
    keys = (f"user:{username}", f"ip:{ip}")
    limiter = _limiter(request)
    wait = limiter.retry_after(*keys)
    if wait > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed logins, try again later",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    user = db.scalars(select(User).where(User.username == username)).one_or_none()
    if user is None:
        burn_verification_time(payload.password)
    valid = user is not None and verify_password(user.password_hash, payload.password)
    if user is None or not valid or not user.is_active:
        limiter.failure(*keys)
        audit.record(
            db,
            AuditAction.LOGIN_FAILED,
            user=user,
            username=username,
            ip_address=ip,
            details={"reason": "inactive" if valid else "bad_credentials"},
        )
        db.commit()
        # Same answer for unknown user, wrong password and disabled account.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)

    limiter.success(*keys)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    now = datetime.now(UTC)
    lifetime = timedelta(hours=settings.auth_session_hours)
    token = create_session(db, user, lifetime, now)
    user.last_login_at = now
    audit.record(db, AuditAction.LOGIN, user=user, ip_address=ip)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,  # not readable by JavaScript
        samesite="strict",  # not sent with requests from other sites (CSRF)
        secure=settings.auth_cookie_secure,
        path="/",
    )
    logger.info("User %s logged in", user.id)
    return LoginResponse(
        user=UserRead.model_validate(user), access_token=token, expires_at=now + lifetime
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, record: AuditDep) -> None:
    token = session_token(request)
    if token:
        revoke_session(db, token)
    record(AuditAction.LOGOUT)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    record: AuditDep,
) -> None:
    """Change your own password; your other sessions are logged out."""
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    check_new_password(payload.new_password, settings.password_min_length, user.username)
    user.password_hash = hash_password(payload.new_password)
    revoke_user_sessions(db, user.id, keep_token=session_token(request))
    record(AuditAction.PASSWORD_CHANGED, "user", user.id)
    db.commit()
