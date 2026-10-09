from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import AuditLog, User
from app.main import create_app
from app.security.types import AuditAction
from tests.conftest import ADMIN_PASSWORD, add_user, login

# Reachable without logging in.
PUBLIC = {("GET", "/health"), ("POST", "/auth/login")}


def audit_actions(engine: Engine) -> list[AuditAction]:
    with Session(engine) as session:
        return list(session.scalars(select(AuditLog.action).order_by(AuditLog.id)))


def all_operations() -> list[tuple[str, str]]:
    paths = create_app().openapi()["paths"]
    operations: list[tuple[str, str]] = []
    for path, methods in paths.items():
        url = "/".join("1" if p.startswith("{") else p for p in path.split("/"))
        operations.extend((method.upper(), url) for method in methods)
    return sorted(operations)


def test_every_api_route_requires_login_except_public_ones(anonymous_client: Any) -> None:
    operations = all_operations()
    assert len(operations) > 30
    for method, url in operations:
        status = anonymous_client.request(method, url).status_code
        if (method, url) in PUBLIC:
            assert status != 401, (method, url)
        else:
            assert status == 401, (method, url, status)


def test_read_only_user_can_read_but_not_change(
    anonymous_client: Any, sqlite_engine: Engine
) -> None:
    add_user(sqlite_engine, "viewer", "viewer-password")
    login(anonymous_client, "viewer", "viewer-password")
    for method, url in all_operations():
        if (method, url) in PUBLIC or url.startswith("/auth"):
            continue
        status = anonymous_client.request(method, url).status_code
        admin_only = method != "GET" or url.startswith(("/users", "/audit"))
        if admin_only:
            assert status == 403, (method, url, status)
        else:
            assert status not in (401, 403), (method, url, status)


def test_login_sets_hardened_cookie_and_me_works(
    anonymous_client: Any, sqlite_engine: Engine
) -> None:
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    response = login(anonymous_client, "Admin ", ADMIN_PASSWORD)  # case/space-insensitive
    body = response.json()
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"
    assert "password" not in str(body["user"])
    cookie = response.headers["set-cookie"].lower()
    for flag in ("korgoz_session=", "httponly", "samesite=strict", "path=/", "max-age=43200"):
        assert flag in cookie
    assert "secure" not in cookie  # AUTH_COOKIE_SECURE is off by default
    assert anonymous_client.get("/auth/me").json()["username"] == "admin"
    assert audit_actions(sqlite_engine) == [AuditAction.LOGIN]
    with Session(sqlite_engine) as session:
        assert session.scalars(select(User)).one().last_login_at is not None


def test_secure_cookie_flag(
    anonymous_client: Any, sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    response = anonymous_client.post(
        "/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert "secure" in response.headers["set-cookie"].lower()


def test_bearer_token_works_without_cookie(anonymous_client: Any, sqlite_engine: Engine) -> None:
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    token = login(anonymous_client, "admin", ADMIN_PASSWORD).json()["access_token"]
    anonymous_client.cookies.clear()
    assert anonymous_client.get("/cameras").status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert anonymous_client.get("/cameras", headers=headers).status_code == 200
    assert (
        anonymous_client.get("/cameras", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin", "wrong-password"), ("ghost", ADMIN_PASSWORD), ("blocked", "blocked-password")],
)
def test_failed_logins_look_the_same_and_are_audited(
    anonymous_client: Any, sqlite_engine: Engine, username: str, password: str
) -> None:
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    blocked = add_user(sqlite_engine, "blocked", "blocked-password")
    with Session(sqlite_engine) as session:
        session.get_one(User, blocked).is_active = False
        session.commit()
    response = anonymous_client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert "set-cookie" not in response.headers
    with Session(sqlite_engine) as session:
        entry = session.scalars(select(AuditLog)).one()
    assert entry.action is AuditAction.LOGIN_FAILED
    assert entry.username == username
    assert password not in str(entry.details)


def test_brute_force_is_locked_out_only_from_the_attackers_address(
    anonymous_client: Any, sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTH_MAX_FAILED_LOGINS", "3")
    get_settings.cache_clear()
    app = anonymous_client.app
    attacker = TestClient(app, client=("10.0.0.66", 4000))
    owner = TestClient(app, client=("10.0.0.1", 4000))
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    bad = {"username": "admin", "password": "guess"}
    good = {"username": "admin", "password": ADMIN_PASSWORD}
    assert [attacker.post("/auth/login", json=bad).status_code for _ in range(3)] == [401] * 3
    locked = attacker.post("/auth/login", json=good)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    # The real admin, from another address, is not locked out.
    assert owner.post("/auth/login", json=good).status_code == 200


def test_one_address_cannot_spray_many_usernames(
    anonymous_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_MAX_FAILED_LOGINS", "2")
    get_settings.cache_clear()
    statuses = [
        anonymous_client.post(
            "/auth/login", json={"username": f"u{i}", "password": "x"}
        ).status_code
        for i in range(9)
    ]
    assert statuses == [401] * 8 + [429]  # 2 per username, 2 * 4 per address


def test_current_password_guessing_is_limited(
    anonymous_client: Any, sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_MAX_FAILED_LOGINS", "2")
    get_settings.cache_clear()
    add_user(sqlite_engine, "bob", "bob-password-1")
    login(anonymous_client, "bob", "bob-password-1")
    guess = {"current_password": "guess", "new_password": "bob-password-2"}
    codes = [anonymous_client.post("/auth/password", json=guess).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_logout_revokes_the_session(anonymous_client: Any, sqlite_engine: Engine) -> None:
    add_user(sqlite_engine, "admin", ADMIN_PASSWORD, role="admin")
    token = login(anonymous_client, "admin", ADMIN_PASSWORD).json()["access_token"]
    response = anonymous_client.post("/auth/logout")
    assert response.status_code == 204
    assert 'korgoz_session=""' in response.headers["set-cookie"]
    headers = {"Authorization": f"Bearer {token}"}  # the old token is dead server-side too
    assert anonymous_client.get("/auth/me", headers=headers).status_code == 401
    assert audit_actions(sqlite_engine)[-1] is AuditAction.LOGOUT


def test_change_own_password_logs_out_other_sessions(
    anonymous_client: Any, sqlite_engine: Engine
) -> None:
    add_user(sqlite_engine, "bob", "bob-password-1")
    other = login(anonymous_client, "bob", "bob-password-1").json()["access_token"]
    login(anonymous_client, "bob", "bob-password-1")  # current session (cookie)
    change = {"current_password": "wrong", "new_password": "bob-password-2"}
    assert anonymous_client.post("/auth/password", json=change).status_code == 400
    change["current_password"] = "bob-password-1"
    change["new_password"] = "short"
    assert anonymous_client.post("/auth/password", json=change).status_code == 422
    change["new_password"] = "bob-password-2"
    assert anonymous_client.post("/auth/password", json=change).status_code == 204
    assert anonymous_client.get("/auth/me").status_code == 200  # current session kept
    stale = {"Authorization": f"Bearer {other}"}
    assert anonymous_client.get("/auth/me", headers=stale).status_code == 401
    anonymous_client.cookies.clear()
    login(anonymous_client, "bob", "bob-password-2")


def test_security_headers(anonymous_client: Any) -> None:
    headers = anonymous_client.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"
