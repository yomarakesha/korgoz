from datetime import datetime

from pydantic import BaseModel


class PeriodRead(BaseModel):
    since: datetime
    until: datetime


class CameraOccupancyRead(BaseModel):
    camera_id: int
    name: str
    count: int


class OccupancyRead(BaseModel):
    at: datetime
    total: int  # people visible at `at` (active tracks)
    cameras: list[CameraOccupancyRead]


class PeopleCountRead(BaseModel):
    period: PeriodRead
    visits: int
    recognized_persons: int
    unknown_visits: int


class DwellTimeRead(BaseModel):
    period: PeriodRead
    sessions: int
    average_seconds: float | None
    median_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None


class FlowBucketRead(BaseModel):
    hour: datetime
    entered: int
    left: int


class PeopleFlowRead(BaseModel):
    period: PeriodRead
    timezone: str
    peak_hours: list[int]  # local hours of day (0-23) with most entries, busiest first
    buckets: list[FlowBucketRead]


class RepeatVisitorRead(BaseModel):
    person_id: int
    name: str
    visits: int
    first_seen: datetime
    last_seen: datetime
