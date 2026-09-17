from __future__ import annotations

# JACE_STEP4C5A_CALENDAR_WRITE_COMMON

from datetime import date, datetime, time, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from jace.calendar.models import CalendarEvent, CalendarSource
from jace.calendar.preferences import (
    DEFAULT_CALENDAR_TIMEZONE,
    ensure_calendar_preferences,
)
from jace.calendar.service import get_calendar_event
from jace.tools.base import ToolContext, ToolError


CalendarAvailability = Literal["busy", "free"]
CalendarVisibility = Literal[
    "default",
    "public",
    "private",
    "confidential",
]


class CalendarCreateEventInput(BaseModel):
    calendar: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Optional human calendar name, for example 'Work' or 'Personal'. "
            "Leave empty to use the primary calendar for the resolved account. "
            "Never supply a connection ID."
        ),
    )
    title: str = Field(
        min_length=1,
        max_length=1000,
    )
    description: str = Field(
        default="",
        max_length=20_000,
    )
    location: str = Field(
        default="",
        max_length=2000,
    )
    all_day: bool = False
    start_at: datetime | None = Field(
        default=None,
        description=(
            "Timed-event start. If timezone-naive, it is interpreted in `timezone`."
        ),
    )
    end_at: datetime | None = Field(
        default=None,
        description=(
            "Timed-event end. If timezone-naive, it is interpreted in `timezone`."
        ),
    )
    start_date: date | None = None
    end_date_exclusive: date | None = Field(
        default=None,
        description=(
            "For all-day events, the exclusive end date. "
            "A one-day event ending on 20 September uses 21 September here."
        ),
    )
    timezone: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "IANA timezone. Leave empty to use Jace Calendar Settings."
        ),
    )
    availability: CalendarAvailability = "busy"
    visibility: CalendarVisibility = "default"

    @model_validator(mode="after")
    def validate_window(self):
        if self.all_day:
            if (
                self.start_date is None
                or self.end_date_exclusive is None
            ):
                raise ValueError(
                    "All-day events require start_date and end_date_exclusive."
                )
            if self.end_date_exclusive <= self.start_date:
                raise ValueError(
                    "end_date_exclusive must be after start_date."
                )
            if self.start_at is not None or self.end_at is not None:
                raise ValueError(
                    "All-day events must not include start_at/end_at."
                )
        else:
            if self.start_at is None or self.end_at is None:
                raise ValueError(
                    "Timed events require start_at and end_at."
                )
        return self


class CalendarModifyEventInput(BaseModel):
    event_id: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Jace local calendar event ID returned by Calendar Intelligence. "
            "Do not invent an event ID."
        ),
    )
    action: Literal["update", "delete"] = "update"
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
    )
    description: str | None = Field(
        default=None,
        max_length=20_000,
    )
    location: str | None = Field(
        default=None,
        max_length=2000,
    )
    all_day: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date_exclusive: date | None = None
    timezone: str | None = Field(
        default=None,
        max_length=100,
    )
    availability: CalendarAvailability | None = None
    visibility: CalendarVisibility | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if self.action == "delete":
            return self

        fields = self.model_fields_set - {
            "event_id",
            "action",
        }

        if not fields:
            raise ValueError(
                "Update requires at least one changed event field."
            )

        start_changed = (
            "start_at" in self.model_fields_set
            or "end_at" in self.model_fields_set
        )
        date_changed = (
            "start_date" in self.model_fields_set
            or "end_date_exclusive" in self.model_fields_set
        )

        if start_changed and (
            self.start_at is None
            or self.end_at is None
        ):
            raise ValueError(
                "Changing timed dates requires both start_at and end_at."
            )

        if date_changed and (
            self.start_date is None
            or self.end_date_exclusive is None
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
            raise ValueError(
                "end_date_exclusive must be after start_date."
            )

        return self


async def effective_timezone(
    context: ToolContext,
    requested: str | None,
) -> str:
    name = requested

    if not name:
        preferences = await ensure_calendar_preferences(
            context.session
        )
        name = (
            preferences.timezone
            or DEFAULT_CALENDAR_TIMEZONE
        )

    try:
        ZoneInfo(name)
    except Exception as exc:
        raise ToolError(
            f"Unknown calendar timezone: {name}"
        ) from exc

    return name


def aware_datetime(
    value: datetime,
    timezone_name: str,
) -> datetime:
    if value.tzinfo is not None:
        return value

    return value.replace(
        tzinfo=ZoneInfo(
            timezone_name
        )
    )


def utc_datetime(
    value: datetime,
    timezone_name: str,
) -> datetime:
    return aware_datetime(
        value,
        timezone_name,
    ).astimezone(
        timezone.utc
    )


def _binding(
    context: ToolContext,
    provider_id: str,
    capability_id: str,
) -> tuple[str, str]:
    binding = (
        context.capability_binding
        or {}
    )

    if (
        binding.get(
            "provider_id"
        )
        != provider_id
    ):
        raise ToolError(
            f"Calendar write requires a {provider_id} capability binding."
        )

    if (
        binding.get(
            "capability_id"
        )
        != capability_id
    ):
        raise ToolError(
            f"Calendar write requires {capability_id} capability authorization."
        )

    connection_id = binding.get(
        "connection_id"
    )

    if not isinstance(
        connection_id,
        str,
    ) or not connection_id:
        raise ToolError(
            "Calendar write requires a resolved connected account."
        )

    account_hint = binding.get(
        "account_hint"
    )

    return (
        connection_id,
        str(
            account_hint
            or provider_id
        ),
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

    statement = select(
        CalendarSource
    ).where(
        CalendarSource.provider_id
        == provider_id,
        CalendarSource.connection_id
        == connection_id,
        CalendarSource.enabled.is_(
            True
        ),
        CalendarSource.external_calendar_id.is_not(
            None
        ),
    )

    rows = list(
        (
            await context.session.execute(
                statement
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
            if row.name.casefold()
            == needle
            or (
                row.external_calendar_id
                and row.external_calendar_id.casefold()
                == needle
            )
        ]

        if len(matches) > 1:
            raise ToolError(
                f'More than one calendar named "{calendar}" exists on {account}. '
                "Ask the user which calendar to use."
            )

        if len(matches) == 1:
            selected = matches[0]
        else:
            raise ToolError(
                f'No calendar named "{calendar}" was found on {account}. '
                "Use the calendar names returned by Calendar Intelligence."
            )
    else:
        primary = [
            row
            for row in rows
            if row.is_primary
        ]

        if len(primary) == 1:
            selected = primary[0]
        elif len(rows) == 1:
            selected = rows[0]
        else:
            names = ", ".join(
                sorted(
                    row.name
                    for row in rows
                )
            )
            raise ToolError(
                "This account has multiple writable calendar choices and "
                f"no single primary calendar could be selected. Available: {names}. "
                "Ask the user which calendar to use."
            )

    if selected.read_only:
        raise ToolError(
            f'Calendar "{selected.name}" is read-only for this account.'
        )

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

    row = await get_calendar_event(
        context.session,
        event_id,
    )

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
        raise ToolError(
            f'Calendar "{row.source.name}" is read-only.'
        )

    if not row.external_event_id:
        raise ToolError(
            "The selected external event has no provider event ID."
        )

    return row, account


def local_event_summary(
    row: CalendarEvent,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_event_id":
            row.external_event_id,
        "title": row.title,
        "calendar":
            row.source.name,
        "provider":
            row.source.provider_id,
        "account":
            row.source.account_hint,
        "all_day":
            row.all_day,
        "start_at":
            row.start_at.isoformat()
            if row.start_at
            else None,
        "end_at":
            row.end_at.isoformat()
            if row.end_at
            else None,
        "start_date":
            row.start_date.isoformat()
            if row.start_date
            else None,
        "end_date_exclusive":
            row.end_date_exclusive.isoformat()
            if row.end_date_exclusive
            else None,
        "timezone":
            row.timezone,
        "status":
            row.status,
    }
