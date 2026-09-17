from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from jace.capabilities.runtime import detect_capability_needs
from jace.connections.providers import (
    GOOGLE,
    MICROSOFT,
)
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.calendar_write_common import (
    CalendarCreateEventInput,
    CalendarModifyEventInput,
)
from jace.tools.google_calendar_write import (
    _create_payload as google_create_payload,
)
from jace.tools.microsoft_calendar_write import (
    _create_payload as microsoft_create_payload,
)
from jace.tools.registry import registry


GOOGLE_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events"
)
MICROSOFT_SCOPE = (
    "Calendars.ReadWrite"
)

EXPECTED = {
    "google_calendar_create_event": (
        "google",
        "calendar.create",
    ),
    "google_calendar_modify_event": (
        "google",
        "calendar.modify",
    ),
    "microsoft_calendar_create_event": (
        "microsoft",
        "calendar.create",
    ),
    "microsoft_calendar_modify_event": (
        "microsoft",
        "calendar.modify",
    ),
}


def _capability(
    provider,
    capability_id: str,
):
    return next(
        item
        for item in provider.capabilities
        if item.id
        == capability_id
    )


def registration_tests() -> None:
    ensure_tools_registered()

    for name, (
        provider_id,
        capability_id,
    ) in EXPECTED.items():
        tool = registry.get(
            name
        )

        if tool is None:
            raise RuntimeError(
                f"{name} was not registered."
            )

        if (
            tool.provider_id
            != provider_id
            or tool.capability_id
            != capability_id
        ):
            raise RuntimeError(
                f"{name} has the wrong provider/capability binding."
            )

        if (
            tool.risk
            != "write"
            or tool.default_permission
            != "ask"
        ):
            raise RuntimeError(
                f"{name} is not guarded as an Ask/write tool."
            )

    print(
        "External Calendar write tool registration: PASS"
    )
    print(
        "Write tools default to Ask: PASS"
    )


def provider_definition_tests() -> None:
    if (
        GOOGLE_SCOPE
        not in GOOGLE.oauth_scopes
    ):
        raise RuntimeError(
            "Google OAuth does not request calendar.events."
        )

    if (
        MICROSOFT_SCOPE
        not in MICROSOFT.oauth_scopes
    ):
        raise RuntimeError(
            "Microsoft OAuth does not request Calendars.ReadWrite."
        )

    expected = [
        (
            GOOGLE,
            "calendar.create",
            "google_calendar_create_event",
        ),
        (
            GOOGLE,
            "calendar.modify",
            "google_calendar_modify_event",
        ),
        (
            MICROSOFT,
            "calendar.create",
            "microsoft_calendar_create_event",
        ),
        (
            MICROSOFT,
            "calendar.modify",
            "microsoft_calendar_modify_event",
        ),
    ]

    for (
        provider,
        capability_id,
        tool_name,
    ) in expected:
        capability = _capability(
            provider,
            capability_id,
        )

        if (
            capability.tool_name
            != tool_name
        ):
            raise RuntimeError(
                f"{provider.id} {capability_id} tool_name is incorrect."
            )

        if (
            capability.default_permission
            != "ask"
        ):
            raise RuntimeError(
                f"{provider.id} {capability_id} must default to Ask."
            )

    print(
        "Provider Calendar write capabilities: PASS"
    )


def routing_tests() -> None:
    create_needs = {
        need.capability_id
        for need in detect_capability_needs(
            "Add a dentist appointment to my Google Calendar tomorrow."
        )
    }

    modify_needs = {
        need.capability_id
        for need in detect_capability_needs(
            "Delete the dentist appointment from my Outlook calendar."
        )
    }

    if (
        "calendar.create"
        not in create_needs
    ):
        raise RuntimeError(
            "Calendar create intent was not detected."
        )

    if (
        "calendar.modify"
        not in modify_needs
    ):
        raise RuntimeError(
            "Calendar delete/modify intent was not detected."
        )

    print(
        "Calendar create/modify intent detection: PASS"
    )


def payload_tests() -> None:
    timed = CalendarCreateEventInput(
        title="4C.5A timed test",
        start_at=datetime(
            2026,
            9,
            18,
            10,
            0,
        ),
        end_at=datetime(
            2026,
            9,
            18,
            11,
            0,
        ),
        timezone="Europe/London",
    )

    google = google_create_payload(
        timed,
        "Europe/London",
    )

    if (
        "dateTime"
        not in google[
            "start"
        ]
        or google[
            "start"
        ][
            "timeZone"
        ]
        != "Europe/London"
    ):
        raise RuntimeError(
            "Google timed-event payload is incorrect."
        )

    microsoft = microsoft_create_payload(
        timed,
        "Europe/London",
    )

    if (
        microsoft[
            "start"
        ][
            "timeZone"
        ]
        != "UTC"
        or microsoft[
            "isAllDay"
        ]
    ):
        raise RuntimeError(
            "Microsoft timed-event payload is incorrect."
        )

    all_day = CalendarCreateEventInput(
        title="4C.5A all-day test",
        all_day=True,
        start_date=date(
            2026,
            9,
            18,
        ),
        end_date_exclusive=date(
            2026,
            9,
            20,
        ),
    )

    google_all_day = google_create_payload(
        all_day,
        "Europe/London",
    )

    if (
        google_all_day[
            "start"
        ].get(
            "date"
        )
        != "2026-09-18"
        or google_all_day[
            "end"
        ].get(
            "date"
        )
        != "2026-09-20"
    ):
        raise RuntimeError(
            "Google all-day payload is incorrect."
        )

    microsoft_all_day = microsoft_create_payload(
        all_day,
        "Europe/London",
    )

    if (
        not microsoft_all_day[
            "isAllDay"
        ]
        or not microsoft_all_day[
            "start"
        ][
            "dateTime"
        ].startswith(
            "2026-09-18"
        )
    ):
        raise RuntimeError(
            "Microsoft all-day payload is incorrect."
        )

    CalendarModifyEventInput(
        event_id="local-event-id",
        action="update",
        title="Updated title",
    )

    CalendarModifyEventInput(
        event_id="local-event-id",
        action="delete",
    )

    print(
        "Google/Microsoft event payload generation: PASS"
    )
    print(
        "Create/update/delete input validation: PASS"
    )


def _normalized_scopes(
    config_json: str,
) -> set[str]:
    payload = _loads_object(
        config_json
    )
    raw = payload.get(
        "scopes",
        [],
    )

    if not isinstance(
        raw,
        list,
    ):
        return set()

    result: set[str] = set()

    for value in raw:
        if not isinstance(
            value,
            str,
        ):
            continue

        cleaned = value.strip().casefold()

        if not cleaned:
            continue

        result.add(
            cleaned
        )

        if "/" in cleaned:
            result.add(
                cleaned.rsplit(
                    "/",
                    1,
                )[-1]
            )

    return result


async def connection_scope_tests() -> None:
    async with SessionLocal() as session:
        for (
            provider_id,
            required_scope,
        ) in (
            (
                "google",
                GOOGLE_SCOPE,
            ),
            (
                "microsoft",
                MICROSOFT_SCOPE,
            ),
        ):
            rows = await list_provider_connections(
                session,
                provider_id,
            )
            configured = [
                row
                for row in rows
                if row.status
                == "configured"
            ]

            if not configured:
                print(
                    f"{provider_id}: no configured account; live scope check skipped."
                )
                continue

            if not any(
                required_scope.casefold()
                in _normalized_scopes(
                    row.config_json
                )
                for row in configured
            ):
                raise RuntimeError(
                    f"{provider_id} is connected but does not record "
                    f"{required_scope}. Reconnect the account after adding "
                    "the Calendar write permission."
                )

            print(
                f"{provider_id} recorded Calendar write scope: PASS"
            )


async def main() -> int:
    print()
    print(
        "Jace Step 4C.5A External Calendar Write Core test"
    )
    print(
        "================================================"
    )
    print()

    registration_tests()
    provider_definition_tests()
    routing_tests()
    payload_tests()
    await connection_scope_tests()

    print()
    print(
        "PASS - Step 4C.5A Calendar Write Core is configured."
    )
    print(
        "No external calendar event was created, changed, or deleted by this test."
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
