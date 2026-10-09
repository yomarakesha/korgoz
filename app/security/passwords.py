"""Password hashing with argon2id (argon2-cffi, MIT).

The hash string carries its own salt and cost parameters, so the parameters can be
raised later: old hashes still verify and are upgraded on the next login.
"""

from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Library defaults = RFC 9106 "low memory" profile (64 MiB, 3 passes), ~50 ms per hash.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("korgoz-dummy-password")


def burn_verification_time(password: str) -> None:
    """Spend as long as a real check: unknown usernames must not answer faster."""
    verify_password(_dummy_hash(), password)


def password_problem(password: str, min_length: int, username: str) -> str | None:
    """Minimal policy: long enough and not the username. The reason, or None if fine."""
    if len(password) < min_length:
        return f"Password must be at least {min_length} characters long"
    if password.strip().lower() == username.strip().lower():
        return "Password must differ from the username"
    return None
