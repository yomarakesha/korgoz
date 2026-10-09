"""Create a dashboard/API user, or reset a forgotten password.

Usage:
    python -m scripts.create_user admin --role admin          # first administrator
    python -m scripts.create_user alice                        # read-only user
    python -m scripts.create_user admin --reset                # new password, unblock
    echo "$PASSWORD" | python -m scripts.create_user bob --password-stdin
    python -m scripts.create_user admin --role admin --if-no-users   # setup scripts

The password is asked twice without echo (or read from stdin) and never printed.
Works directly on the database (DATABASE_URL), so it also helps when no admin can log in.
"""

import argparse
import getpass
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas.user import Username
from app.config import get_settings
from app.database.models import User
from app.database.session import get_session_factory
from app.security import audit
from app.security.passwords import hash_password, password_problem
from app.security.sessions import revoke_user_sessions
from app.security.types import AuditAction, UserRole


class UserError(Exception):
    pass


def upsert_user(
    db: Session, username: str, password: str, role: UserRole | None, *, reset: bool
) -> tuple[User, bool]:
    """Create the user (or, with `reset`, set a new password and unblock). Commits."""
    try:
        username = TypeAdapter(Username).validate_python(username)
    except ValidationError:
        raise UserError("Username: 3-64 characters, letters, digits, '_', '.', '-'") from None
    problem = password_problem(password, get_settings().password_min_length, username)
    if problem:
        raise UserError(problem)

    user = db.scalars(select(User).where(User.username == username)).one_or_none()
    if user is None:
        user = User(
            username=username, password_hash=hash_password(password), role=role or UserRole.USER
        )
        db.add(user)
        db.flush()
        action = AuditAction.USER_CREATED
    elif not reset:
        raise UserError(f"User {username!r} already exists (use --reset to set a new password)")
    else:
        user.password_hash = hash_password(password)
        user.is_active = True
        if role is not None:
            user.role = role
        revoke_user_sessions(db, user.id)
        action = AuditAction.USER_UPDATED
    audit.record(
        db,
        action,
        user=None,
        username="(cli)",
        ip_address=None,
        target_type="user",
        target_id=user.id,
        details={"username": user.username, "role": user.role, "source": "cli"},
    )
    db.commit()
    return user, action is AuditAction.USER_CREATED


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise UserError("Passwords do not match")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--role", choices=[r.value for r in UserRole], default=None)
    parser.add_argument("--reset", action="store_true", help="existing user: new password")
    parser.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    parser.add_argument(
        "--if-no-users", action="store_true", help="do nothing if any user already exists"
    )
    args = parser.parse_args()

    if args.if_no_users:
        with get_session_factory()() as db:
            if db.scalar(select(func.count(User.id))):
                print("Users already exist, nothing to do")
                return 0
        print(f"No users yet: create the administrator {args.username!r}")
    try:
        password = _read_password(args.password_stdin)
        with get_session_factory()() as db:
            role = UserRole(args.role) if args.role else None
            user, created = upsert_user(db, args.username, password, role, reset=args.reset)
    except UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{'Created' if created else 'Updated'} user {user.username!r} (role: {user.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
