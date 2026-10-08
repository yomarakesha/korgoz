from datetime import timedelta
from zoneinfo import ZoneInfoNotFoundError

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService, Period, Scope
from tests.unit.analytics.seed import seed, t

PERIOD = Period(t(9), t(12))
STALE = timedelta(seconds=13)


@pytest.fixture
def db(sqlite_engine: Engine) -> Session:
    seed(sqlite_engine)
    return Session(sqlite_engine)


def test_period_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="before"):
        Period(t(10), t(9))


def test_occupancy_at_moments(db: Session) -> None:
    service = AnalyticsService(db)
    busy = service.occupancy(t(9, 5, 30), stale_after=STALE)
    assert busy.total == 2
    assert [(c.camera_id, c.name, c.count) for c in busy.cameras] == [(1, "entrance", 2)]
    # Open track, last seen 1 s ago: still in view.
    assert service.occupancy(t(10, 59, 59), stale_after=STALE).total == 1
    # Open track not refreshed for an hour (crashed worker): not counted.
    assert service.occupancy(t(12), stale_after=STALE).total == 0


def test_occupancy_scope(db: Session) -> None:
    service = AnalyticsService(db)
    assert service.occupancy(t(10, 59, 59), Scope(camera_id=1), stale_after=STALE).total == 0
    assert service.occupancy(t(9, 5, 30), Scope(location_id=1), stale_after=STALE).total == 2


def test_people_count(db: Session) -> None:
    service = AnalyticsService(db)
    count = service.people_count(PERIOD)
    assert (count.visits, count.recognized_persons, count.unknown_visits) == (4, 2, 1)
    yard = service.people_count(PERIOD, Scope(camera_id=2))
    assert (yard.visits, yard.recognized_persons, yard.unknown_visits) == (1, 0, 1)
    morning = service.people_count(Period(t(9), t(10)))
    assert (morning.visits, morning.recognized_persons) == (2, 2)


def test_dwell_time(db: Session) -> None:
    dwell = AnalyticsService(db).dwell_time(PERIOD)
    assert dwell.sessions == 3  # the open track has no finished session yet
    assert dwell.average_seconds == 820  # (600 + 60 + 1800) / 3
    assert dwell.median_seconds == 600
    assert (dwell.min_seconds, dwell.max_seconds) == (60, 1800)


def test_dwell_time_without_data(db: Session) -> None:
    dwell = AnalyticsService(db).dwell_time(Period(t(20), t(21)))
    assert dwell.sessions == 0
    assert dwell.average_seconds is None


def test_people_flow_per_hour_with_empty_hours(db: Session) -> None:
    flow = AnalyticsService(db).people_flow(Period(t(8), t(12)))
    assert [(b.hour.hour, b.entered, b.left) for b in flow.buckets] == [
        (8, 0, 0),
        (9, 2, 2),
        (10, 1, 0),
        (11, 1, 1),
    ]
    assert flow.peak_hours == [9, 10, 11]
    assert flow.timezone == "UTC"


def test_people_flow_in_local_time(db: Session) -> None:
    flow = AnalyticsService(db, "Asia/Tashkent").people_flow(PERIOD)  # UTC+5
    assert [(b.hour.hour, b.entered) for b in flow.buckets] == [(14, 2), (15, 1), (16, 1)]
    assert flow.buckets[0].hour.utcoffset() == timedelta(hours=5)
    assert flow.peak_hours[0] == 14


def test_repeat_visitors(db: Session) -> None:
    service = AnalyticsService(db)
    visitors = service.repeat_visitors(PERIOD)
    assert [(v.person_id, v.name, v.visits) for v in visitors] == [(1, "Alice", 2)]
    assert visitors[0].first_seen == t(9, 0, 2)
    assert visitors[0].last_seen == t(11, 0, 2)
    assert service.repeat_visitors(PERIOD, min_visits=3) == []


def test_unknown_timezone() -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        AnalyticsService(Session(), "Mars/Olympus")
