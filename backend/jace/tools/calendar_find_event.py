from __future__ import annotations

# JACE_STEP4C5A_CALENDAR_FIND_EVENT

import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from jace.calendar.date_resolution import (
    CalendarDateResolutionError,
    resolve_calendar_range,
)
from jace.calendar.models import CalendarEvent, CalendarSource
from jace.calendar.preferences import (
    DEFAULT_CALENDAR_TIMEZONE,
    ensure_calendar_preferences,
)
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.registry import registry


class CalendarFindEventInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Event title or distinctive title fragment to find. Copy the "
            "user's event name rather than inventing a local event ID."
        ),
    )
    when: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "Optional human date phrase such as tomorrow, Friday, or "
            "18 September 2026."
        ),
    )
    limit: int = Field(default=8, ge=1, le=20)


def _event_payload(
    event: CalendarEvent,
    source: CalendarSource,
) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "provider": source.provider_id,
        "account": source.account_hint,
        "calendar": source.name,
        "all_day": event.all_day,
        "start_at": (
            event.start_at.isoformat()
            if event.start_at
            else None
        ),
        "end_at": (
            event.end_at.isoformat()
            if event.end_at
            else None
        ),
        "start_date": (
            event.start_date.isoformat()
            if event.start_date
            else None
        ),
        "end_date_exclusive": (
            event.end_date_exclusive.isoformat()
            if event.end_date_exclusive
            else None
        ),
        "location": event.location or None,
        "status": event.status,
        "read_only": source.read_only,
    }


async def calendar_find_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CalendarFindEventInput)

    preferences = await ensure_calendar_preferences(context.session)
    timezone_name = (
        preferences.timezone
        or DEFAULT_CALENDAR_TIMEZONE
    )
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)

    if payload.when:
        try:
            resolved = resolve_calendar_range(
                payload.when,
                timezone_name=timezone_name,
                now=now,
            )
        except CalendarDateResolutionError as exc:
            raise ToolError(str(exc)) from exc

        range_start = resolved.start
        range_end = resolved.end
        resolved_when = resolved.as_dict()
    else:
        range_start = now - timedelta(days=180)
        range_end = now + timedelta(days=730)
        resolved_when = None

    needle = payload.query.strip()
    lowered = needle.casefold()

    title_rank = case(
        (
            func.lower(CalendarEvent.title) == lowered,
            0,
        ),
        else_=1,
    )

    statement = (
        select(CalendarEvent, CalendarSource)
        .join(
            CalendarSource,
            CalendarEvent.source_id == CalendarSource.id,
        )
        .where(
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.status != "cancelled",
            CalendarSource.enabled.is_(True),
            or_(
                func.lower(CalendarEvent.title).contains(lowered),
                func.lower(CalendarEvent.location).contains(lowered),
            ),
            or_(
                (
                    CalendarEvent.all_day.is_(False)
                    & (CalendarEvent.start_at < range_end)
                    & (CalendarEvent.end_at > range_start)
                ),
                (
                    CalendarEvent.all_day.is_(True)
                    & (CalendarEvent.start_date < range_end.date())
                    & (
                        CalendarEvent.end_date_exclusive
                        > range_start.date()
                    )
                ),
            ),
        )
        .order_by(
            title_rank,
            CalendarEvent.start_at,
            CalendarEvent.start_date,
        )
        .limit(payload.limit)
    )

    rows = list((await context.session.execute(statement)).all())
    events = [
        _event_payload(event, source)
        for event, source in rows
    ]

    result = {
        "query": payload.query,
        "timezone": timezone_name,
        "resolved_when": resolved_when,
        "match_count": len(events),
        "events": events,
    }

    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=(
            f"Found {len(events)} calendar event"
            f"{'' if len(events) == 1 else 's'} matching "
            f'"{payload.query}".'
        ),
        metadata={
            "category": "calendar",
            "read_only": True,
            "match_count": len(events),
        },
    )


def register_calendar_find_event_tool() -> None:
    registry.register(
        ToolDefinition(
            name="calendar_find_event",
            label="Find calendar event",
            description=(
                "Find an existing event in Jace's unified calendar cache by "
                "title/location and return its local event ID, provider, "
                "account and calendar. Use this before moving, editing or "
                "deleting an event when the user did not provide a local "
                "event ID."
            ),
            category="Calendar",
            risk="read",
            default_permission="allow",
            input_model=CalendarFindEventInput,
            handler=calendar_find_event_tool,
        ),
        replace=True,
    )
