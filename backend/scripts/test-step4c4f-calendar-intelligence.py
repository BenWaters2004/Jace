from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from jace.calendar.intelligence import (
    conflicts,
    find_open_slots,
    free_busy,
    list_events,
    next_event,
)
from jace.calendar.models import (
    CalendarEvent,
    CalendarSource,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


TOOL_NAMES = {
    "calendar_list_events",
    "calendar_next_event",
    "calendar_free_busy",
    "calendar_check_conflicts",
    "calendar_find_open_slots",
}


def routing_tests() -> None:
    ensure_tools_registered()

    missing = [
        name
        for name in TOOL_NAMES
        if registry.get(name) is None
    ]

    if missing:
        raise RuntimeError(
            "Calendar intelligence tools were not registered: "
            + ", ".join(missing)
        )

    routed = route_tool_names(
        "When am I free tomorrow afternoon?"
    )

    if not TOOL_NAMES.issubset(
        routed
    ):
        raise RuntimeError(
            "Smart tool routing did not expose the calendar intelligence tools."
        )

    if "current_datetime" not in routed:
        raise RuntimeError(
            "Relative calendar wording did not route current_datetime."
        )

    print(
        "Calendar tool registration: PASS"
    )
    print(
        "Calendar smart-tool routing: PASS"
    )


async def intelligence_tests() -> None:
    zone = ZoneInfo(
        "Europe/London"
    )

    async with SessionLocal() as session:
        source = CalendarSource(
            id=str(uuid4()),
            provider_id="jace",
            connection_id=None,
            external_calendar_id=(
                "step4c4f-"
                + str(uuid4())
            ),
            name="Step 4C.4F test",
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
        session.add(
            source
        )
        await session.flush()

        first = CalendarEvent(
            id=str(uuid4()),
            source_id=source.id,
            title="Step 4C.4F morning meeting",
            description="",
            location="Test room",
            all_day=False,
            start_at=datetime(
                2040,
                1,
                2,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            end_at=datetime(
                2040,
                1,
                2,
                11,
                0,
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
        second = CalendarEvent(
            id=str(uuid4()),
            source_id=source.id,
            title="Step 4C.4F afternoon meeting",
            description="",
            location="",
            all_day=False,
            start_at=datetime(
                2040,
                1,
                2,
                14,
                0,
                tzinfo=timezone.utc,
            ),
            end_at=datetime(
                2040,
                1,
                2,
                15,
                0,
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
        all_day = CalendarEvent(
            id=str(uuid4()),
            source_id=source.id,
            title="Step 4C.4F all-day item",
            description="",
            location="",
            all_day=True,
            start_date=date(
                2040,
                1,
                3,
            ),
            end_date_exclusive=date(
                2040,
                1,
                4,
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

        session.add_all(
            [
                first,
                second,
                all_day,
            ]
        )
        await session.flush()

        day_start = datetime(
            2040,
            1,
            2,
            9,
            0,
            tzinfo=zone,
        )
        day_end = datetime(
            2040,
            1,
            2,
            17,
            0,
            tzinfo=zone,
        )

        listed = await list_events(
            session,
            start=day_start,
            end=day_end,
            timezone_name="Europe/London",
        )

        titles = {
            event["title"]
            for event in listed[
                "events"
            ]
        }

        if (
            "Step 4C.4F morning meeting"
            not in titles
            or "Step 4C.4F afternoon meeting"
            not in titles
        ):
            raise RuntimeError(
                "Unified range lookup did not return the test meetings."
            )

        print(
            "Unified calendar range lookup: PASS"
        )

        next_result = await next_event(
            session,
            after=day_start,
            lookahead_days=2,
            timezone_name="Europe/London",
        )

        if (
            not next_result["event"]
            or next_result[
                "event"
            ][
                "title"
            ]
            != "Step 4C.4F morning meeting"
        ):
            raise RuntimeError(
                "Next-event intelligence returned the wrong event."
            )

        print(
            "Next-event intelligence: PASS"
        )

        busy = await free_busy(
            session,
            start=day_start,
            end=day_end,
            timezone_name="Europe/London",
        )

        if (
            busy[
                "is_free"
            ]
            or len(
                busy[
                    "busy_events"
                ]
            ) < 2
        ):
            raise RuntimeError(
                "Free/busy intelligence did not detect the busy periods."
            )

        print(
            "Free/busy intelligence: PASS"
        )

        conflict = await conflicts(
            session,
            start=datetime(
                2040,
                1,
                2,
                10,
                30,
                tzinfo=zone,
            ),
            end=datetime(
                2040,
                1,
                2,
                10,
                45,
                tzinfo=zone,
            ),
            timezone_name="Europe/London",
        )

        if not conflict[
            "has_conflict"
        ]:
            raise RuntimeError(
                "Conflict detection missed an overlapping meeting."
            )

        print(
            "Conflict detection: PASS"
        )

        slots = await find_open_slots(
            session,
            start=day_start,
            end=day_end,
            duration_minutes=60,
            day_start=time(
                9,
                0,
            ),
            day_end=time(
                17,
                0,
            ),
            timezone_name="Europe/London",
            limit=5,
        )

        if not slots[
            "slots"
        ]:
            raise RuntimeError(
                "Open-slot intelligence did not find any free time."
            )

        first_slot = slots[
            "slots"
        ][0]

        if not first_slot[
            "start"
        ].startswith(
            "2040-01-02T09:00"
        ):
            raise RuntimeError(
                "Expected 09:00-10:00 to be the first free one-hour slot."
            )

        print(
            "Open-slot intelligence: PASS"
        )

        all_day_busy = await free_busy(
            session,
            start=datetime(
                2040,
                1,
                3,
                9,
                0,
                tzinfo=zone,
            ),
            end=datetime(
                2040,
                1,
                3,
                17,
                0,
                tzinfo=zone,
            ),
            timezone_name="Europe/London",
        )

        if all_day_busy[
            "is_free"
        ]:
            raise RuntimeError(
                "All-day events were not treated as busy."
            )

        print(
            "All-day busy handling: PASS"
        )

        # Never retain acceptance-test calendar data.
        await session.rollback()


async def main() -> int:
    print()
    print(
        "Jace Step 4C.4F Calendar Intelligence test"
    )
    print(
        "=========================================="
    )
    print()

    routing_tests()
    await intelligence_tests()

    print()
    print(
        "PASS - Step 4C.4F Calendar Intelligence is operational."
    )
    print(
        "Test events were rolled back; no calendar entries were retained."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            asyncio.run(
                main()
            )
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
