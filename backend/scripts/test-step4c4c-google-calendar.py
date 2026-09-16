from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request

from jace.calendar.google_sync import (
    GOOGLE_CALENDAR_READ_SCOPE,
    _normalize_google_event,
)
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.database import SessionLocal

BASE = "http://127.0.0.1:8000"


def request_json(path: str, *, method: str = "GET") -> dict:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {path} returned HTTP {exc.code}: {detail}"
        ) from exc


def normalization_tests() -> None:
    timed = _normalize_google_event(
        {
            "id": "timed-1",
            "summary": "Project review",
            "status": "confirmed",
            "etag": '"123"',
            "iCalUID": "timed-1@example.com",
            "start": {
                "dateTime": "2026-09-17T13:00:00+01:00",
                "timeZone": "Europe/London",
            },
            "end": {
                "dateTime": "2026-09-17T14:00:00+01:00",
                "timeZone": "Europe/London",
            },
            "attendees": [
                {
                    "email": "test@example.com",
                    "responseStatus": "accepted",
                }
            ],
        },
        source_timezone="Europe/London",
    )
    if timed is None or timed.all_day or timed.start_at is None or timed.end_at is None:
        raise RuntimeError("Timed Google event normalization failed.")

    all_day = _normalize_google_event(
        {
            "id": "all-day-1",
            "summary": "Annual leave",
            "status": "confirmed",
            "start": {"date": "2026-09-20"},
            "end": {"date": "2026-09-22"},
        },
        source_timezone="Europe/London",
    )
    if (
        all_day is None
        or not all_day.all_day
        or str(all_day.start_date) != "2026-09-20"
        or str(all_day.end_date_exclusive) != "2026-09-22"
    ):
        raise RuntimeError("All-day Google event normalization failed.")

    deleted = _normalize_google_event(
        {"id": "deleted-1", "status": "cancelled"},
        source_timezone="Europe/London",
    )
    if deleted is None or not deleted.deleted:
        raise RuntimeError("Deleted Google event normalization failed.")

    print("Google event normalization: PASS")


async def scope_test() -> None:
    async with SessionLocal() as session:
        rows = await list_provider_connections(session, "google")
        configured = [row for row in rows if row.status == "configured"]
        if not configured:
            raise RuntimeError("No connected Google account was found.")

        with_scope = []
        for row in configured:
            config = _loads_object(row.config_json)
            scopes = config.get("scopes", [])
            normalized = (
                {
                    str(value).casefold()
                    for value in scopes
                    if isinstance(value, str)
                }
                if isinstance(scopes, list)
                else set()
            )
            if GOOGLE_CALENDAR_READ_SCOPE.casefold() in normalized:
                with_scope.append(row)

        if not with_scope:
            raise RuntimeError(
                "Google calendar.readonly is not recorded on a connected account. "
                "Reconnect Google after installing Step 4C.4C."
            )

    print("Recorded Google Calendar scope: PASS")


async def main() -> int:
    print()
    print("Jace Step 4C.4C Google Calendar Sync test")
    print("=========================================")
    print()

    normalization_tests()
    await scope_test()

    health = request_json("/health")
    if health.get("status") != "ok":
        raise RuntimeError("Jace backend health check failed.")
    print("Backend health: PASS")

    result = request_json("/calendar/sync", method="POST")
    if result.get("needs_reconnect"):
        raise RuntimeError("Backend reports Google Calendar needs reconnection.")
    if result.get("status") not in {"ok", "partial"}:
        raise RuntimeError(
            "Google Calendar sync did not complete: "
            + json.dumps(result, ensure_ascii=False)[:1500]
        )

    providers = result.get("providers", [])
    google = next(
        (
            provider
            for provider in providers
            if isinstance(provider, dict)
            and provider.get("provider_id") == "google"
        ),
        None,
    )
    if google is None:
        raise RuntimeError("Google provider result was missing from /calendar/sync.")
    if int(google.get("calendars_discovered", 0)) < 1:
        raise RuntimeError("Google Calendar did not discover any calendars.")

    print("Google calendar discovery: PASS")
    print("Google event sync: PASS")

    sources = request_json("/calendar/sources").get("sources", [])
    google_sources = [
        source
        for source in sources
        if isinstance(source, dict) and source.get("provider_id") == "google"
    ]
    if not google_sources:
        raise RuntimeError("No Google calendar_sources rows were created.")

    if not any(
        source.get("last_synced_at")
        for source in google_sources
        if source.get("sync_enabled")
    ):
        raise RuntimeError("No enabled Google calendar source records a successful sync.")

    print("Unified calendar source persistence: PASS")
    print()
    print("PASS - Step 4C.4C Google Calendar Sync is operational.")
    print()
    print(f"Discovered {len(google_sources)} Google calendar source(s).")
    print(
        f"Sync response: {result.get('events_changed', 0)} changed, "
        f"{result.get('events_deleted', 0)} deleted."
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
