from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from jace.calendar.write_continuation import (
    calendar_capability_message,
    is_explicit_write_continuation,
)
from jace.calendar.write_routing import (
    compact_calendar_write_tools,
)
from jace.capabilities.runtime import (
    resolve_runtime_capabilities,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.calendar_write_flat import (
    CalendarCreateFlatInput,
    to_calendar_create_input,
)
from jace.tools.registry import registry


ORIGINAL = """Schedule a Google Calendar meeting called "Jace scheduling test"
tomorrow from 3pm to 3:30pm.
Invite test@example.com as required.
Repeat it every week for 3 occurrences.
Remind me 10 minutes before.
Add a Google Meet."""


def flat_schema_tests() -> None:
    ensure_tools_registered()

    tool = registry.get(
        "google_calendar_create_event"
    )

    if tool is None:
        raise RuntimeError(
            "google_calendar_create_event is not registered."
        )

    if tool.input_model is not CalendarCreateFlatInput:
        raise RuntimeError(
            "Google create tool is not using the flat scheduling schema."
        )

    schema = tool.input_model.model_json_schema()

    if "$defs" in schema:
        raise RuntimeError(
            "Flat Calendar create schema unexpectedly contains nested $defs."
        )

    properties = schema.get(
        "properties",
        {},
    )

    required_fields = {
        "title",
        "start_at",
        "end_at",
        "attendee_emails",
        "recurrence_frequency",
        "recurrence_count",
        "reminder_minutes",
        "add_online_meeting",
    }

    missing = (
        required_fields
        - set(
            properties
        )
    )

    if missing:
        raise RuntimeError(
            f"Flat schema is missing fields: {sorted(missing)}"
        )

    data = CalendarCreateFlatInput(
        title="Jace scheduling test",
        start_at=datetime(
            2026,
            9,
            18,
            15,
            0,
        ),
        end_at=datetime(
            2026,
            9,
            18,
            15,
            30,
        ),
        timezone="Europe/London",
        attendee_emails=[
            "test@example.com",
        ],
        recurrence_frequency="weekly",
        recurrence_count=3,
        reminder_minutes=[
            10,
        ],
        add_online_meeting=True,
    )

    nested = to_calendar_create_input(
        data,
        provider_id="google",
    )

    if (
        len(
            nested.attendees
        )
        != 1
        or nested.attendees[
            0
        ].email
        != "test@example.com"
    ):
        raise RuntimeError(
            "Flat attendee conversion failed."
        )

    if (
        nested.recurrence is None
        or nested.recurrence.frequency
        != "weekly"
        or nested.recurrence.count
        != 3
    ):
        raise RuntimeError(
            "Flat recurrence conversion failed."
        )

    if (
        nested.reminders is None
        or nested.reminders[
            0
        ].minutes_before_start
        != 10
    ):
        raise RuntimeError(
            "Flat reminder conversion failed."
        )

    if (
        nested.online_meeting
        != "google_meet"
    ):
        raise RuntimeError(
            "Flat online-meeting conversion failed."
        )

    print(
        "Flat model-facing Calendar create schema: PASS"
    )
    print(
        "Flat → rich provider scheduling conversion: PASS"
    )


def continuation_tests() -> None:
    history_retry = [
        {
            "role":
                "user",
            "content":
                ORIGINAL,
        },
        {
            "role":
                "assistant",
            "content":
                (
                    "The recurrence parameter needs to be a proper object "
                    "structure. Let me try again."
                ),
        },
        {
            "role":
                "user",
            "content":
                "Okay try again",
        },
    ]

    effective = calendar_capability_message(
        "Okay try again",
        history_retry,
    )

    if (
        ORIGINAL
        not in effective
        or "Okay try again"
        not in effective
    ):
        raise RuntimeError(
            "Explicit retry did not inherit the unresolved Calendar write."
        )

    history_confirm = [
        {
            "role":
                "user",
            "content":
                ORIGINAL,
        },
        {
            "role":
                "assistant",
            "content":
                "The recurrence format failed; I need to try again.",
        },
        {
            "role":
                "user",
            "content":
                "Okay try again",
        },
        {
            "role":
                "assistant",
            "content":
                "Is tomorrow still good? Please confirm before I proceed.",
        },
        {
            "role":
                "user",
            "content":
                "Tomorrow is good",
        },
    ]

    effective_confirm = calendar_capability_message(
        "Tomorrow is good",
        history_confirm,
    )

    if ORIGINAL not in effective_confirm:
        raise RuntimeError(
            "Explicit date confirmation did not inherit Calendar write intent."
        )

    history_complaint = [
        {
            "role":
                "user",
            "content":
                ORIGINAL,
        },
        {
            "role":
                "assistant",
            "content":
                "I tried to schedule it.",
        },
        {
            "role":
                "user",
            "content":
                "Still not there",
        },
    ]

    complaint = calendar_capability_message(
        "Still not there",
        history_complaint,
    )

    if complaint != "Still not there":
        raise RuntimeError(
            "A complaint unexpectedly re-authorized a Calendar write."
        )

    if not is_explicit_write_continuation(
        "Tomorrow is good"
    ):
        raise RuntimeError(
            "Expected confirmation phrase was not recognised."
        )

    print(
        "Explicit retry carries unresolved Calendar capability: PASS"
    )
    print(
        "Explicit confirmation carries unresolved Calendar capability: PASS"
    )
    print(
        "Complaint does not silently retry write: PASS"
    )


async def runtime_tests() -> None:
    history = [
        {
            "role":
                "user",
            "content":
                ORIGINAL,
        },
        {
            "role":
                "assistant",
            "content":
                "The recurrence parameter format failed. Should I try again?",
        },
        {
            "role":
                "user",
            "content":
                "Okay try again",
        },
    ]

    effective = calendar_capability_message(
        "Okay try again",
        history,
    )

    async with SessionLocal() as session:
        plan = await resolve_runtime_capabilities(
            session,
            effective,
        )

    resolution = next(
        (
            item
            for item in plan.resolutions
            if item.capability_id
            == "calendar.create"
        ),
        None,
    )

    if resolution is None:
        raise RuntimeError(
            "Continuation capability plan omitted calendar.create."
        )

    print(
        "Continuation runtime resolution: "
        f"{resolution.status} via "
        f"{resolution.provider_id or 'no provider'} / "
        f"{resolution.account_hint or 'no account'}"
    )

    if resolution.status != "ready":
        raise RuntimeError(
            "calendar.create is not READY on the inherited continuation. "
            f"Reason: {resolution.reason}"
        )

    if (
        resolution.tool_name
        != "google_calendar_create_event"
    ):
        raise RuntimeError(
            "Continuation did not resolve to google_calendar_create_event."
        )

    noisy = {
        "calendar_list_events",
        "calendar_next_event",
        "calendar_free_busy",
        "calendar_check_conflicts",
        "calendar_find_open_slots",
        "current_datetime",
        "google_calendar_create_event",
    }

    compact = compact_calendar_write_tools(
        effective,
        noisy,
        plan.tool_names,
    )

    expected = {
        "current_datetime",
        "google_calendar_create_event",
    }

    if set(
        compact
    ) != expected:
        raise RuntimeError(
            "Continuation did not compact to the focused Google create tools. "
            f"Got: {compact}"
        )

    print(
        "Continuation provider write injection: PASS"
    )
    print(
        "Continuation focused tool compaction: PASS"
    )


async def main() -> int:
    print()
    print(
        "Jace Step 4C.5B v2 Reliable Scheduling test"
    )
    print(
        "============================================="
    )
    print()

    flat_schema_tests()
    continuation_tests()
    await runtime_tests()

    print()
    print(
        "PASS - 4C.5B v2 reliable scheduling is configured."
    )
    print(
        "No Calendar event or invitation was written by this test."
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
