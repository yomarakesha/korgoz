"""PostgreSQL-only SQL paths of analytics: date_trunc + time zone, percentile_cont."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService, Period
from tests.unit.analytics.seed import seed, t

pytestmark = pytest.mark.integration


@pytest.fixture
def db(migrated_url: str) -> Iterator[Session]:
    engine = create_engine(migrated_url)
    seed(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_flow_buckets_in_local_time(db: Session) -> None:
    flow = AnalyticsService(db, "Asia/Tashkent").people_flow(Period(t(9), t(12)))
    assert [(b.hour.hour, b.entered, b.left) for b in flow.buckets] == [
        (14, 2, 2),
        (15, 1, 0),
        (16, 1, 1),
    ]
    assert flow.peak_hours == [14, 15, 16]


def test_flow_with_a_half_hour_zone(db: Session) -> None:
    # India is UTC+5:30: 09:05 UTC is 14:35 local, so hours start at :30 UTC.
    flow = AnalyticsService(db, "Asia/Kolkata").people_flow(Period(t(9), t(10)))
    assert [(b.hour.hour, b.hour.minute) for b in flow.buckets] == [(14, 0), (15, 0)]
    assert sum(b.entered for b in flow.buckets) == 2
    assert flow.buckets[0].hour.utcoffset() == timedelta(hours=5, minutes=30)


def test_dwell_median_and_other_metrics(db: Session) -> None:
    service = AnalyticsService(db)
    period = Period(t(9), t(12))
    dwell = service.dwell_time(period)
    assert (dwell.sessions, dwell.average_seconds, dwell.median_seconds) == (3, 820, 600)
    count = service.people_count(period)
    assert (count.visits, count.recognized_persons, count.unknown_visits) == (4, 2, 1)
    assert [v.visits for v in service.repeat_visitors(period)] == [2]
    assert service.occupancy(t(9, 5, 30), stale_after=timedelta(seconds=13)).total == 2
