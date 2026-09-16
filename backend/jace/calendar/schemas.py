from __future__ import annotations

# JACE_STEP4C4A_UNIFIED_CALENDAR_SCHEMAS

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

CalendarEventStatus = Literal["confirmed", "tentative", "cancelled"]
CalendarAvailability = Literal["busy", "free"]
CalendarVisibility = Literal["default", "public", "private", "confidential"]


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


class CalendarSourceResponse(BaseModel):
    id: str
    provider_id: str
    connection_id: str | None
    external_calendar_id: str | None
    name: str
    account_hint: str | None
    color: str
    timezone: str
    read_only: bool
    enabled: bool
    sync_enabled: bool
    is_primary: bool
    sync_status: str
    metadata: dict[str, Any]
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CalendarSourceListResponse(BaseModel):
    sources: list[CalendarSourceResponse]


class CalendarSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    color: str | None = Field(
        default=None, min_length=7, max_length=9,
        pattern=r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$",
    )
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sync_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_values(self) -> "CalendarSourceUpdate":
        if self.timezone is not None:
            validate_timezone(self.timezone)
        return self


class CalendarEventCreate(BaseModel):
    source_id: str | None = None
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=100_000)
    location: str = Field(default="", max_length=10_000)
    meeting_url: str | None = Field(default=None, max_length=10_000)
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str = Field(default="Europe/London", min_length=1, max_length=100)
    status: CalendarEventStatus = "confirmed"
    availability: CalendarAvailability = "busy"
    visibility: CalendarVisibility = "default"
    organizer: dict[str, Any] = Field(default_factory=dict)
    attendees: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    reminders: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    recurrence_rule: str | None = Field(default=None, max_length=10_000)
    recurrence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: Literal["user", "jace"] = "user"

    @model_validator(mode="after")
    def validate_event(self) -> "CalendarEventCreate":
        validate_timezone(self.timezone)
        if self.all_day:
            if self.start_date is None or self.end_date_exclusive is None:
                raise ValueError("All-day events require start_date and end_date_exclusive.")
            if self.end_date_exclusive <= self.start_date:
                raise ValueError("end_date_exclusive must be after start_date.")
            if self.start_at is not None or self.end_at is not None:
                raise ValueError("All-day events must not contain start_at/end_at.")
            return self
        if self.start_at is None or self.end_at is None:
            raise ValueError("Timed events require start_at and end_at.")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        if self.start_date is not None or self.end_date_exclusive is not None:
            raise ValueError("Timed events must not contain date-only fields.")
        return self


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=100_000)
    location: str | None = Field(default=None, max_length=10_000)
    meeting_url: str | None = Field(default=None, max_length=10_000)
    all_day: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    status: CalendarEventStatus | None = None
    availability: CalendarAvailability | None = None
    visibility: CalendarVisibility | None = None
    organizer: dict[str, Any] | None = None
    attendees: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    reminders: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    recurrence_rule: str | None = Field(default=None, max_length=10_000)
    recurrence: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_values(self) -> "CalendarEventUpdate":
        if self.timezone is not None:
            validate_timezone(self.timezone)
        return self


class CalendarEventResponse(BaseModel):
    id: str
    source_id: str
    provider_id: str
    calendar_name: str
    calendar_color: str
    account_hint: str | None
    source_read_only: bool
    external_event_id: str | None
    external_series_id: str | None
    original_event_id: str | None
    ical_uid: str | None
    title: str
    description: str
    location: str
    meeting_url: str | None
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date_exclusive: date | None
    timezone: str
    status: str
    availability: str
    visibility: str
    organizer: dict[str, Any]
    attendees: list[dict[str, Any]]
    reminders: list[dict[str, Any]]
    recurrence_rule: str | None
    recurrence: dict[str, Any]
    created_by: str
    sync_state: str
    sync_error: str | None
    can_edit: bool
    can_delete: bool
    event_type: str | None = None
    can_enrich_from_email: bool = False
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CalendarEventListResponse(BaseModel):
    start: datetime
    end: datetime
    timezone: str
    events: list[CalendarEventResponse]


class CalendarStatusResponse(BaseModel):
    default_calendar_id: str
    timezone: str
    source_count: int
    enabled_source_count: int
    local_event_count: int
    external_event_count: int
    pending_sync_count: int
