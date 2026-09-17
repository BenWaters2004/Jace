from __future__ import annotations

# JACE_STEP4C4F_CALENDAR_INTELLIGENCE_TOOLS
# JACE_STEP4C4F_CALENDAR_DATE_TOOL_FIX

import json
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field, field_validator

from jace.calendar.date_resolution import (
    CalendarDateResolutionError,
    resolve_calendar_range,
)
from jace.calendar.intelligence import (
    calendar_timezone,
    conflicts,
    find_open_slots,
    free_busy,
    list_events,
    next_event,
)
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.registry import registry


class CalendarAgendaInput(BaseModel):
    when: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "The user's calendar date phrase copied as literally as possible, "
            "for example: yesterday, today, tomorrow, the 16th, "
            "16 September 2026, Friday, next Friday, this week, or next week. "
            "Do NOT invent an ISO date for relative or incomplete wording. "
            "When the user used relative/incomplete wording, call "
            "current_datetime first, then pass the original phrase here."
        ),
    )
    timezone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone. Leave empty to use the Calendar timezone "
            "from Settings."
        ),
    )


class CalendarRangeInput(BaseModel):
    start: datetime = Field(
        description=(
            "Inclusive range start as an ISO 8601 date-time."
        )
    )
    end: datetime = Field(
        description=(
            "Exclusive range end as an ISO 8601 date-time."
        )
    )
    timezone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone. Leave empty to use the Calendar timezone "
            "from Settings."
        ),
    )


class CalendarNextInput(BaseModel):
    after: datetime | None = Field(
        default=None,
        description=(
            "Optional ISO date-time to search after. Leave empty for now."
        ),
    )
    lookahead_days: int = Field(
        default=90,
        ge=1,
        le=730,
    )
    timezone: str | None = None


class CalendarConflictInput(BaseModel):
    start: datetime
    end: datetime
    timezone: str | None = None


class CalendarOpenSlotsInput(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: int = Field(
        ge=5,
        le=1440,
        description="Required free-slot duration in minutes.",
    )
    day_start: str = Field(
        default="09:00",
        pattern=r"^\d{2}:\d{2}$",
        description="Earliest daily slot time in HH:MM.",
    )
    day_end: str = Field(
        default="17:00",
        pattern=r"^\d{2}:\d{2}$",
        description="Latest daily working-hours boundary in HH:MM.",
    )
    limit: int = Field(
        default=8,
        ge=1,
        le=20,
    )
    include_weekends: bool = Field(
        default=False,
        description="Include Saturday and Sunday in slot suggestions.",
    )
    timezone: str | None = None

    @field_validator(
        "day_start",
        "day_end",
    )
    @classmethod
    def valid_time(
        cls,
        value: str,
    ) -> str:
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "Expected HH:MM time."
            ) from exc

        return value


def _content(
    payload: dict[str, Any],
) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
    )


async def calendar_list_events_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarAgendaInput,
    )

    timezone_name = (
        payload.timezone
        or await calendar_timezone(
            context.session
        )
    )

    try:
        resolved = resolve_calendar_range(
            payload.when,
            timezone_name=timezone_name,
        )
    except CalendarDateResolutionError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    result = await list_events(
        context.session,
        start=resolved.start,
        end=resolved.end,
        timezone_name=timezone_name,
    )
    result["requested_when"] = payload.when
    result["resolved_date"] = resolved.as_dict()

    event_count = int(
        result.get(
            "event_count",
            0,
        )
    )

    return ToolExecutionResult(
        content=_content(result),
        display=(
            f"Read {event_count} calendar event"
            f"{'' if event_count == 1 else 's'} "
            f"for {resolved.label} ({timezone_name})."
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
            "requested_when": payload.when,
            "resolved_start": resolved.start.isoformat(),
            "resolved_end": resolved.end.isoformat(),
            "timezone": timezone_name,
            "resolution": resolved.resolution,
        },
    )


async def calendar_next_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarNextInput,
    )

    result = await next_event(
        context.session,
        after=payload.after,
        lookahead_days=payload.lookahead_days,
        timezone_name=payload.timezone,
    )

    event = result.get(
        "event"
    )

    return ToolExecutionResult(
        content=_content(result),
        display=(
            f'Next calendar event: "{event["title"]}".'
            if isinstance(
                event,
                dict,
            )
            else "No upcoming calendar event found in the requested period."
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
        },
    )


async def calendar_free_busy_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarRangeInput,
    )

    result = await free_busy(
        context.session,
        start=payload.start,
        end=payload.end,
        timezone_name=payload.timezone,
    )

    return ToolExecutionResult(
        content=_content(result),
        display=(
            "Calendar is free in the requested period."
            if result[
                "is_free"
            ]
            else (
                f"Calendar has {len(result['busy_events'])} "
                "busy event(s) in the requested period."
            )
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
        },
    )


async def calendar_check_conflicts_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarConflictInput,
    )

    result = await conflicts(
        context.session,
        start=payload.start,
        end=payload.end,
        timezone_name=payload.timezone,
    )

    return ToolExecutionResult(
        content=_content(result),
        display=(
            f"Found {result['conflict_count']} conflicting calendar event(s)."
            if result[
                "has_conflict"
            ]
            else "No calendar conflict found."
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
        },
    )


async def calendar_find_open_slots_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarOpenSlotsInput,
    )

    result = await find_open_slots(
        context.session,
        start=payload.start,
        end=payload.end,
        duration_minutes=payload.duration_minutes,
        day_start=time.fromisoformat(
            payload.day_start
        ),
        day_end=time.fromisoformat(
            payload.day_end
        ),
        timezone_name=payload.timezone,
        limit=payload.limit,
        include_weekends=payload.include_weekends,
    )

    return ToolExecutionResult(
        content=_content(result),
        display=(
            f"Found {result['slot_count']} open calendar slot"
            f"{'' if result['slot_count'] == 1 else 's'}."
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
        },
    )


def register_calendar_intelligence_tools() -> None:
    definitions = [
        ToolDefinition(
            name="calendar_list_events",
            label="Read unified calendar",
            description=(
                "Read events from Jace's unified Jace/Google/Outlook calendar "
                "for a human date expression. IMPORTANT: if the user says "
                "yesterday, today, tomorrow, a weekday, or an incomplete date "
                "such as 'the 16th', call current_datetime first and then copy "
                "the user's original date phrase into `when`. Never manufacture "
                "an ISO range for an incomplete calendar date."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarAgendaInput,
            handler=calendar_list_events_tool,
        ),
        ToolDefinition(
            name="calendar_next_event",
            label="Find next calendar event",
            description=(
                "Find the next current or upcoming event across the unified "
                "Jace, Google and Outlook calendar."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarNextInput,
            handler=calendar_next_event_tool,
        ),
        ToolDefinition(
            name="calendar_free_busy",
            label="Check calendar free/busy",
            description=(
                "Check whether an exact date/time range is free or busy and "
                "return busy intervals/events across all enabled calendars. "
                "Use current_datetime first when converting relative wording "
                "into an exact time range."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarRangeInput,
            handler=calendar_free_busy_tool,
        ),
        ToolDefinition(
            name="calendar_check_conflicts",
            label="Check calendar conflicts",
            description=(
                "Check a proposed exact start/end time against all enabled "
                "calendars and return any events that conflict."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarConflictInput,
            handler=calendar_check_conflicts_tool,
        ),
        ToolDefinition(
            name="calendar_find_open_slots",
            label="Find open calendar slots",
            description=(
                "Find free time slots of a requested duration within an exact "
                "date range and working-hours window across the unified calendar. "
                "Use current_datetime first when the user's range is relative."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarOpenSlotsInput,
            handler=calendar_find_open_slots_tool,
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
