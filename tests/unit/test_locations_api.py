from typing import Any


def test_location_crud_and_camera_assignment(api_client: Any) -> None:
    hall = api_client.post("/locations", json={"name": "Hall"}).json()
    assert hall == {"id": 1, "name": "Hall", "description": None}
    assert api_client.post("/locations", json={"name": "Hall"}).status_code == 409
    api_client.post("/locations", json={"name": "Atrium", "description": "1st floor"})
    assert [loc["name"] for loc in api_client.get("/locations").json()] == ["Atrium", "Hall"]

    camera = api_client.post("/cameras", json={"name": "cam", "stream_url": "0"}).json()
    moved = api_client.patch(f"/cameras/{camera['id']}", json={"location_id": hall["id"]}).json()
    assert moved["location_id"] == hall["id"]

    assert api_client.delete(f"/locations/{hall['id']}").status_code == 204
    assert api_client.get(f"/cameras/{camera['id']}").json()["location_id"] is None
    assert api_client.delete("/locations/99").status_code == 404


def test_camera_patch(api_client: Any) -> None:
    camera = api_client.post("/cameras", json={"name": "cam", "stream_url": "0"}).json()
    url = f"/cameras/{camera['id']}"
    body = api_client.patch(url, json={"name": "front door", "enabled": False}).json()
    assert (body["name"], body["enabled"]) == ("front door", False)
    # Not sent = unchanged; null name is ignored, null location clears it.
    body = api_client.patch(url, json={"name": None}).json()
    assert body["name"] == "front door"
    assert api_client.patch(url, json={"location_id": 42}).status_code == 422
    assert api_client.patch(url, json={"name": ""}).status_code == 422
    assert api_client.patch("/cameras/99", json={"name": "x"}).status_code == 404
