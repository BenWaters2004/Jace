from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

from sqlalchemy import select

from jace.calendar.google_sync import _canonical_google_connection_groups
from jace.calendar.models import CalendarEvent, CalendarSource
from jace.connections.service import list_provider_connections
from jace.database import SessionLocal

BASE = "http://127.0.0.1:8000"


def request_json(path: str, *, method: str = "GET") -> dict:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


async def assert_no_duplicates() -> None:
    async with SessionLocal() as session:
        connections = [
            row
            for row in await list_provider_connections(session, "google")
            if row.status == "configured"
        ]

        groups = _canonical_google_connection_groups(connections)
        group_by_connection_id: dict[str, str] = {}

        for index, (canonical, rows) in enumerate(groups):
            logical_key = f"group-{index}:{canonical.account_hint or canonical.id}"
            for row in rows:
                group_by_connection_id[str(row.id)] = logical_key

        sources = list(
            (
                await session.execute(
                    select(CalendarSource).where(
                        CalendarSource.provider_id == "google"
                    )
                )
            ).scalars().all()
        )

        seen_sources: dict[tuple[str, str], str] = {}

        for source in sources:
            if not source.connection_id or not source.external_calendar_id:
                continue

            group_key = group_by_connection_id.get(
                source.connection_id,
                f"connection:{source.connection_id}",
            )
            key = (group_key, source.external_calendar_id)

            if key in seen_sources:
                raise RuntimeError(
                    "Duplicate Google calendar source remains: "
                    f"{source.name} / {source.external_calendar_id}"
                )

            seen_sources[key] = source.id

        event_rows = list(
            (
                await session.execute(
                    select(CalendarEvent, CalendarSource)
                    .join(CalendarSource, CalendarEvent.source_id == CalendarSource.id)
                    .where(
                        CalendarSource.provider_id == "google",
                        CalendarEvent.deleted_at.is_(None),
                    )
                )
            ).all()
        )

        seen_events: set[tuple[str, str, str]] = set()

        for event, source in event_rows:
            if (
                not source.connection_id
                or not source.external_calendar_id
                or not event.external_event_id
            ):
                continue

            group_key = group_by_connection_id.get(
                source.connection_id,
                f"connection:{source.connection_id}",
            )
            key = (
                group_key,
                source.external_calendar_id,
                event.external_event_id,
            )

            if key in seen_events:
                raise RuntimeError(
                    "Duplicate Google event remains: "
                    f"{event.title} / {event.external_event_id}"
                )

            seen_events.add(key)

    print("Google calendar-source uniqueness: PASS")
    print("Google event uniqueness: PASS")


async def main() -> int:
    print()
    print("Jace Step 4C.4C duplicate-calendar hotfix test")
    print("=============================================")
    print()

    health = request_json("/health")
    if health.get("status") != "ok":
        raise RuntimeError("Jace backend is not healthy.")
    print("Backend health: PASS")

    result = request_json("/calendar/sync", method="POST")
    print("Google reconciliation:")
    print("  Duplicate connection rows ignored:", result.get("duplicate_connections_ignored", 0))
    print("  Duplicate calendar sources removed:", result.get("duplicate_sources_removed", 0))
    print("  Duplicate cached events removed:", result.get("duplicate_events_removed", 0))

    await assert_no_duplicates()

    request_json("/calendar/sync", method="POST")
    await assert_no_duplicates()

    print("Repeated sync idempotency: PASS")
    print()
    print("PASS - Google Calendar duplicate repair is operational.")
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
