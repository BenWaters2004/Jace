from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request

from sqlalchemy import func, select

from jace.calendar.microsoft_sync import (
    MICROSOFT_CALENDAR_READ_SCOPE,
    _canonical_connection_groups,
    _normalize_event,
)
from jace.calendar.models import (
    CalendarEvent,
    CalendarSource,
)
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal


BASE = "http://127.0.0.1:8000"


def request_json(
    path: str,
    *,
    method: str = "GET",
) -> dict:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        headers={
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=240,
        ) as response:
            return json.loads(
                response.read().decode(
                    "utf-8"
                )
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"{method} {path} returned HTTP {exc.code}: {detail}"
        ) from exc


def normalization_tests() -> None:
    timed = _normalize_event(
        {
            "id": "timed-1",
            "@odata.etag": 'W/"123"',
            "subject": "Project review",
            "isAllDay": False,
            "isCancelled": False,
            "showAs": "busy",
            "sensitivity": "normal",
            "start": {
                "dateTime":
                    "2026-09-17T13:00:00.0000000",
                "timeZone":
                    "UTC",
            },
            "end": {
                "dateTime":
                    "2026-09-17T14:00:00.0000000",
                "timeZone":
                    "UTC",
            },
            "organizer": {
                "emailAddress": {
                    "name": "Example",
                    "address":
                        "example@example.com",
                },
            },
            "attendees": [
                {
                    "type": "required",
                    "status": {
                        "response": "accepted",
                        "time":
                            "2026-09-10T10:00:00Z",
                    },
                    "emailAddress": {
                        "name": "Attendee",
                        "address":
                            "attendee@example.com",
                    },
                }
            ],
        }
    )

    if (
        timed is None
        or timed.all_day
        or timed.start_at is None
        or timed.end_at is None
    ):
        raise RuntimeError(
            "Timed Microsoft event normalization failed."
        )

    all_day = _normalize_event(
        {
            "id": "all-day-1",
            "subject": "Annual leave",
            "isAllDay": True,
            "isCancelled": False,
            "showAs": "free",
            "start": {
                "dateTime":
                    "2026-09-20T00:00:00.0000000",
                "timeZone":
                    "UTC",
            },
            "end": {
                "dateTime":
                    "2026-09-22T00:00:00.0000000",
                "timeZone":
                    "UTC",
            },
        }
    )

    if (
        all_day is None
        or not all_day.all_day
        or str(
            all_day.start_date
        )
        != "2026-09-20"
        or str(
            all_day.end_date_exclusive
        )
        != "2026-09-22"
    ):
        raise RuntimeError(
            "All-day Microsoft event normalization failed."
        )

    print(
        "Microsoft event normalization: PASS"
    )


def normalized_scopes(
    config_json: str,
) -> set[str]:
    config = _loads_object(
        config_json
    )
    raw = config.get(
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


async def scope_test() -> None:
    async with SessionLocal() as session:
        rows = await list_provider_connections(
            session,
            "microsoft",
        )

        configured = [
            row
            for row in rows
            if row.status
            == "configured"
        ]

        if not configured:
            raise RuntimeError(
                "No connected Microsoft account was found."
            )

        if not any(
            MICROSOFT_CALENDAR_READ_SCOPE.casefold()
            in normalized_scopes(
                row.config_json
            )
            for row in configured
        ):
            raise RuntimeError(
                "Calendars.Read is not recorded on a connected Microsoft "
                "account. Reconnect Microsoft after installing Step 4C.4D."
            )

    print(
        "Recorded Microsoft Calendars.Read scope: PASS"
    )


async def source_snapshot() -> tuple[
    int,
    int,
]:
    async with SessionLocal() as session:
        connections = [
            row
            for row in await list_provider_connections(
                session,
                "microsoft",
            )
            if row.status
            == "configured"
        ]

        groups = _canonical_connection_groups(
            connections
        )

        group_by_connection: dict[
            str,
            str,
        ] = {}

        for index, (
            canonical,
            rows,
        ) in enumerate(
            groups
        ):
            group_key = (
                f"group-{index}:"
                f"{canonical.account_hint or canonical.id}"
            )

            for row in rows:
                group_by_connection[
                    str(row.id)
                ] = group_key

        sources = list(
            (
                await session.execute(
                    select(
                        CalendarSource
                    ).where(
                        CalendarSource.provider_id
                        == "microsoft"
                    )
                )
            ).scalars().all()
        )

        seen: set[
            tuple[str, str]
        ] = set()

        for source in sources:
            if (
                not source.connection_id
                or not source.external_calendar_id
            ):
                continue

            key = (
                group_by_connection.get(
                    source.connection_id,
                    f"connection:{source.connection_id}",
                ),
                source.external_calendar_id,
            )

            if key in seen:
                raise RuntimeError(
                    "Duplicate Microsoft calendar source remains: "
                    f"{source.name} / {source.external_calendar_id}"
                )

            seen.add(
                key
            )

        event_count = int(
            (
                await session.execute(
                    select(
                        func.count(
                            CalendarEvent.id
                        )
                    )
                    .join(
                        CalendarSource,
                        CalendarEvent.source_id
                        == CalendarSource.id,
                    )
                    .where(
                        CalendarSource.provider_id
                        == "microsoft",
                        CalendarEvent.deleted_at.is_(
                            None
                        ),
                    )
                )
            ).scalar_one()
        )

    return (
        len(seen),
        event_count,
    )


async def main() -> int:
    print()
    print(
        "Jace Step 4C.4D Microsoft Calendar Sync test"
    )
    print(
        "============================================"
    )
    print()

    normalization_tests()
    await scope_test()

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

    first = request_json(
        "/calendar/sync",
        method="POST",
    )

    providers = first.get(
        "providers",
        [],
    )

    microsoft = next(
        (
            provider
            for provider in providers
            if isinstance(
                provider,
                dict,
            )
            and provider.get(
                "provider_id"
            )
            == "microsoft"
        ),
        None,
    )

    if microsoft is None:
        raise RuntimeError(
            "Microsoft provider result was missing from /calendar/sync."
        )

    if microsoft.get(
        "needs_reconnect"
    ):
        raise RuntimeError(
            "Backend reports Microsoft Calendar needs reconnection."
        )

    if microsoft.get(
        "status"
    ) not in {
        "ok",
        "partial",
    }:
        raise RuntimeError(
            "Microsoft Calendar sync did not complete: "
            + json.dumps(
                microsoft,
                ensure_ascii=False,
            )[:1800]
        )

    if int(
        microsoft.get(
            "calendars_discovered",
            0,
        )
    ) < 1:
        raise RuntimeError(
            "Microsoft Graph did not discover any calendars."
        )

    print(
        "Microsoft calendar discovery: PASS"
    )

    source_count, event_count = await source_snapshot()

    if source_count < 1:
        raise RuntimeError(
            "No Microsoft calendar_sources rows were created."
        )

    print(
        "Microsoft source uniqueness: PASS"
    )
    print(
        "Microsoft event import: PASS"
    )

    # Re-run the real provider sync. Full-window refresh should be idempotent:
    # source count and active event count must remain stable.
    second = request_json(
        "/calendar/sync",
        method="POST",
    )

    second_provider = next(
        (
            provider
            for provider in second.get(
                "providers",
                [],
            )
            if isinstance(
                provider,
                dict,
            )
            and provider.get(
                "provider_id"
            )
            == "microsoft"
        ),
        None,
    )

    if (
        second_provider is None
        or second_provider.get(
            "status"
        )
        not in {
            "ok",
            "partial",
        }
    ):
        raise RuntimeError(
            "Repeated Microsoft Calendar sync failed."
        )

    source_count_2, event_count_2 = (
        await source_snapshot()
    )

    if source_count_2 != source_count:
        raise RuntimeError(
            "Microsoft calendar source count changed after an immediate repeated sync."
        )

    if event_count_2 != event_count:
        raise RuntimeError(
            "Microsoft active event count changed after an immediate repeated sync."
        )

    print(
        "Repeated-sync idempotency: PASS"
    )

    api_sources = request_json(
        "/calendar/sources"
    ).get(
        "sources",
        [],
    )

    microsoft_api_sources = [
        source
        for source in api_sources
        if isinstance(
            source,
            dict,
        )
        and source.get(
            "provider_id"
        )
        == "microsoft"
    ]

    if not microsoft_api_sources:
        raise RuntimeError(
            "Calendar API did not return Microsoft sources."
        )

    print(
        "Unified Calendar API integration: PASS"
    )
    print()
    print(
        "PASS - Step 4C.4D Microsoft Calendar Sync is operational."
    )
    print()
    print(
        f"Microsoft calendars cached: {source_count_2}"
    )
    print(
        f"Active Microsoft events cached: {event_count_2}"
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
