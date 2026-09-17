from __future__ import annotations

import sys
from datetime import date, datetime

from pydantic import ValidationError

from jace.capabilities.runtime import detect_capability_needs
from jace.calendar.models import CalendarSource
from jace.tools import ensure_tools_registered
from jace.tools.calendar_write_common import (
    CalendarAttendeeInput,
    CalendarCreateEventInput,
    CalendarModifyEventInput,
    CalendarRecurrenceInput,
    CalendarReminderInput,
)
from jace.tools.google_calendar_write import (
    _base_create as google_create_payload,
    _base_update as google_update_payload,
    _google_meet_supported,
)
from jace.tools.microsoft_calendar_write import (
    _base_create as microsoft_create_payload,
    _recurrence_payload as microsoft_recurrence_payload,
    _reminder_payload as microsoft_reminder_payload,
    _teams_supported,
    _validate_notifications,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


WRITE_TOOLS = {
    "google_calendar_create_event",
    "google_calendar_modify_event",
    "microsoft_calendar_create_event",
    "microsoft_calendar_modify_event",
}


def source(
    provider: str,
    metadata: str,
) -> CalendarSource:
    return CalendarSource(
        id=f"{provider}-test-source",
        provider_id=provider,
        connection_id=f"{provider}-connection",
        external_calendar_id="calendar-id",
        name="Test Calendar",
        account_hint="test@example.com",
        color="#7489c8",
        timezone="Europe/London",
        read_only=False,
        enabled=True,
        sync_enabled=True,
        is_primary=True,
        sync_status="synced",
        metadata_json=metadata,
    )


def model_tests() -> None:
    recurrence = CalendarRecurrenceInput(
        frequency="weekly",
        weekdays=["monday", "wednesday"],
        count=6,
    )

    create = CalendarCreateEventInput(
        title="Jace scheduling test",
        start_at=datetime(2026, 10, 19, 9, 0),
        end_at=datetime(2026, 10, 19, 10, 0),
        timezone="Europe/London",
        attendees=[
            CalendarAttendeeInput(
                email="required@example.com",
                type="required",
            ),
            CalendarAttendeeInput(
                email="optional@example.com",
                name="Optional Person",
                type="optional",
            ),
        ],
        reminders=[
            CalendarReminderInput(
                minutes_before_start=15,
                method="popup",
            )
        ],
        recurrence=recurrence,
        online_meeting="google_meet",
    )

    if len(create.attendees) != 2:
        raise RuntimeError("Attendee input validation failed.")

    try:
        CalendarCreateEventInput(
            title="Duplicate attendees",
            start_at=datetime(2026, 10, 19, 9, 0),
            end_at=datetime(2026, 10, 19, 10, 0),
            attendees=[
                CalendarAttendeeInput(
                    email="same@example.com",
                ),
                CalendarAttendeeInput(
                    email="SAME@example.com",
                ),
            ],
        )
    except ValidationError:
        pass
    else:
        raise RuntimeError("Duplicate attendee validation did not fire.")

    try:
        CalendarRecurrenceInput(
            frequency="weekly",
            count=4,
            until=date(2026, 12, 1),
        )
    except ValidationError:
        pass
    else:
        raise RuntimeError("Recurrence count/until validation did not fire.")

    try:
        CalendarModifyEventInput(
            event_id="event-id",
            recurrence=recurrence,
            recurrence_scope="single",
        )
    except ValidationError:
        pass
    else:
        raise RuntimeError("Series-scope recurrence guard did not fire.")

    print("Scheduling input validation: PASS")


def google_payload_tests() -> None:
    google_source = source(
        "google",
        (
            '{"allowed_conference_solution_types":'
            '["hangoutsMeet"]}'
        ),
    )

    data = CalendarCreateEventInput(
        title="Weekly Google meeting",
        start_at=datetime(2026, 10, 19, 9, 0),
        end_at=datetime(2026, 10, 19, 10, 0),
        timezone="Europe/London",
        attendees=[
            CalendarAttendeeInput(
                email="required@example.com",
                type="required",
            ),
            CalendarAttendeeInput(
                email="optional@example.com",
                type="optional",
            ),
        ],
        reminders=[
            CalendarReminderInput(
                minutes_before_start=10,
                method="popup",
            ),
        ],
        recurrence=CalendarRecurrenceInput(
            frequency="weekly",
            weekdays=["monday"],
            count=3,
        ),
        online_meeting="google_meet",
    )

    payload = google_create_payload(
        data,
        "Europe/London",
        meet_supported=_google_meet_supported(
            google_source
        ),
    )

    if (
        payload["start"]["timeZone"]
        != "Europe/London"
    ):
        raise RuntimeError("Google timezone was not preserved.")

    if (
        payload["attendees"][1].get(
            "optional"
        )
        is not True
    ):
        raise RuntimeError("Google optional attendee mapping failed.")

    rule = payload["recurrence"][0]

    if (
        "FREQ=WEEKLY" not in rule
        or "BYDAY=MO" not in rule
        or "COUNT=3" not in rule
    ):
        raise RuntimeError("Google RRULE generation failed.")

    if (
        payload["reminders"]["overrides"][0]["minutes"]
        != 10
    ):
        raise RuntimeError("Google reminder mapping failed.")

    if (
        payload["conferenceData"]["createRequest"]
        ["conferenceSolutionKey"]["type"]
        != "hangoutsMeet"
    ):
        raise RuntimeError("Google Meet payload failed.")

    update = CalendarModifyEventInput(
        event_id="event-id",
        title="Updated",
    )
    update_payload = google_update_payload(
        update,
        "Europe/London",
        meet_supported=True,
    )

    if "attendees" in update_payload:
        raise RuntimeError(
            "Omitted attendees should be preserved, not cleared."
        )

    print("Google scheduling payload generation: PASS")


def microsoft_payload_tests() -> None:
    microsoft_source = source(
        "microsoft",
        (
            '{"allowed_online_meeting_providers":'
            '["teamsForBusiness"],'
            '"default_online_meeting_provider":"teamsForBusiness"}'
        ),
    )

    data = CalendarCreateEventInput(
        title="Weekly Teams meeting",
        start_at=datetime(2026, 10, 19, 9, 0),
        end_at=datetime(2026, 10, 19, 10, 0),
        timezone="Europe/London",
        attendees=[
            CalendarAttendeeInput(
                email="required@example.com",
                type="required",
            ),
            CalendarAttendeeInput(
                email="room@example.com",
                name="Meeting Room",
                type="resource",
            ),
        ],
        reminders=[
            CalendarReminderInput(
                minutes_before_start=15,
                method="popup",
            ),
        ],
        recurrence=CalendarRecurrenceInput(
            frequency="weekly",
            weekdays=["monday", "wednesday"],
            count=5,
        ),
        online_meeting="microsoft_teams",
    )

    payload = microsoft_create_payload(
        data,
        "Europe/London",
        microsoft_source,
    )

    if payload["start"]["timeZone"] != "Europe/London":
        raise RuntimeError(
            "Microsoft timed event was flattened to UTC instead of Europe/London."
        )

    if (
        payload["attendees"][1]["type"]
        != "resource"
    ):
        raise RuntimeError("Microsoft resource attendee mapping failed.")

    if (
        payload["recurrence"]["pattern"]["type"]
        != "weekly"
        or payload["recurrence"]["range"]["type"]
        != "numbered"
    ):
        raise RuntimeError("Microsoft recurrence payload failed.")

    if payload.get("onlineMeetingProvider") != "teamsForBusiness":
        raise RuntimeError("Microsoft Teams payload failed.")

    if payload.get("reminderMinutesBeforeStart") != 15:
        raise RuntimeError("Microsoft reminder payload failed.")

    try:
        microsoft_reminder_payload(
            [
                CalendarReminderInput(
                    minutes_before_start=5,
                ),
                CalendarReminderInput(
                    minutes_before_start=15,
                ),
            ]
        )
    except Exception:
        pass
    else:
        raise RuntimeError(
            "Microsoft multiple-reminder safety did not fire."
        )

    try:
        _validate_notifications(
            attendee_count=1,
            notify_attendees=False,
        )
    except Exception:
        pass
    else:
        raise RuntimeError(
            "Microsoft silent-attendee safety did not fire."
        )

    if not _teams_supported(microsoft_source):
        raise RuntimeError("Teams support metadata check failed.")

    print("Microsoft scheduling payload generation: PASS")
    print("Microsoft Europe/London recurrence timezone: PASS")
    print("Microsoft attendee notification safety: PASS")


def routing_and_registration_tests() -> None:
    ensure_tools_registered()

    for name in WRITE_TOOLS:
        tool = registry.get(name)
        if tool is None:
            raise RuntimeError(f"{name} was not registered.")
        if tool.risk != "write" or tool.default_permission != "ask":
            raise RuntimeError(
                f"{name} must remain write/Ask."
            )

    needs = {
        item.capability_id
        for item in detect_capability_needs(
            'Invite bob@example.com to "Jace scheduling test".'
        )
    }

    if "calendar.modify" not in needs:
        raise RuntimeError(
            "Invite/attendee request did not resolve calendar.modify."
        )

    routed = route_tool_names(
        'Add a 10 minute reminder to "Jace scheduling test".'
    )

    if "calendar_find_event" not in routed:
        raise RuntimeError(
            "Scheduling modification did not route calendar_find_event."
        )

    print("External scheduling tools remain Ask/write: PASS")
    print("Scheduling capability detection: PASS")
    print("Scheduling event lookup routing: PASS")


def main() -> int:
    print()
    print("Jace Step 4C.5B Scheduling & Invitations test")
    print("===============================================")
    print()

    model_tests()
    google_payload_tests()
    microsoft_payload_tests()
    routing_and_registration_tests()

    print()
    print(
        "PASS - Step 4C.5B Scheduling & Invitations is configured."
    )
    print(
        "No external invitations, events, series or reminders were written by this test."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print()
        print(f"FAIL - {exc}", file=sys.stderr)
        print()
        raise
