from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jace.calendar.models import CalendarEvent, CalendarSource
from jace.calendar.write_target_resolution import (
    candidate_phrases,
    infer_calendar_modify_target,
)
from jace.capabilities.runtime import detect_capability_needs
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.agent import (
    _calendar_write_request,
    _looks_like_write_success,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


FOLLOW_UP = 'Move "Jace calendar write test" to 4pm.'


def static_tests() -> None:
    needs = {
        need.capability_id
        for need in detect_capability_needs(FOLLOW_UP)
    }

    if "calendar.modify" not in needs:
        raise RuntimeError(
            "Natural move/reschedule follow-up did not detect calendar.modify."
        )

    routed = route_tool_names(FOLLOW_UP)

    if "calendar_find_event" not in routed:
        raise RuntimeError(
            "Natural modify follow-up did not route calendar_find_event."
        )

    phrases = candidate_phrases(FOLLOW_UP)

    if "Jace calendar write test" not in phrases:
        raise RuntimeError(
            "Quoted event title was not extracted from the follow-up."
        )

    if not _calendar_write_request(FOLLOW_UP):
        raise RuntimeError(
            "Agent calendar-write completion guard did not recognise the request."
        )

    if not _looks_like_write_success("Done — I've moved it to 4pm."):
        raise RuntimeError(
            "Agent false-success detector did not recognise a success claim."
        )

    if _looks_like_write_success(
        "I couldn't move it because the provider write failed."
    ):
        raise RuntimeError(
            "Agent false-success detector incorrectly classified a failure."
        )

    ensure_tools_registered()
    find_tool = registry.get("calendar_find_event")

    if find_tool is None:
        raise RuntimeError(
            "calendar_find_event was not registered."
        )

    for name in (
        "google_calendar_modify_event",
        "microsoft_calendar_modify_event",
    ):
        tool = registry.get(name)
        if tool is None:
            raise RuntimeError(f"{name} is not registered.")
        if tool.risk != "write" or tool.default_permission != "ask":
            raise RuntimeError(
                f"{name} is no longer guarded by write/Ask permissions."
            )

    print("Natural calendar.modify intent detection: PASS")
    print("Modify follow-up smart routing: PASS")
    print("Quoted event-title extraction: PASS")
    print("Calendar write false-success guard: PASS")
    print("calendar_find_event registration: PASS")
    print("External modify tools remain Ask/write: PASS")


async def target_binding_test() -> None:
    async with SessionLocal() as session:
        source = CalendarSource(
            id=str(uuid4()),
            provider_id="google",
            connection_id="step4c5a-test-connection",
            external_calendar_id="step4c5a-test-calendar",
            name="Step 4C.5A test calendar",
            account_hint="test@example.com",
            color="#7489c8",
            timezone="Europe/London",
            read_only=False,
            enabled=True,
            sync_enabled=True,
            is_primary=True,
            sync_status="synced",
            metadata_json="{}",
        )
        session.add(source)
        await session.flush()

        start = datetime.now(timezone.utc) + timedelta(days=1)
        event = CalendarEvent(
            id=str(uuid4()),
            source_id=source.id,
            external_event_id="step4c5a-provider-event",
            title="Jace calendar write test",
            description="",
            location="",
            all_day=False,
            start_at=start,
            end_at=start + timedelta(minutes=30),
            timezone="Europe/London",
            status="confirmed",
            availability="busy",
            visibility="default",
            organizer_json="{}",
            attendees_json="[]",
            reminders_json="[]",
            recurrence_json="{}",
            created_by="provider",
            sync_state="synced",
            provider_data_json="{}",
            metadata_json="{}",
        )
        session.add(event)
        await session.flush()

        hint = await infer_calendar_modify_target(
            session,
            FOLLOW_UP,
        )

        if hint is None:
            raise RuntimeError(
                "A unique cached event did not produce a modify target hint."
            )

        if hint.provider_id != "google":
            raise RuntimeError(
                f"Expected google target, got {hint.provider_id}."
            )

        if hint.connection_id != "step4c5a-test-connection":
            raise RuntimeError(
                "Modify target did not retain the backend-owned connection ID."
            )

        if hint.event_id != event.id:
            raise RuntimeError(
                "Modify target did not resolve the correct local event ID."
            )

        await session.rollback()

    print("Unique cached event → provider/account binding: PASS")
    print("Test cache rows rolled back: PASS")


async def main() -> int:
    print()
    print("Jace Step 4C.5A Calendar Modify Follow-up Fix test")
    print("================================================")
    print()

    static_tests()
    await target_binding_test()

    print()
    print(
        "PASS - Calendar modify follow-ups are routed and bound correctly."
    )
    print(
        "No external calendar event was modified by this test."
    )
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
