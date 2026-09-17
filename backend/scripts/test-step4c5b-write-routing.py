from __future__ import annotations

import asyncio
import sys

from jace.calendar.write_routing import (
    calendar_write_kind,
    compact_calendar_write_tools,
)
from jace.capabilities.runtime import (
    detect_capability_needs,
    resolve_runtime_capabilities,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.agent import (
    _calendar_write_request,
    _looks_like_write_success,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


PROMPT = """Schedule a Google Calendar meeting called "Jace scheduling test"
tomorrow from 3pm to 3:30pm.
Invite test@example.com as required.
Repeat it every week for 3 occurrences.
Remind me 10 minutes before.
Add a Google Meet."""


def classification_tests() -> None:
    kind = calendar_write_kind(PROMPT)

    if kind != "create":
        raise RuntimeError(
            f"Expected Calendar create intent, got {kind!r}."
        )

    needs = detect_capability_needs(PROMPT)
    create = [
        item
        for item in needs
        if item.capability_id == "calendar.create"
    ]

    if len(create) != 1:
        raise RuntimeError(
            "The exact scheduling prompt did not produce calendar.create."
        )

    if create[0].preferred_provider != "google":
        raise RuntimeError(
            "The exact scheduling prompt did not prefer Google."
        )

    if not _calendar_write_request(PROMPT):
        raise RuntimeError(
            "The exact scheduling prompt was not protected as a Calendar write."
        )

    print("Exact scheduling prompt → calendar.create: PASS")
    print("Explicit Google provider preference: PASS")
    print("Calendar write completion guard detection: PASS")


def compaction_tests() -> None:
    noisy = {
        "list_automations",
        "create_automation",
        "calendar_list_events",
        "calendar_next_event",
        "calendar_free_busy",
        "calendar_check_conflicts",
        "calendar_find_open_slots",
        "current_datetime",
        "google_calendar_create_event",
    }

    compact = compact_calendar_write_tools(
        PROMPT,
        noisy,
        ["google_calendar_create_event"],
    )

    expected = {
        "current_datetime",
        "google_calendar_create_event",
    }

    if set(compact) != expected:
        raise RuntimeError(
            "Focused Calendar-create tool set was wrong. "
            f"Expected {sorted(expected)}, got {compact}."
        )

    routed = route_tool_names(PROMPT)

    if "create_automation" in routed:
        raise RuntimeError(
            'The word "Schedule" still routed create_automation for a '
            "Calendar meeting."
        )

    print("Focused provider-write tool compaction: PASS")
    print("Calendar schedule ≠ Automation routing: PASS")


def completion_claim_tests() -> None:
    claims = [
        "Alright, boss. I got this scheduled on your Google Calendar.",
        "The event is all set.",
        "I've booked the meeting.",
        "The meeting was successfully added.",
    ]

    for claim in claims:
        if not _looks_like_write_success(claim):
            raise RuntimeError(
                f"False-success detector missed: {claim}"
            )

    failure = (
        "I didn't complete the calendar change because no provider "
        "write tool completed successfully."
    )

    if _looks_like_write_success(failure):
        raise RuntimeError(
            "A truthful write-failure message was classified as success."
        )

    print("Scheduled/booked/all-set false-success guard: PASS")
    print("Truthful write-failure classification: PASS")


def registration_tests() -> None:
    ensure_tools_registered()

    tool = registry.get(
        "google_calendar_create_event"
    )

    if tool is None:
        raise RuntimeError(
            "google_calendar_create_event is not registered."
        )

    if (
        tool.provider_id != "google"
        or tool.capability_id != "calendar.create"
    ):
        raise RuntimeError(
            "Google Calendar create tool has the wrong capability binding."
        )

    schema = tool.input_model.model_json_schema()
    properties = schema.get(
        "properties",
        {},
    )

    for field in (
        "attendees",
        "recurrence",
        "reminders",
        "online_meeting",
    ):
        if field not in properties:
            raise RuntimeError(
                f"4C.5B field {field!r} is missing from the Google create schema."
            )

    print("Google provider write tool registration: PASS")
    print("4C.5B scheduling fields exposed to model: PASS")


async def live_capability_test() -> None:
    async with SessionLocal() as session:
        plan = await resolve_runtime_capabilities(
            session,
            PROMPT,
        )

    resolution = next(
        (
            item
            for item in plan.resolutions
            if item.capability_id == "calendar.create"
        ),
        None,
    )

    if resolution is None:
        raise RuntimeError(
            "Runtime capability plan omitted calendar.create."
        )

    print(
        "Runtime calendar.create resolution: "
        f"{resolution.status} via "
        f"{resolution.provider_id or 'no provider'} / "
        f"{resolution.account_hint or 'no account'}"
    )

    if resolution.status != "ready":
        missing = ", ".join(
            resolution.missing_scopes
        )
        suffix = (
            f" Missing scopes: {missing}."
            if missing
            else ""
        )
        raise RuntimeError(
            "calendar.create is not READY for the exact prompt. "
            f"Reason: {resolution.reason}.{suffix}"
        )

    if (
        resolution.provider_id != "google"
        or resolution.tool_name
        != "google_calendar_create_event"
    ):
        raise RuntimeError(
            "READY calendar.create did not resolve to the Google create tool."
        )

    if (
        "google_calendar_create_event"
        not in plan.tool_names
    ):
        raise RuntimeError(
            "Runtime capability plan did not expose google_calendar_create_event."
        )

    print("Runtime provider write injection: PASS")


async def main() -> int:
    print()
    print(
        "Jace Step 4C.5B Deterministic Calendar Write Routing test"
    )
    print(
        "========================================================="
    )
    print()

    classification_tests()
    compaction_tests()
    completion_claim_tests()
    registration_tests()
    await live_capability_test()

    print()
    print(
        "PASS - the exact Scheduling & Invitations regression prompt "
        "resolves to a focused, executable Google Calendar write turn."
    )
    print(
        "No calendar event or invitation was written by this test."
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
