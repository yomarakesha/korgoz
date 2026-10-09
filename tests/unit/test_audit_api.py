from typing import Any


def test_changes_are_audited_without_secrets(api_client: Any) -> None:
    location = api_client.post("/locations", json={"name": "Hall"}).json()
    camera = api_client.post(
        "/cameras", json={"name": "door", "stream_url": "rtsp://u:topsecret@cam/1"}
    ).json()
    api_client.patch(f"/cameras/{camera['id']}", json={"enabled": False})
    api_client.delete(f"/cameras/{camera['id']}")
    api_client.delete(f"/locations/{location['id']}")
    api_client.post("/users", json={"username": "bob", "password": "bob-password-1"})
    bob = api_client.get("/users").json()[-1]["id"]
    api_client.patch(f"/users/{bob}", json={"password": "bob-password-2", "role": "admin"})

    entries = api_client.get("/audit").json()
    assert [e["action"] for e in entries] == [
        "USER_UPDATED",
        "USER_CREATED",
        "LOCATION_DELETED",
        "CAMERA_DELETED",
        "CAMERA_UPDATED",
        "CAMERA_CREATED",
        "LOCATION_CREATED",
        "LOGIN",
    ]  # newest first
    assert all(e["username"] == "admin" for e in entries)
    assert entries[0]["details"] == {"fields": ["password", "role"], "role": "admin"}
    assert entries[4]["details"] == {"enabled": False}
    assert entries[5]["target_type"] == "camera"
    assert entries[5]["details"] == {"name": "door"}
    text = str(entries)
    assert "topsecret" not in text
    assert "bob-password" not in text


def test_filters_and_paging(api_client: Any) -> None:
    for name in ("a", "b", "c"):
        api_client.post("/locations", json={"name": name})
    created = api_client.get("/audit", params={"action": "LOCATION_CREATED"}).json()
    assert [e["details"]["name"] for e in created] == ["c", "b", "a"]
    two = api_client.get("/audit", params={"action": "LOCATION_CREATED", "limit": 2, "offset": 1})
    assert [e["details"]["name"] for e in two.json()] == ["b", "a"]
    mine = api_client.get("/audit", params={"user_id": 1}).json()
    assert len(mine) == 4
    assert api_client.get("/audit", params={"user_id": 99}).json() == []
    assert api_client.get("/audit", params={"since": "2999-01-01T00:00:00Z"}).json() == []
    assert api_client.get("/audit", params={"action": "NOPE"}).status_code == 422
