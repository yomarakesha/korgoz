from typing import Any

from sqlalchemy import Engine

from tests.conftest import login


def create(
    client: Any, username: str, password: str = "user-password-1", role: str = "user"
) -> Any:
    return client.post("/users", json={"username": username, "password": password, "role": role})


def test_create_list_and_validate(api_client: Any) -> None:
    response = create(api_client, " Alice ")
    assert response.status_code == 201
    alice = response.json()
    assert (alice["username"], alice["role"], alice["is_active"]) == ("alice", "user", True)
    assert "password" not in str(alice)
    assert create(api_client, "ALICE").status_code == 409
    assert create(api_client, "bob", password="short").status_code == 422
    assert create(api_client, "bob-password", password="Bob-Password").status_code == 422
    assert create(api_client, "no spaces").status_code == 422
    assert create(api_client, "x").status_code == 422
    assert [u["username"] for u in api_client.get("/users").json()] == ["admin", "alice"]


def test_admin_resets_password_and_blocks_user(
    api_client: Any, anonymous_client_factory: Any
) -> None:
    alice_id = create(api_client, "alice").json()["id"]
    alice = anonymous_client_factory()
    login(alice, "alice", "user-password-1")

    reset = api_client.patch(f"/users/{alice_id}", json={"password": "new-password-1"})
    assert reset.status_code == 200
    assert alice.get("/auth/me").status_code == 401  # logged out everywhere
    login(alice, "alice", "new-password-1")

    body = api_client.patch(f"/users/{alice_id}", json={"is_active": False}).json()
    assert body["is_active"] is False
    assert alice.get("/auth/me").status_code == 401
    blocked = alice.post("/auth/login", json={"username": "alice", "password": "new-password-1"})
    assert blocked.status_code == 401

    api_client.patch(f"/users/{alice_id}", json={"is_active": True, "role": "admin"})
    login(alice, "alice", "new-password-1")
    assert alice.get("/users").status_code == 200  # the role applies immediately


def test_admin_cannot_lock_themselves_out(api_client: Any) -> None:
    me = api_client.get("/auth/me").json()["id"]
    assert api_client.patch(f"/users/{me}", json={"role": "user"}).status_code == 409
    assert api_client.patch(f"/users/{me}", json={"is_active": False}).status_code == 409
    assert api_client.delete(f"/users/{me}").status_code == 409
    assert api_client.patch(f"/users/{me}", json={"password": "another-pass-1"}).status_code == 200


def test_delete_user_keeps_their_audit_entries(api_client: Any, sqlite_engine: Engine) -> None:
    bob_id = create(api_client, "bob").json()["id"]
    assert api_client.delete(f"/users/{bob_id}").status_code == 204
    assert api_client.delete(f"/users/{bob_id}").status_code == 404
    assert api_client.patch(f"/users/{bob_id}", json={"role": "admin"}).status_code == 404
    entries = api_client.get("/audit", params={"action": "USER_CREATED"}).json()
    assert entries[0]["target_id"] == bob_id
    assert entries[0]["details"] == {"username": "bob", "role": "user"}
