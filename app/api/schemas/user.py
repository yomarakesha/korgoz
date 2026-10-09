from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.security.types import UserRole

# Usernames are case-insensitive: stored and looked up in lower case.
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]
# The minimum length is a setting (PASSWORD_MIN_LENGTH) and is checked by the routes;
# the maximum only stops absurdly large request bodies.
Password = Annotated[str, Field(min_length=1, max_length=256)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    username: Username
    password: Password
    role: UserRole = UserRole.USER


class UserUpdate(BaseModel):
    """Only the fields that are sent change. A new password logs the user out everywhere."""

    role: UserRole | None = None
    is_active: bool | None = None
    password: Password | None = None


class LoginRequest(BaseModel):
    # Not `Username`: a malformed name is just a failed login, not a validation error.
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Password


class LoginResponse(BaseModel):
    user: UserRead
    # The same token is set as an HttpOnly cookie; scripts send it as `Bearer`.
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (OAuth2 token type, not a secret)
    expires_at: datetime


class PasswordChange(BaseModel):
    current_password: Password
    new_password: Password
