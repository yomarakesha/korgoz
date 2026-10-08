"""Analytics over stored data only (tracks, sessions, events): video is never re-analysed.

Metrics (spec §18):
- occupancy — tracks visible at a moment (now by default), per camera;
- people_count — visits (tracks started) and distinct recognised persons in a period;
- dwell_time — stay durations from `sessions`;
- people_flow — PERSON_ENTERED / PERSON_LEFT per hour, plus peak hours of the day;
- repeat_appearance — recognised persons with several visits in a period.

Hours are bucketed in a configurable IANA time zone, so "peak at 14:00" is local
time. PostgreSQL does it in SQL (`date_trunc` + `AT TIME ZONE`, DST-correct);
SQLite, used only by tests, shifts by the zone's current UTC offset.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, literal, or_, select
from sqlalchemy.orm import Session

from app.database.models import Camera, Event, Person, Track, TrackSession
from app.events.types import EventType


@dataclass(frozen=True)
class Period:
    since: datetime
    until: datetime

    def __post_init__(self) -> None:
        if self.since >= self.until:
            raise ValueError("since must be before until")


@dataclass(frozen=True)
class Scope:
    """Optional filters shared by all metrics."""

    camera_id: int | None = None
    location_id: int | None = None


EVERYWHERE = Scope()


@dataclass(frozen=True)
class CameraOccupancy:
    camera_id: int
    name: str
    count: int


@dataclass(frozen=True)
class Occupancy:
    at: datetime
    total: int
    cameras: list[CameraOccupancy]


@dataclass(frozen=True)
class PeopleCount:
    visits: int  # tracks started in the period (a broken track counts twice)
    recognized_persons: int  # distinct registered persons recognised
    unknown_visits: int  # tracks that ended up PERSON_UNKNOWN


@dataclass(frozen=True)
class DwellTime:
    sessions: int
    average_seconds: float | None
    median_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None


@dataclass(frozen=True)
class FlowBucket:
    hour: datetime  # start of the hour, in the requested time zone
    entered: int = 0
    left: int = 0


@dataclass(frozen=True)
class PeopleFlow:
    timezone: str
    buckets: list[FlowBucket]
    peak_hours: list[int] = field(default_factory=list)  # hours of day, busiest first


@dataclass(frozen=True)
class RepeatVisitor:
    person_id: int
    name: str
    visits: int
    first_seen: datetime
    last_seen: datetime


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes (stored as UTC); PostgreSQL returns aware ones."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AnalyticsService:
    def __init__(self, session: Session, timezone: str = "UTC") -> None:
        self.session = session
        self.timezone = timezone
        self._zone = ZoneInfo(timezone)  # raises ZoneInfoNotFoundError for bad names
        self._dialect = session.get_bind().dialect.name

    # --- filters -----------------------------------------------------------------

    def _camera_filter(self, camera_column: Any, scope: Scope) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if scope.camera_id is not None:
            conditions.append(camera_column == scope.camera_id)
        if scope.location_id is not None:
            in_location = select(Camera.id).where(Camera.location_id == scope.location_id)
            conditions.append(camera_column.in_(in_location))
        return conditions

    # --- occupancy -----------------------------------------------------------------

    def occupancy(
        self, at: datetime, scope: Scope = EVERYWHERE, *, stale_after: timedelta
    ) -> Occupancy:
        """Tracks visible at `at`.

        An open track counts only if it was seen within `stale_after` before `at`:
        a crashed worker leaves tracks open, and they must not count forever.
        """
        visible = and_(
            Track.started_at <= at,
            or_(
                and_(Track.ended_at.is_not(None), Track.ended_at >= at),
                and_(Track.ended_at.is_(None), Track.last_seen_at >= at - stale_after),
            ),
        )
        query = (
            select(Camera.id, Camera.name, func.count(Track.id))
            .join(Track, Track.camera_id == Camera.id)
            .where(visible, *self._camera_filter(Camera.id, scope))
            .group_by(Camera.id, Camera.name)
            .order_by(Camera.id)
        )
        cameras = [
            CameraOccupancy(cid, name, count) for cid, name, count in self.session.execute(query)
        ]
        return Occupancy(at=at, total=sum(c.count for c in cameras), cameras=cameras)

    # --- people count ----------------------------------------------------------------

    def people_count(self, period: Period, scope: Scope = EVERYWHERE) -> PeopleCount:
        visits = self.session.scalar(
            select(func.count(Track.id)).where(
                Track.started_at >= period.since,
                Track.started_at < period.until,
                *self._camera_filter(Track.camera_id, scope),
            )
        )
        in_period = self._event_filter(period, scope)
        recognized = self.session.scalar(
            select(func.count(func.distinct(Event.person_id))).where(
                Event.event_type == EventType.PERSON_RECOGNIZED, *in_period
            )
        )
        unknown = self.session.scalar(
            select(func.count(Event.id)).where(
                Event.event_type == EventType.PERSON_UNKNOWN, *in_period
            )
        )
        return PeopleCount(
            visits=visits or 0, recognized_persons=recognized or 0, unknown_visits=unknown or 0
        )

    def _event_filter(self, period: Period, scope: Scope) -> list[ColumnElement[bool]]:
        conditions = [Event.timestamp >= period.since, Event.timestamp < period.until]
        if scope.camera_id is not None:
            conditions.append(Event.camera_id == scope.camera_id)
        if scope.location_id is not None:
            # Where the camera was when the event happened.
            conditions.append(Event.location_id == scope.location_id)
        return conditions

    # --- dwell time --------------------------------------------------------------------

    def dwell_time(self, period: Period, scope: Scope = EVERYWHERE) -> DwellTime:
        """Sessions that ended in the period (a stay is complete only once it ended)."""
        conditions = [
            TrackSession.ended_at >= period.since,
            TrackSession.ended_at < period.until,
            TrackSession.duration_seconds.is_not(None),
            *self._camera_filter(TrackSession.camera_id, scope),
        ]
        duration = TrackSession.duration_seconds
        count, average, low, high = self.session.execute(
            select(func.count(), func.avg(duration), func.min(duration), func.max(duration)).where(
                *conditions
            )
        ).one()
        if not count:
            return DwellTime(0, None, None, None, None)
        if self._dialect == "postgresql":
            middle = self.session.scalar(
                select(func.percentile_cont(0.5).within_group(duration)).where(*conditions)
            )
        else:  # SQLite has no percentile function
            durations = self.session.scalars(select(duration).where(*conditions))
            middle = median(d for d in durations if d is not None)
        return DwellTime(
            sessions=count,
            average_seconds=_round(average),
            median_seconds=_round(middle),
            min_seconds=_round(low),
            max_seconds=_round(high),
        )

    # --- people flow -------------------------------------------------------------------

    def _local_hour(self, column: Any) -> Any:
        """SQL expression: start of the hour of `column`, as local wall-clock time."""
        if self._dialect == "postgresql":
            return func.date_trunc("hour", func.timezone(self.timezone, column))
        offset = datetime.now(self._zone).utcoffset() or timedelta()
        minutes = int(offset.total_seconds() // 60)
        return func.strftime("%Y-%m-%d %H:00:00", column, literal(f"{minutes:+d} minutes"))

    def _to_local(self, value: datetime | str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.replace(tzinfo=self._zone)

    def people_flow(self, period: Period, scope: Scope = EVERYWHERE) -> PeopleFlow:
        hour = self._local_hour(Event.timestamp).label("hour")
        query = (
            select(hour, Event.event_type, func.count())
            .where(
                Event.event_type.in_([EventType.PERSON_ENTERED, EventType.PERSON_LEFT]),
                *self._event_filter(period, scope),
            )
            .group_by(hour, Event.event_type)
        )
        counts: dict[datetime, Counter[EventType]] = {}
        for bucket, event_type, count in self.session.execute(query):
            counts.setdefault(self._to_local(bucket), Counter())[event_type] = count

        buckets = []
        for start in self._hours(period):
            seen = counts.get(start, Counter())
            buckets.append(
                FlowBucket(start, seen[EventType.PERSON_ENTERED], seen[EventType.PERSON_LEFT])
            )
        return PeopleFlow(self.timezone, buckets, _peak_hours(buckets))

    def _hours(self, period: Period) -> list[datetime]:
        """Every local hour that overlaps the period (empty hours included, for charts)."""
        start = period.since.astimezone(self._zone).replace(minute=0, second=0, microsecond=0)
        hours = []
        current = start.astimezone(UTC)  # step in UTC: local days can have 23 or 25 hours
        while current < period.until:
            hours.append(current.astimezone(self._zone))
            current += timedelta(hours=1)
        return hours

    # --- repeat appearance -----------------------------------------------------------

    def repeat_visitors(
        self, period: Period, scope: Scope = EVERYWHERE, *, min_visits: int = 2
    ) -> list[RepeatVisitor]:
        """Recognised persons seen on >= `min_visits` different tracks, most frequent first."""

        visits = func.count(func.distinct(Event.track_id))
        query = (
            select(
                Person.id,
                Person.name,
                visits,
                func.min(Event.timestamp),
                func.max(Event.timestamp),
            )
            .join(Person, Person.id == Event.person_id)
            .where(
                Event.event_type == EventType.PERSON_RECOGNIZED,
                *self._event_filter(period, scope),
            )
            .group_by(Person.id, Person.name)
            .having(visits >= min_visits)
            .order_by(visits.desc(), Person.id)
        )
        return [
            RepeatVisitor(pid, name, count, as_utc(first), as_utc(last))
            for pid, name, count, first, last in self.session.execute(query)
        ]


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _peak_hours(buckets: Sequence[FlowBucket], top: int = 3) -> list[int]:
    by_hour: Counter[int] = Counter()
    for bucket in buckets:
        by_hour[bucket.hour.hour] += bucket.entered
    return [hour for hour, count in by_hour.most_common(top) if count > 0]
