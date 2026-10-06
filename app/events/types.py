"""Event types produced by the Event Engine.

Stored in the database as plain strings (not a PostgreSQL ENUM), so adding a
new member here does not require a schema migration.
"""

from enum import StrEnum


class EventType(StrEnum):
    PERSON_DETECTED = "PERSON_DETECTED"
    PERSON_ENTERED = "PERSON_ENTERED"
    PERSON_LEFT = "PERSON_LEFT"
    PERSON_RECOGNIZED = "PERSON_RECOGNIZED"
    PERSON_UNKNOWN = "PERSON_UNKNOWN"
    TRACK_STARTED = "TRACK_STARTED"
    TRACK_ENDED = "TRACK_ENDED"
    CAMERA_ONLINE = "CAMERA_ONLINE"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
