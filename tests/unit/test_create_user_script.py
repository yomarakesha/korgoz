from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, User
from app.security.passwords import verify_password
from app.security.sessions import create_session, resolve_session
from app.security.types import AuditAction, UserRole
from scripts.create_user import UserError, upsert_user


def test_creates_admin_then_resets_password(db_session: Session) -> None:
    user, created = upsert_user(db_session, "Admin", "first-password", UserRole.ADMIN, reset=False)
    assert created
    assert (user.username, user.role) == ("admin", UserRole.ADMIN)
    assert verify_password(user.password_hash, "first-password")

    with pytest.raises(UserError, match="already exists"):
        upsert_user(db_session, "admin", "second-password", None, reset=False)

    now = datetime.now(UTC)
    token = create_session(db_session, user, timedelta(hours=1), now)
    user.is_active = False
    db_session.commit()
    user, created = upsert_user(db_session, "admin", "second-password", None, reset=True)
    assert not created
    assert user.is_active
    assert user.role is UserRole.ADMIN  # unchanged without --role
    assert verify_password(user.password_hash, "second-password")
    assert resolve_session(db_session, token, now) is None  # old sessions revoked

    actions = db_session.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
    assert actions == [AuditAction.USER_CREATED, AuditAction.USER_UPDATED]
    assert "password" not in str(db_session.scalars(select(AuditLog.details)).all())


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [("a", "long-enough-pw", "Username"), ("bob", "short", "at least")],
)
def test_rejects_bad_input(db_session: Session, username: str, password: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        upsert_user(db_session, username, password, None, reset=False)
    assert db_session.scalars(select(User)).all() == []
