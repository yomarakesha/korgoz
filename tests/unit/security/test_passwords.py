import pytest
from argon2 import PasswordHasher

from app.security import passwords
from app.security.passwords import (
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)


def test_hash_is_salted_argon2id_and_verifies() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2id$")
    assert first != second  # random salt
    assert "correct horse" not in first
    assert verify_password(first, "correct horse")
    assert not verify_password(first, "wrong horse")


def test_garbage_hash_is_a_failed_check_not_a_crash() -> None:
    assert not verify_password("not-a-hash", "x")
    assert not verify_password("", "x")


def test_weaker_hash_needs_rehash(monkeypatch: pytest.MonkeyPatch) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=64, parallelism=1).hash("pw")
    monkeypatch.setattr(passwords, "_hasher", PasswordHasher())
    assert needs_rehash(weak)
    assert verify_password(weak, "pw")  # old hashes keep working


def test_password_policy() -> None:
    assert password_problem("short", 10, "bob") == "Password must be at least 10 characters long"
    assert password_problem("Administrator", 10, "administrator") is not None
    assert password_problem("long enough pw", 10, "bob") is None
