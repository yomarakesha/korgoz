"""Server-side login sessions.

The client gets a random token (cookie or `Authorization: Bearer`); the database keeps
only its SHA-256, so a leaked database dump cannot be replayed as a login. Deleting the
row logs the session out immediately (unlike a stateless JWT).
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import AuthSession, User

TOKEN_BYTES = 32


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, lifetime: timedelta, now: datetime) -> str:
    """Add a session for `user` (caller commits) and return its token."""
    # Housekeeping: expired sessions of anyone are useless.
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        AuthSession(
            token_hash=_digest(token), user_id=user.id, created_at=now, expires_at=now + lifetime
        )
    )
    return token


def resolve_session(db: Session, token: str, now: datetime) -> User | None:
    """The active user owning a valid token, or None."""
    query = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == _digest(token),
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    return db.scalars(query).one_or_none()


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))


def revoke_user_sessions(db: Session, user_id: int, keep_token: str | None = None) -> None:
    """Log the user out everywhere (except, optionally, the current session)."""
    statement = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_token is not None:
        statement = statement.where(AuthSession.token_hash != _digest(keep_token))
    db.execute(statement)
