from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from uuid import uuid4
from zoneinfo import ZoneInfo

from jace.calendar.email_enrichment import (
    _extract_details,
    _is_from_gmail,
)
from jace.calendar.models import (
    CalendarEvent,
    CalendarSource,
)
from jace.calendar.preferences import (
    DEFAULT_CALENDAR_TIMEZONE,
    ensure_calendar_preferences,
)
from jace.calendar.schemas import (
    CalendarSourceUpdate,
)
from jace.calendar.service import (
    update_calendar_source,
    upsert_provider_calendar_source,
)
from jace.database import SessionLocal


BASE = "http://127.0.0.1:8000"


def request_json(
    path: str,
) -> dict:
    request = urllib.request.Request(
        BASE + path,
        method="GET",
        headers={
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


def local_logic_tests() -> None:
    source = CalendarSource(
        id=str(uuid4()),
        provider_id="google",
        connection_id="connection-test",
        external_calendar_id="calendar-test",
        name="Calendar test",
        account_hint="test@example.com",
        color="#123456",
        timezone="Europe/London",
        read_only=True,
        enabled=True,
        sync_enabled=True,
        is_primary=False,
        sync_status="synced",
        metadata_json="{}",
    )

    event = CalendarEvent(
        id=str(uuid4()),
        source_id=source.id,
        title="Train to Axminster",
        description=(
            "This event was created from an email you received in Gmail."
        ),
        all_day=False,
        timezone="Europe/London",
        provider_data_json=json.dumps(
            {
                "eventType":
                    "fromGmail",
            }
        ),
        metadata_json="{}",
    )
    event.source = source

    if not _is_from_gmail(
        event
    ):
        raise RuntimeError(
            "fromGmail event detection failed."
        )

    details = _extract_details(
        """
Booking reference: ABC123
Departure: Exeter St Davids
Arrival: Axminster
Coach: C
Seat: 42
"""
    )

    labels = {
        item["label"].casefold()
        for item in details
    }

    if (
        "booking reference"
        not in labels
        or "departure"
        not in labels
        or "arrival"
        not in labels
    ):
        raise RuntimeError(
            "Email detail extraction failed."
        )

    print(
        "Gmail-created event detection: PASS"
    )
    print(
        "Source-email detail extraction: PASS"
    )


async def database_tests() -> None:
    async with SessionLocal() as session:
        preferences = await ensure_calendar_preferences(
            session
        )

        try:
            ZoneInfo(
                preferences.timezone
            )
        except Exception as exc:
            raise RuntimeError(
                "Stored calendar preference is not a valid IANA timezone."
            ) from exc

        if not preferences.timezone:
            raise RuntimeError(
                "Calendar timezone preference is empty."
            )

        print(
            "Calendar timezone preference: PASS "
            f"({preferences.timezone})"
        )

        external_id = (
            "jace-step4c4e-test-"
            + str(uuid4())
        )

        source = await upsert_provider_calendar_source(
            session,
            provider_id="google",
            connection_id="step4c4e-test-connection",
            external_calendar_id=external_id,
            name="Step 4C.4E colour test",
            account_hint="test@example.com",
            color="#112233",
            timezone_name=DEFAULT_CALENDAR_TIMEZONE,
            read_only=True,
            is_primary=False,
            metadata={
                "provider_colour":
                    "#112233",
            },
        )

        await update_calendar_source(
            session,
            source,
            CalendarSourceUpdate(
                color="#A1B2C3",
            ),
        )

        source = await upsert_provider_calendar_source(
            session,
            provider_id="google",
            connection_id="step4c4e-test-connection",
            external_calendar_id=external_id,
            name="Step 4C.4E colour test",
            account_hint="test@example.com",
            color="#445566",
            timezone_name=DEFAULT_CALENDAR_TIMEZONE,
            read_only=True,
            is_primary=False,
            metadata={
                "provider_colour":
                    "#445566",
            },
        )

        if (
            source.color.casefold()
            != "#a1b2c3"
        ):
            raise RuntimeError(
                "User calendar colour was overwritten by a provider refresh."
            )

        metadata = json.loads(
            source.metadata_json
        )

        if (
            str(
                metadata.get(
                    "user_color"
                )
            ).casefold()
            != "#a1b2c3"
        ):
            raise RuntimeError(
                "User calendar colour override was not persisted."
            )

        await session.rollback()

    print(
        "Calendar colour override survives sync: PASS"
    )


async def main() -> int:
    print()
    print(
        "Jace Step 4C.4E Calendar UX + Event Enrichment test"
    )
    print(
        "=================================================="
    )
    print()

    local_logic_tests()
    await database_tests()

    health = request_json(
        "/health"
    )

    if health.get(
        "status"
    ) != "ok":
        raise RuntimeError(
            "Jace backend health check failed."
        )

    print(
        "Backend health: PASS"
    )

    preferences = request_json(
        "/calendar/preferences"
    )

    try:
        ZoneInfo(
            str(
                preferences.get(
                    "timezone"
                )
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "/calendar/preferences returned an invalid timezone."
        ) from exc

    status = request_json(
        "/calendar/status"
    )

    if (
        status.get(
            "timezone"
        )
        != preferences.get(
            "timezone"
        )
    ):
        raise RuntimeError(
            "Calendar status and Calendar preferences disagree on timezone."
        )

    print(
        "Calendar preferences API: PASS"
    )
    print(
        "Calendar display timezone wiring: PASS"
    )
    print()
    print(
        "PASS - Step 4C.4E backend calendar UX foundations are operational."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            asyncio.run(main())
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
