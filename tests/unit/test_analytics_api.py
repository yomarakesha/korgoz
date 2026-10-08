from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine

from app.config import Settings, get_settings
from tests.unit.analytics.seed import seed, t


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


WINDOW = f"since={iso(t(9))}&until={iso(t(12))}"


@pytest.fixture
def api(api_client: Any, sqlite_engine: Engine) -> Any:
    seed(sqlite_engine)
    return api_client


def test_occupancy(api: Any) -> None:
    body = api.get(f"/analytics/occupancy?at={iso(t(9, 5, 30))}").json()
    assert body["total"] == 2
    assert body["cameras"] == [{"camera_id": 1, "name": "entrance", "count": 2}]
    assert api.get("/analytics/occupancy").json()["total"] == 0  # "now": nothing recent


def test_people_count_and_dwell_time(api: Any) -> None:
    count = api.get(f"/analytics/people-count?{WINDOW}").json()
    assert (count["visits"], count["recognized_persons"], count["unknown_visits"]) == (4, 2, 1)
    assert count["period"]["since"].startswith("2026-01-01T09:00:00")
    dwell = api.get(f"/analytics/dwell-time?{WINDOW}&camera_id=1").json()
    assert (dwell["sessions"], dwell["median_seconds"]) == (3, 600)


def test_people_flow_uses_the_requested_time_zone(api: Any) -> None:
    body = api.get(f"/analytics/people-flow?{WINDOW}&tz=Asia/Tashkent").json()
    assert body["timezone"] == "Asia/Tashkent"
    assert body["peak_hours"] == [14, 15, 16]
    assert body["buckets"][0] == {"hour": "2026-01-01T14:00:00+05:00", "entered": 2, "left": 2}


def test_default_time_zone_from_settings(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYTICS_TIMEZONE", "Europe/Moscow")
    get_settings.cache_clear()
    assert api.get(f"/analytics/people-flow?{WINDOW}").json()["peak_hours"][0] == 12


def test_repeat_visitors(api: Any) -> None:
    body = api.get(f"/analytics/repeat-visitors?{WINDOW}").json()
    assert [(v["person_id"], v["visits"]) for v in body] == [(1, 2)]
    assert api.get(f"/analytics/repeat-visitors?{WINDOW}&min_visits=1").status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        f"since={iso(t(12))}&until={iso(t(9))}",  # reversed
        "since=2024-01-01T00:00:00Z&until=2026-01-01T00:00:00Z",  # > 366 days
        "tz=Mars/Olympus",
    ],
)
def test_bad_parameters(api: Any, query: str) -> None:
    assert api.get(f"/analytics/people-flow?{query}").status_code == 422


def test_bad_timezone_setting_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError, match="Unknown IANA time zone"):
        Settings(_env_file=None, database_url="sqlite://", analytics_timezone="Nowhere/City")
