from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import AuthSession, User
from app.security.sessions import (
    create_session,
    resolve_session,
    revoke_session,
    revoke_user_sessions,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def make_user(db: Session, name: str = "bob") -> User:
    user = User(username=name, password_hash="x")
    db.add(user)
    db.flush()
    return user


def test_token_resolves_until_expiry_and_only_its_hash_is_stored(db_session: Session) -> None:
    user = make_user(db_session)
    token = create_session(db_session, user, HOUR, NOW)
    db_session.commit()
    assert db_session.scalar(select(AuthSession.token_hash)) != token
    assert resolve_session(db_session, token, NOW + HOUR / 2) == user
    assert resolve_session(db_session, token, NOW + HOUR) is None
    assert resolve_session(db_session, token + "x", NOW) is None


def test_blocked_user_has_no_session(db_session: Session) -> None:
    user = make_user(db_session)
    token = create_session(db_session, user, HOUR, NOW)
    user.is_active = False
    db_session.commit()
    assert resolve_session(db_session, token, NOW) is None


def test_revoke_one_or_all_but_current(db_session: Session) -> None:
    user = make_user(db_session)
    first, second, third = (create_session(db_session, user, HOUR, NOW) for _ in range(3))
    revoke_session(db_session, first)
    assert resolve_session(db_session, first, NOW) is None
    revoke_user_sessions(db_session, user.id, keep_token=second)
    assert resolve_session(db_session, second, NOW) == user
    assert resolve_session(db_session, third, NOW) is None


def test_expired_sessions_are_cleaned_up_on_login(db_session: Session) -> None:
    user = make_user(db_session)
    create_session(db_session, user, HOUR, NOW)
    create_session(db_session, user, HOUR, NOW + 2 * HOUR)
    assert db_session.scalar(select(func.count(AuthSession.id))) == 1
