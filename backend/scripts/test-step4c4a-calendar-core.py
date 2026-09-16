from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

from jace.calendar.normalized import NormalizedCalendarEvent
from jace.calendar.schemas import CalendarEventCreate, CalendarEventUpdate
from jace.calendar.service import (
    create_jace_event,
    delete_jace_event,
    ensure_default_jace_calendar,
    get_calendar_event,
    list_calendar_events,
    mark_sync_success,
    upsert_provider_calendar_source,
    upsert_provider_event,
    update_jace_event,
)
from jace.database import SessionLocal, init_database


async def main() -> int:
    print()
    print("Jace Step 4C.4A Unified Calendar Core test")
    print("==========================================")
    print()

    await init_database()

    async with SessionLocal() as session:
        transaction = await session.begin()
        try:
            source = await ensure_default_jace_calendar(session)

            if source.provider_id != "jace" or source.read_only:
                raise RuntimeError("Default Jace calendar is not writable.")

            print("Default Jace calendar: PASS")

            start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
            end = start + timedelta(hours=1)

            timed = await create_jace_event(
                session,
                CalendarEventCreate(
                    title="4C.4A timed test",
                    start_at=start,
                    end_at=end,
                    timezone="Europe/London",
                    created_by="jace",
                ),
            )

            all_day = await create_jace_event(
                session,
                CalendarEventCreate(
                    title="4C.4A all-day test",
                    all_day=True,
                    start_date=date.today() + timedelta(days=3),
                    end_date_exclusive=date.today() + timedelta(days=4),
                    timezone="Europe/London",
                ),
            )

            rows = await list_calendar_events(
                session,
                start=start - timedelta(days=3),
                end=end + timedelta(days=5),
                timezone_name="Europe/London",
            )
            ids = {row.id for row in rows}
            if timed.id not in ids or all_day.id not in ids:
                raise RuntimeError("Unified range query did not return both event types.")

            print("Timed + all-day range query: PASS")

            await update_jace_event(
                session,
                timed,
                CalendarEventUpdate(title="4C.4A updated timed test"),
            )
            refreshed = await get_calendar_event(session, timed.id)
            if refreshed is None or refreshed.title != "4C.4A updated timed test":
                raise RuntimeError("Native event update failed.")

            print("Native event update: PASS")

            google = await upsert_provider_calendar_source(
                session,
                provider_id="google",
                connection_id="test-google-connection",
                external_calendar_id="primary",
                name="Test Google",
                account_hint="calendar-test@example.invalid",
                color="#4285F4",
                timezone_name="Europe/London",
                read_only=False,
                is_primary=True,
                metadata={"test": True},
            )

            external = await upsert_provider_event(
                session,
                google,
                NormalizedCalendarEvent(
                    external_event_id="external-test-event",
                    title="External normalized test",
                    all_day=False,
                    timezone="Europe/London",
                    start_at=start + timedelta(hours=2),
                    end_at=start + timedelta(hours=3),
                    external_version='"test-etag"',
                    provider_data={"test": True},
                ),
            )

            if external is None or external.sync_state != "synced":
                raise RuntimeError("Provider event normalization/upsert failed.")

            state = await mark_sync_success(
                session,
                google,
                sync_token="google-sync-token-test",
                provider_state={"test": True},
                full_sync=True,
            )
            if state.sync_token != "google-sync-token-test":
                raise RuntimeError("Google sync-token storage failed.")

            microsoft = await upsert_provider_calendar_source(
                session,
                provider_id="microsoft",
                connection_id="test-microsoft-connection",
                external_calendar_id="calendar-id",
                name="Test Outlook",
                account_hint="calendar-test@example.invalid",
                color="#0078D4",
                timezone_name="Europe/London",
                read_only=False,
                is_primary=True,
                metadata={"test": True},
            )
            state = await mark_sync_success(
                session,
                microsoft,
                delta_url="https://graph.microsoft.com/test-delta-link",
                provider_state={"test": True},
                full_sync=True,
            )
            if not state.delta_url:
                raise RuntimeError("Microsoft delta-link storage failed.")

            print("Provider normalization + sync cursors: PASS")

            await delete_jace_event(session, timed)
            deleted = await get_calendar_event(session, timed.id)
            if deleted is not None:
                raise RuntimeError("Soft-deleted event remained visible.")

            print("Soft deletion: PASS")

        finally:
            await transaction.rollback()

    print()
    print("PASS - Step 4C.4A Unified Calendar Core is operational.")
    print("Test data was rolled back; no calendar entries were retained.")
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
