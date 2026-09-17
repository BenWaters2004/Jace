from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from jace.calendar.date_resolution import resolve_calendar_range
from jace.calendar.intelligence import calendar_timezone, list_events
from jace.calendar.models import CalendarEvent, CalendarSource
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


def resolution_tests() -> None:
    zone = ZoneInfo("Europe/London")
    now = datetime(2026, 9, 17, 8, 0, tzinfo=zone)

    yesterday = resolve_calendar_range(
        "yesterday",
        timezone_name="Europe/London",
        now=now,
    )
    ordinal = resolve_calendar_range(
        "the 16th",
        timezone_name="Europe/London",
        now=now,
    )
    verbose = resolve_calendar_range(
        "for the 16th",
        timezone_name="Europe/London",
        now=now,
    )

    expected_start = datetime(2026, 9, 16, 0, 0, tzinfo=zone)
    expected_end = datetime(2026, 9, 17, 0, 0, tzinfo=zone)

    for label, resolved in (
        ("yesterday", yesterday),
        ("the 16th", ordinal),
        ("for the 16th", verbose),
    ):
        if resolved.start != expected_start or resolved.end != expected_end:
            raise RuntimeError(
                f"{label!r} resolved to {resolved.start} → {resolved.end}; "
                f"expected {expected_start} → {expected_end}."
            )

    print("17 Sept → yesterday = 16 Sept: PASS")
    print("17 Sept → the 16th = 16 Sept: PASS")
    print("Slightly over-copied date phrase handling: PASS")


def routing_tests() -> None:
    ensure_tools_registered()

    tool = registry.get("calendar_list_events")
    if tool is None:
        raise RuntimeError("calendar_list_events is not registered.")

    fields = set(tool.input_model.model_fields)

    if "when" not in fields:
        raise RuntimeError(
            "calendar_list_events still uses the old ISO-range input model."
        )

    yesterday = route_tool_names(
        "What was on my calendar yesterday?"
    )
    ordinal = route_tool_names(
        "What's on my calendar for the 16th?"
    )

    for label, routed in (
        ("yesterday", yesterday),
        ("the 16th", ordinal),
    ):
        if "calendar_list_events" not in routed:
            raise RuntimeError(
                f"{label} did not route calendar_list_events."
            )

        if "current_datetime" not in routed:
            raise RuntimeError(
                f"{label} did not route current_datetime."
            )

    print("Calendar agenda tool uses human date phrases: PASS")
    print("Yesterday routes current_datetime + Calendar Intelligence: PASS")
    print("Ordinal date routes current_datetime + Calendar Intelligence: PASS")


async def database_range_test() -> None:
    zone = ZoneInfo("Europe/London")

    async with SessionLocal() as session:
        source = CalendarSource(
            id=str(uuid4()),
            provider_id="jace",
            connection_id=None,
            external_calendar_id="date-resolution-test-" + str(uuid4()),
            name="Calendar date-resolution test",
            account_hint=None,
            color="#7489c8",
            timezone="Europe/London",
            read_only=False,
            enabled=True,
            sync_enabled=False,
            is_primary=False,
            sync_status="local",
            metadata_json="{}",
        )
        session.add(source)
        await session.flush()

        event = CalendarEvent(
            id=str(uuid4()),
            source_id=source.id,
            title="Calendar date-resolution regression event",
            description="",
            location="",
            all_day=False,
            start_at=datetime(
                2040,
                9,
                16,
                17,
                8,
                tzinfo=timezone.utc,
            ),
            end_at=datetime(
                2040,
                9,
                16,
                18,
                8,
                tzinfo=timezone.utc,
            ),
            timezone="Europe/London",
            status="confirmed",
            availability="busy",
            visibility="default",
            organizer_json="{}",
            attendees_json="[]",
            reminders_json="[]",
            recurrence_json="{}",
            created_by="user",
            sync_state="local",
            provider_data_json="{}",
            metadata_json="{}",
        )
        session.add(event)
        await session.flush()

        resolved = resolve_calendar_range(
            "16 September 2040",
            timezone_name="Europe/London",
            now=datetime(2040, 9, 17, 8, 0, tzinfo=zone),
        )

        result = await list_events(
            session,
            start=resolved.start,
            end=resolved.end,
            timezone_name="Europe/London",
        )

        if not any(
            row.get("title") == "Calendar date-resolution regression event"
            for row in result.get("events", [])
        ):
            raise RuntimeError(
                "A known event on 16 September was not returned by the unified "
                "calendar range query."
            )

        await session.rollback()

    print("Resolved day range returns matching unified-calendar event: PASS")


async def real_calendar_diagnostic() -> None:
    async with SessionLocal() as session:
        timezone_name = await calendar_timezone(session)
        resolved = resolve_calendar_range(
            "yesterday",
            timezone_name=timezone_name,
        )
        result = await list_events(
            session,
            start=resolved.start,
            end=resolved.end,
            timezone_name=timezone_name,
        )

    print()
    print("Live unified-calendar diagnostic")
    print("--------------------------------")
    print(f"Timezone: {timezone_name}")
    print(
        "Resolved yesterday: "
        f"{resolved.start.isoformat()} → {resolved.end.isoformat()}"
    )
    print(f"Events currently cached in that range: {result['event_count']}")

    for event in result.get("events", [])[:10]:
        start = event.get("start") or event.get("start_date") or "all day"
        print(
            f"  - {start} | {event.get('title')} "
            f"[{event.get('provider')} · {event.get('calendar')}]"
        )


async def main() -> int:
    print()
    print("Jace Step 4C.4F Calendar Date Resolution test")
    print("==============================================")
    print()

    resolution_tests()
    routing_tests()
    await database_range_test()
    await real_calendar_diagnostic()

    print()
    print("PASS - Calendar Date Resolution hotfix is operational.")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print()
        print(f"FAIL - {exc}", file=sys.stderr)
        print()
        raise
