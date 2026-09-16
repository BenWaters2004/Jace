from __future__ import annotations

# JACE_STEP4C4A_UNIFIED_CALENDAR_MODELS

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jace.db.models import Base, new_id, utc_now


class CalendarSource(Base):
    __tablename__ = "calendar_sources"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "connection_id", "external_calendar_id",
            name="uq_calendar_source_external_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    external_calendar_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    account_hint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    color: Mapped[str] = mapped_column(String(32), nullable=False, default="#7c8cff")
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="Europe/London")
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sync_status: Mapped[str] = mapped_column(String(30), nullable=False, default="local", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    events: Mapped[list["CalendarEvent"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
    sync_state: Mapped["CalendarSyncState | None"] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id", name="uq_calendar_event_external_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )

    external_event_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_series_id: Mapped[str | None] = mapped_column(String(1000), nullable=True, index=True)
    original_event_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ical_uid: Mapped[str | None] = mapped_column(String(1000), nullable=True, index=True)
    external_version: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    title: Mapped[str] = mapped_column(String(1000), nullable=False, default="Untitled event")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    end_date_exclusive: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="Europe/London")

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmed", index=True)
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="busy")
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="default")

    organizer_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    attendees_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reminders_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recurrence_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurrence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_by: Mapped[str] = mapped_column(String(30), nullable=False, default="user", index=True)
    sync_state: Mapped[str] = mapped_column(String(30), nullable=False, default="local", index=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    source: Mapped["CalendarSource"] = relationship(back_populates="events")


class CalendarSyncState(Base):
    __tablename__ = "calendar_sync_state"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_sources.id", ondelete="CASCADE"), primary_key=True
    )
    sync_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    delta_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    source: Mapped["CalendarSource"] = relationship(back_populates="sync_state")
