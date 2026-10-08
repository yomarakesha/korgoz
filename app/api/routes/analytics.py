"""Analytics endpoints. Every period defaults to the last 24 hours."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analytics.service import AnalyticsService, Period, Scope
from app.api.dependencies import DbSession, SettingsDep
from app.api.schemas.analytics import (
    DwellTimeRead,
    FlowBucketRead,
    OccupancyRead,
    PeopleCountRead,
    PeopleFlowRead,
    PeriodRead,
    RepeatVisitorRead,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

MAX_PERIOD = timedelta(days=366)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def get_period(
    since: Annotated[datetime | None, Query(description="default: until - 24h")] = None,
    until: Annotated[datetime | None, Query(description="default: now")] = None,
) -> Period:
    end = _aware(until) if until else datetime.now(UTC)
    start = _aware(since) if since else end - timedelta(hours=24)
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "since must be before until")
    if end - start > MAX_PERIOD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Period is longer than 366 days")
    return Period(start, end)


def get_scope(camera_id: int | None = None, location_id: int | None = None) -> Scope:
    return Scope(camera_id=camera_id, location_id=location_id)


def get_service(
    db: DbSession,
    settings: SettingsDep,
    tz: Annotated[str | None, Query(description="IANA zone, default ANALYTICS_TIMEZONE")] = None,
) -> AnalyticsService:
    try:
        return AnalyticsService(db, tz or settings.analytics_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown time zone: {tz}"
        ) from None


PeriodDep = Annotated[Period, Depends(get_period)]
ScopeDep = Annotated[Scope, Depends(get_scope)]
ServiceDep = Annotated[AnalyticsService, Depends(get_service)]


def _period(period: Period) -> PeriodRead:
    return PeriodRead(since=period.since, until=period.until)


@router.get("/occupancy", response_model=OccupancyRead)
def occupancy(
    service: ServiceDep,
    scope: ScopeDep,
    settings: SettingsDep,
    at: Annotated[datetime | None, Query(description="default: now")] = None,
) -> OccupancyRead:
    """How many people are in view now (or at `at`), per camera."""
    # An open track whose last-seen time wasn't refreshed for this long is
    # considered abandoned (e.g. the worker crashed).
    stale_after = timedelta(
        seconds=2 * settings.track_flush_interval_seconds + settings.track_max_lost_seconds
    )
    result = service.occupancy(
        _aware(at) if at else datetime.now(UTC), scope, stale_after=stale_after
    )
    return OccupancyRead.model_validate(asdict(result))


@router.get("/people-count", response_model=PeopleCountRead)
def people_count(service: ServiceDep, period: PeriodDep, scope: ScopeDep) -> PeopleCountRead:
    """Visits (tracks), distinct recognised persons and unknown visits in the period."""
    result = service.people_count(period, scope)
    return PeopleCountRead(period=_period(period), **asdict(result))


@router.get("/dwell-time", response_model=DwellTimeRead)
def dwell_time(service: ServiceDep, period: PeriodDep, scope: ScopeDep) -> DwellTimeRead:
    """How long people stay in view: sessions that ended in the period."""
    result = service.dwell_time(period, scope)
    return DwellTimeRead(period=_period(period), **asdict(result))


@router.get("/people-flow", response_model=PeopleFlowRead)
def people_flow(service: ServiceDep, period: PeriodDep, scope: ScopeDep) -> PeopleFlowRead:
    """Entries and exits per hour (local time zone) and the peak hours."""
    result = service.people_flow(period, scope)
    return PeopleFlowRead(
        period=_period(period),
        timezone=result.timezone,
        peak_hours=result.peak_hours,
        buckets=[FlowBucketRead(**asdict(b)) for b in result.buckets],
    )


@router.get("/repeat-visitors", response_model=list[RepeatVisitorRead])
def repeat_visitors(
    service: ServiceDep,
    period: PeriodDep,
    scope: ScopeDep,
    min_visits: Annotated[int, Query(ge=2, le=1000)] = 2,
) -> list[RepeatVisitorRead]:
    """Registered persons recognised on several visits (repeat appearance)."""
    return [
        RepeatVisitorRead.model_validate(asdict(v))
        for v in service.repeat_visitors(period, scope, min_visits=min_visits)
    ]
