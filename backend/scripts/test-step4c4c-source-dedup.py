from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

from sqlalchemy import select

from jace.calendar.models import (
    CalendarSource,
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

    with urllib.request.urlopen(
        request,
        timeout=180,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


async def assert_source_identity() -> int:
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        CalendarSource
                    )
                    .where(
                        CalendarSource.provider_id
                        == "google"
                    )
                    .order_by(
                        CalendarSource.name,
                        CalendarSource.external_calendar_id,
                    )
                )
            ).scalars().all()
        )

    seen: dict[
        str,
        CalendarSource,
    ] = {}

    for source in rows:
        external_id = (
            source.external_calendar_id
        )

        if not external_id:
            continue

        if external_id in seen:
            first = seen[
                external_id
            ]

            raise RuntimeError(
                "Duplicate Google calendar source remains for calendarId "
                f"{external_id!r}: {first.name!r} and {source.name!r}."
            )

        seen[
            external_id
        ] = source

    print(
        "Google calendarId uniqueness: PASS"
    )

    return len(
        seen
    )


async def main() -> int:
    print()
    print(
        "Jace Step 4C.4C Google source-dedup v3 test"
    )
    print(
        "=========================================="
    )
    print()

    health = request_json(
        "/health"
    )

    if health.get(
        "status"
    ) != "ok":
        raise RuntimeError(
            "Jace backend is not healthy."
        )

    print(
        "Backend health: PASS"
    )

    first = request_json(
        "/calendar/sync",
        method="POST",
    )

    if first.get(
        "status"
    ) not in {
        "ok",
        "partial",
    }:
        raise RuntimeError(
            "First Google Calendar sync failed: "
            + json.dumps(
                first,
                ensure_ascii=False,
            )[:1500]
        )

    count = await assert_source_identity()

    api_sources = request_json(
        "/calendar/sources"
    ).get(
        "sources",
        [],
    )

    api_google = [
        source
        for source in api_sources
        if isinstance(
            source,
            dict,
        )
        and source.get(
            "provider_id"
        )
        == "google"
    ]

    api_ids = [
        source.get(
            "external_calendar_id"
        )
        for source in api_google
        if source.get(
            "external_calendar_id"
        )
    ]

    if len(
        api_ids
    ) != len(
        set(
            api_ids
        )
    ):
        raise RuntimeError(
            "GET /calendar/sources still returns duplicate Google calendar IDs."
        )

    print(
        "Calendar API source uniqueness: PASS"
    )

    # Run again to prove normal incremental refresh does not recreate sources.
    second = request_json(
        "/calendar/sync",
        method="POST",
    )

    if second.get(
        "status"
    ) not in {
        "ok",
        "partial",
    }:
        raise RuntimeError(
            "Second Google Calendar sync failed."
        )

    second_count = await assert_source_identity()

    if second_count != count:
        raise RuntimeError(
            "Google calendar source count changed after an immediate repeated sync."
        )

    print(
        "Repeated-sync source stability: PASS"
    )
    print()
    print(
        "PASS - Google calendar sidebar source deduplication is operational."
    )
    print()
    print(
        f"Unique Google calendars currently cached: {second_count}"
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
