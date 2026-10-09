"""User management (admin only; enforced where the router is included)."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.auth import AdminUser, AuditDep, check_new_password
from app.api.dependencies import DbSession, SettingsDep
from app.api.schemas.user import UserCreate, UserRead, UserUpdate
from app.database.models import User
from app.security.passwords import hash_password
from app.security.sessions import revoke_user_sessions
from app.security.types import AuditAction

router = APIRouter(prefix="/users", tags=["users"])


def _get_or_404(db: DbSession, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("", response_model=list[UserRead])
def list_users(db: DbSession) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, db: DbSession, settings: SettingsDep, record: AuditDep
) -> User:
    if db.scalar(select(User.id).where(User.username == payload.username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    check_new_password(payload.password, settings.password_min_length, payload.username)
    user = User(
        username=payload.username, password_hash=hash_password(payload.password), role=payload.role
    )
    db.add(user)
    db.flush()
    record(AuditAction.USER_CREATED, "user", user.id, username=user.username, role=user.role)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: AdminUser,
    db: DbSession,
    settings: SettingsDep,
    record: AuditDep,
) -> User:
    """Change role, block/unblock or reset the password.

    An admin cannot demote or block themselves, so at least one admin always remains.
    """
    user = _get_or_404(db, user_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if user.id == admin.id and ("role" in changes or "is_active" in changes):
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own role or status")
    if "password" in changes:
        check_new_password(changes["password"], settings.password_min_length, user.username)
        user.password_hash = hash_password(changes["password"])
    if "role" in changes:
        user.role = changes["role"]
    if "is_active" in changes:
        user.is_active = changes["is_active"]
    if "password" in changes or changes.get("is_active") is False:
        revoke_user_sessions(db, user.id)
    # Field names only: the password itself never goes to the audit log.
    record(
        AuditAction.USER_UPDATED,
        "user",
        user.id,
        fields=sorted(changes),
        **{k: v for k, v in changes.items() if k != "password"},
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: AdminUser, db: DbSession, record: AuditDep) -> None:
    """Delete the account. Its audit entries stay (with the username snapshot)."""
    user = _get_or_404(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete yourself")
    record(AuditAction.USER_DELETED, "user", user.id, username=user.username)
    db.delete(user)
    db.commit()
