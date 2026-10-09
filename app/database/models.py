"""SQLAlchemy ORM models (the persistent part of the Vision Ontology).

Face embedding vectors live in Qdrant; PostgreSQL only keeps a reference
(`FaceEmbedding.vector_id`) so a person's biometric data can be deleted in one place.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.camera.types import CameraStatus
from app.database.base import Base, JSONType, TimestampMixin
from app.events.types import EventType
from app.security.types import AuditAction, UserRole


class PersonStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _str_enum(enum_cls: type[StrEnum]) -> Enum:
    # VARCHAR + Python-side validation instead of a native PG ENUM:
    # new members can be added without an ALTER TYPE migration.
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    cameras: Mapped[list["Camera"]] = relationship(back_populates="location")


class Camera(TimestampMixin, Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    # May contain credentials: never log it or return it raw from the API.
    stream_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[CameraStatus] = mapped_column(
        _str_enum(CameraStatus), default=CameraStatus.UNKNOWN, server_default="unknown"
    )

    location: Mapped[Location | None] = relationship(back_populates="cameras")

    def __repr__(self) -> str:  # stream_url deliberately excluded
        return f"Camera(id={self.id!r}, name={self.name!r}, status={self.status!r})"


class Person(TimestampMixin, Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PersonStatus] = mapped_column(
        _str_enum(PersonStatus), default=PersonStatus.ACTIVE, server_default="active"
    )

    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True
    )


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    vector_id: Mapped[str] = mapped_column(String(64), unique=True)  # Qdrant point id
    model_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    person: Mapped[Person] = relationship(back_populates="embeddings")


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        Index("ix_tracks_camera_id_track_identifier", "camera_id", "track_identifier"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    # Tracker-local id (e.g. ByteTrack id). Not unique: trackers restart numbering.
    track_identifier: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_camera_id_timestamp", "camera_id", "timestamp"),
        Index("ix_events_person_id_timestamp", "person_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[EventType] = mapped_column(_str_enum(EventType), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    track_id: Mapped[int | None] = mapped_column(
        ForeignKey("tracks.id", ondelete="SET NULL"), index=True
    )
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    # Nullable: a camera may not be assigned to a location yet.
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    # `metadata` is reserved by SQLAlchemy's declarative API, hence the trailing underscore.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Read-only navigation for the ontology / timeline (no schema change).
    camera: Mapped[Camera] = relationship(viewonly=True)
    location: Mapped[Location | None] = relationship(viewonly=True)
    person: Mapped[Person | None] = relationship(viewonly=True)
    track: Mapped[Track | None] = relationship(viewonly=True)


class TrackSession(Base):
    """A continuous stay of one track in front of one camera (the spec's `Session`).

    Named `TrackSession` to avoid confusion with SQLAlchemy's `Session`.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)


class User(TimestampMixin, Base):
    """A dashboard / API account (not a tracked `Person`)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # argon2id hash with its own salt and parameters; never the password itself.
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        _str_enum(UserRole), default=UserRole.USER, server_default="user"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # password_hash deliberately excluded
        return f"User(id={self.id!r}, username={self.username!r}, role={self.role!r})"


class AuthSession(Base):
    """A login session. The cookie holds a random token; only its SHA-256 is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # SET NULL keeps the history after a user is deleted; `username` is a snapshot.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[AuditAction] = mapped_column(_str_enum(AuditAction), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None]
    ip_address: Mapped[str | None] = mapped_column(String(64))
    # Never credentials, stream URLs or biometric data.
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)


__all__ = [
    "AuditLog",
    "AuthSession",
    "Base",
    "Camera",
    "CameraStatus",
    "Event",
    "FaceEmbedding",
    "Location",
    "Person",
    "PersonStatus",
    "Track",
    "TrackSession",
    "User",
    "UserRole",
]
