from __future__ import annotations

# JACE_STEP4C5B_SCHEDULING_COMMON

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select, update

from jace.calendar.models import CalendarEvent, CalendarSource
from jace.calendar.preferences import (
    DEFAULT_CALENDAR_TIMEZONE,
    ensure_calendar_preferences,
)
from jace.calendar.service import get_calendar_event
from jace.db.models import utc_now
from jace.tools.base import ToolContext, ToolError


CalendarAvailability = Literal["busy", "free"]
CalendarVisibility = Literal["default", "public", "private", "confidential"]
CalendarAttendeeType = Literal["required", "optional", "resource"]
CalendarReminderMethod = Literal["popup", "email"]
CalendarRecurrenceFrequency = Literal["daily", "weekly", "monthly", "yearly"]
CalendarWeekday = Literal[
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]
CalendarOnlineMeeting = Literal["google_meet", "microsoft_teams"]
CalendarSeriesScope = Literal["single", "series"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CalendarAttendeeInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=300)
    type: CalendarAttendeeType = "required"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip()
        if not _EMAIL_RE.fullmatch(cleaned):
            raise ValueError(f"Invalid attendee email address: {cleaned}")
        return cleaned


class CalendarReminderInput(BaseModel):
    minutes_before_start: int = Field(ge=0, le=40_320)
    method: CalendarReminderMethod = "popup"


class CalendarRecurrenceInput(BaseModel):
    frequency: CalendarRecurrenceFrequency
    interval: int = Field(default=1, ge=1, le=99)
    weekdays: list[CalendarWeekday] = Field(default_factory=list, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    month: int | None = Field(default=None, ge=1, le=12)
    count: int | None = Field(default=None, ge=1, le=999)
    until: date | None = None

    @model_validator(mode="after")
    def validate_pattern(self):
        if self.count is not None and self.until is not None:
            raise ValueError("Recurrence can use count or until, not both.")
        if self.frequency != "weekly" and self.weekdays:
            raise ValueError("weekdays can only be used with weekly recurrence.")
        if self.frequency in {"daily", "weekly"} and (
            self.day_of_month is not None or self.month is not None
        ):
            raise ValueError(
                f"{self.frequency.title()} recurrence does not use "
                "day_of_month/month."
            )
        if self.frequency == "monthly" and self.month is not None:
            raise ValueError("Monthly recurrence does not use month.")
        return self


class CalendarCreateEventInput(BaseModel):
    calendar: str | None = Field(default=None, max_length=300)
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=20_000)
    location: str = Field(default="", max_length=2000)
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = Field(default=None, max_length=100)
    availability: CalendarAvailability = "busy"
    visibility: CalendarVisibility = "default"
    attendees: list[CalendarAttendeeInput] = Field(
        default_factory=list,
        max_length=200,
    )
    reminders: list[CalendarReminderInput] | None = Field(
        default=None,
        max_length=5,
        description="Null keeps provider defaults; [] disables reminders.",
    )
    recurrence: CalendarRecurrenceInput | None = None
    online_meeting: CalendarOnlineMeeting | None = None
    notify_attendees: bool = True
    allow_new_time_proposals: bool = True

    @model_validator(mode="after")
    def validate_window(self):
        if self.all_day:
            if self.start_date is None or self.end_date_exclusive is None:
                raise ValueError(
                    "All-day events require start_date and end_date_exclusive."
                )
            if self.end_date_exclusive <= self.start_date:
                raise ValueError("end_date_exclusive must be after start_date.")
            if self.start_at is not None or self.end_at is not None:
                raise ValueError(
                    "All-day events must not include start_at/end_at."
                )
        else:
            if self.start_at is None or self.end_at is None:
                raise ValueError("Timed events require start_at and end_at.")
        _validate_unique_attendees(self.attendees)
        return self


class CalendarModifyEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    action: Literal["update", "delete"] = "update"
    recurrence_scope: CalendarSeriesScope = "single"
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=2000)
    all_day: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = Field(default=None, max_length=100)
    availability: CalendarAvailability | None = None
    visibility: CalendarVisibility | None = None
    attendees: list[CalendarAttendeeInput] | None = Field(
        default=None,
        max_length=200,
        description="Complete replacement list. Null preserves; [] removes all.",
    )
    reminders: list[CalendarReminderInput] | None = Field(
        default=None,
        max_length=5,
        description="Complete replacement list. Null preserves; [] disables.",
    )
    recurrence: CalendarRecurrenceInput | None = None
    online_meeting: CalendarOnlineMeeting | None = None
    notify_attendees: bool = True
    allow_new_time_proposals: bool | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if self.action == "delete":
            return self

        ignored = {"event_id", "action", "recurrence_scope", "notify_attendees"}
        if not (self.model_fields_set - ignored):
            raise ValueError("Update requires at least one changed event field.")

        start_changed = (
            "start_at" in self.model_fields_set
            or "end_at" in self.model_fields_set
        )
        date_changed = (
            "start_date" in self.model_fields_set
            or "end_date_exclusive" in self.model_fields_set
        )
        if start_changed and (self.start_at is None or self.end_at is None):
            raise ValueError(
                "Changing timed dates requires both start_at and end_at."
            )
        if date_changed and (
            self.start_date is None or self.end_date_exclusive is None
        ):
            raise ValueError(
                "Changing all-day dates requires both start_date "
                "and end_date_exclusive."
            )
        if (
            self.start_date is not None
            and self.end_date_exclusive is not None
            and self.end_date_exclusive <= self.start_date
        ):
            raise ValueError("end_date_exclusive must be after start_date.")
        if (
            "recurrence" in self.model_fields_set
            and self.recurrence_scope != "series"
        ):
            raise ValueError(
                "Changing/clearing recurrence requires recurrence_scope=series."
            )
        if self.attendees is not None:
            _validate_unique_attendees(self.attendees)
        return self


def _validate_unique_attendees(
    attendees: list[CalendarAttendeeInput],
) -> None:
    seen: set[str] = set()
    for attendee in attendees:
        key = attendee.email.casefold()
        if key in seen:
            raise ValueError(f"Duplicate attendee email: {attendee.email}")
        seen.add(key)


async def effective_timezone(
    context: ToolContext,
    requested: str | None,
) -> str:
    name = requested
    if not name:
        preferences = await ensure_calendar_preferences(context.session)
        name = preferences.timezone or DEFAULT_CALENDAR_TIMEZONE
    try:
        ZoneInfo(name)
    except Exception as exc:
        raise ToolError(f"Unknown calendar timezone: {name}") from exc
    return name


def aware_datetime(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is not None:
        return value.astimezone(zone)
    return value.replace(tzinfo=zone)


def utc_datetime(value: datetime, timezone_name: str) -> datetime:
    return aware_datetime(value, timezone_name).astimezone(timezone.utc)


def first_occurrence_date(
    data: CalendarCreateEventInput | CalendarModifyEventInput,
    timezone_name: str,
    *,
    fallback_event: CalendarEvent | None = None,
) -> date:
    if data.start_date is not None:
        return data.start_date
    if data.start_at is not None:
        return aware_datetime(data.start_at, timezone_name).date()
    if fallback_event is not None:
        if fallback_event.start_date is not None:
            return fallback_event.start_date
        if fallback_event.start_at is not None:
            value = fallback_event.start_at
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(ZoneInfo(timezone_name)).date()
    raise ToolError(
        "Could not establish the first occurrence date for recurrence."
    )


def _binding(
    context: ToolContext,
    provider_id: str,
    capability_id: str,
) -> tuple[str, str]:
    binding = context.capability_binding or {}
    if binding.get("provider_id") != provider_id:
        raise ToolError(
            f"Calendar write requires a {provider_id} capability binding."
        )
    if binding.get("capability_id") != capability_id:
        raise ToolError(
            f"Calendar write requires {capability_id} capability authorization."
        )
    connection_id = binding.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id:
        raise ToolError(
            "Calendar write requires a resolved connected account."
        )
    return (
        connection_id,
        str(binding.get("account_hint") or provider_id),
    )


async def resolve_create_source(
    context: ToolContext,
    *,
    provider_id: str,
    capability_id: str,
    calendar: str | None,
) -> tuple[CalendarSource, str]:
    connection_id, account = _binding(
        context,
        provider_id,
        capability_id,
    )
    rows = list(
        (
            await context.session.execute(
                select(CalendarSource).where(
                    CalendarSource.provider_id == provider_id,
                    CalendarSource.connection_id == connection_id,
                    CalendarSource.enabled.is_(True),
                    CalendarSource.external_calendar_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    if not rows:
        raise ToolError(
            "No synchronized external calendars are available for "
            f"{account}. Open/refresh the Calendar workspace first."
        )

    selected: CalendarSource | None = None
    if calendar:
        needle = calendar.strip().casefold()
        matches = [
            row
            for row in rows
            if row.name.casefold() == needle
            or (
                row.external_calendar_id
                and row.external_calendar_id.casefold() == needle
            )
        ]
        if len(matches) > 1:
            raise ToolError(
                f'More than one calendar named "{calendar}" exists on {account}.'
            )
        if len(matches) == 1:
            selected = matches[0]
        else:
            raise ToolError(
                f'No calendar named "{calendar}" was found on {account}.'
            )
    else:
        primary = [row for row in rows if row.is_primary]
        if len(primary) == 1:
            selected = primary[0]
        elif len(rows) == 1:
            selected = rows[0]
        else:
            names = ", ".join(sorted(row.name for row in rows))
            raise ToolError(
                "This account has multiple writable calendars and no single "
                f"primary was selected. Available: {names}."
            )

    if selected.read_only:
        raise ToolError(f'Calendar "{selected.name}" is read-only.')
    return selected, account


async def resolve_modify_event(
    context: ToolContext,
    *,
    provider_id: str,
    capability_id: str,
    event_id: str,
) -> tuple[CalendarEvent, str]:
    connection_id, account = _binding(
        context,
        provider_id,
        capability_id,
    )
    row = await get_calendar_event(context.session, event_id)
    if row is None:
        raise ToolError(
            "The selected calendar event no longer exists in Jace's cache."
        )
    if row.source.provider_id != provider_id:
        raise ToolError(
            f"The selected event belongs to {row.source.provider_id}, "
            f"not {provider_id}."
        )
    if row.source.connection_id != connection_id:
        raise ToolError(
            "The selected event belongs to a different connected account."
        )
    if row.source.read_only:
        raise ToolError(f'Calendar "{row.source.name}" is read-only.')
    if not row.external_event_id:
        raise ToolError(
            "The selected external event has no provider event ID."
        )
    return row, account


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def source_metadata(source: CalendarSource) -> dict[str, Any]:
    return parse_json_object(source.metadata_json)


def existing_attendee_count(event: CalendarEvent) -> int:
    return len(parse_json_list(event.attendees_json))


def target_external_event_id(
    event: CalendarEvent,
    scope: CalendarSeriesScope,
) -> str:
    if scope == "series" and event.external_series_id:
        return event.external_series_id
    if not event.external_event_id:
        raise ToolError(
            "The selected calendar event has no provider event ID."
        )
    return event.external_event_id


async def mark_series_deleted(
    context: ToolContext,
    event: CalendarEvent,
) -> None:
    series_id = event.external_series_id or event.external_event_id
    if not series_id:
        return
    now = utc_now()
    await context.session.execute(
        update(CalendarEvent)
        .where(
            CalendarEvent.source_id == event.source_id,
            or_(
                CalendarEvent.external_event_id == series_id,
                CalendarEvent.external_series_id == series_id,
            ),
        )
        .values(
            deleted_at=now,
            sync_state="synced",
            sync_error=None,
            updated_at=now,
        )
    )


async def mark_series_pending(
    context: ToolContext,
    event: CalendarEvent,
    warning: str | None = None,
) -> None:
    series_id = event.external_series_id or event.external_event_id
    if not series_id:
        return
    now = utc_now()
    await context.session.execute(
        update(CalendarEvent)
        .where(
            CalendarEvent.source_id == event.source_id,
            or_(
                CalendarEvent.external_event_id == series_id,
                CalendarEvent.external_series_id == series_id,
            ),
        )
        .values(
            sync_state="pending",
            sync_error=warning,
            updated_at=now,
        )
    )


def local_event_summary(row: CalendarEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_event_id": row.external_event_id,
        "external_series_id": row.external_series_id,
        "title": row.title,
        "calendar": row.source.name,
        "provider": row.source.provider_id,
        "account": row.source.account_hint,
        "all_day": row.all_day,
        "start_at": row.start_at.isoformat() if row.start_at else None,
        "end_at": row.end_at.isoformat() if row.end_at else None,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date_exclusive": (
            row.end_date_exclusive.isoformat()
            if row.end_date_exclusive
            else None
        ),
        "timezone": row.timezone,
        "status": row.status,
        "meeting_url": row.meeting_url,
        "attendee_count": len(parse_json_list(row.attendees_json)),
        "reminders": parse_json_list(row.reminders_json),
        "recurrence": parse_json_object(row.recurrence_json),
    }
