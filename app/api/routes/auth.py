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
# One client IP may try this many times more logins than one username from that IP
# (stops spraying many usernames without locking anyone out from elsewhere).
IP_LIMIT_FACTOR = 4


def _limiter(request: Request) -> LoginLimiter:
    limiter: LoginLimiter = request.app.state.login_limiter
    return limiter


def _too_many(wait: float) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many failed attempts, try again later",
        headers={"Retry-After": str(int(wait) + 1)},
    )


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
    # Keyed by username *and* IP: failures from an attacker's address do not lock the
    # real user out from theirs. The attempt is counted before the password is checked.
    account_key = f"login:{username}|{ip}"
    limit = settings.auth_max_failed_logins
    limiter = _limiter(request)
    wait = limiter.attempt({account_key: limit, f"ip:{ip}": limit * IP_LIMIT_FACTOR})
    if wait > 0:
        raise _too_many(wait)

    user = db.scalars(select(User).where(User.username == username)).one_or_none()
    if user is None:
        burn_verification_time(payload.password)
    valid = user is not None and verify_password(user.password_hash, payload.password)
    if user is None or not valid or not user.is_active:
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

    limiter.success(account_key)  # not the IP key: own logins must not reset spraying
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
    # A stolen session must not be able to guess the current password at full speed.
    key = f"password:{user.id}"
    wait = _limiter(request).attempt({key: settings.auth_max_failed_logins})
    if wait > 0:
        raise _too_many(wait)
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    _limiter(request).success(key)
    check_new_password(payload.new_password, settings.password_min_length, user.username)
    user.password_hash = hash_password(payload.new_password)
    revoke_user_sessions(db, user.id, keep_token=session_token(request))
    record(AuditAction.PASSWORD_CHANGED, "user", user.id)
    db.commit()
