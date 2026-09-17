from __future__ import annotations

# JACE_STEP4C4F_CALENDAR_INTELLIGENCE

from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from jace.calendar.models import CalendarEvent
from jace.calendar.preferences import (
    DEFAULT_CALENDAR_TIMEZONE,
    ensure_calendar_preferences,
)
from jace.calendar.service import (
    list_calendar_events,
    list_calendar_sources,
)


def _db_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def calendar_timezone(session: AsyncSession) -> str:
    preferences = await ensure_calendar_preferences(session)
    return preferences.timezone or DEFAULT_CALENDAR_TIMEZONE


def _event_interval(
    event: CalendarEvent,
    zone: ZoneInfo,
) -> tuple[datetime, datetime] | None:
    if event.all_day:
        if (
            event.start_date is None
            or event.end_date_exclusive is None
        ):
            return None

        return (
            datetime.combine(
                event.start_date,
                time.min,
                tzinfo=zone,
            ),
            datetime.combine(
                event.end_date_exclusive,
                time.min,
                tzinfo=zone,
            ),
        )

    start = _db_aware(event.start_at)
    end = _db_aware(event.end_at)

    if start is None or end is None:
        return None

    return (
        start.astimezone(zone),
        end.astimezone(zone),
    )


def _event_summary(
    event: CalendarEvent,
    zone: ZoneInfo,
) -> dict[str, Any]:
    interval = _event_interval(event, zone)
    source = event.source

    result: dict[str, Any] = {
        "id": event.id,
        "title": event.title,
        "calendar": source.name,
        "provider": source.provider_id,
        "account": source.account_hint,
        "all_day": event.all_day,
        "status": event.status,
        "availability": event.availability,
        "location": event.location or None,
        "meeting_url": event.meeting_url,
    }

    if event.all_day:
        result["start_date"] = (
            event.start_date.isoformat()
            if event.start_date
            else None
        )
        result["end_date_exclusive"] = (
            event.end_date_exclusive.isoformat()
            if event.end_date_exclusive
            else None
        )
    elif interval is not None:
        result["start"] = interval[0].isoformat()
        result["end"] = interval[1].isoformat()

    return result


def _is_busy(event: CalendarEvent) -> bool:
    return (
        event.status != "cancelled"
        and event.availability != "free"
    )


def _merge_intervals(
    intervals: Iterable[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    ordered = sorted(
        (
            (start, end)
            for start, end in intervals
            if end > start
        ),
        key=lambda item: item[0],
    )

    merged: list[tuple[datetime, datetime]] = []

    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue

        previous_start, previous_end = merged[-1]
        merged[-1] = (
            previous_start,
            max(previous_end, end),
        )

    return merged


async def _sources_freshness(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    sources = await list_calendar_sources(session)

    return [
        {
            "id": source.id,
            "calendar": source.name,
            "provider": source.provider_id,
            "account": source.account_hint,
            "enabled": source.enabled,
            "sync_status": source.sync_status,
            "last_synced_at": (
                _db_aware(source.last_synced_at).isoformat()
                if source.last_synced_at
                else None
            ),
        }
        for source in sources
        if source.enabled
    ]


async def list_events(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    timezone_name = timezone_name or await calendar_timezone(session)
    zone = ZoneInfo(timezone_name)

    rows = await list_calendar_events(
        session,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )

    events = [
        _event_summary(row, zone)
        for row in rows
        if row.status != "cancelled"
    ]

    return {
        "timezone": timezone_name,
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "event_count": len(events),
        "events": events,
        "calendar_freshness": await _sources_freshness(session),
    }


async def next_event(
    session: AsyncSession,
    *,
    after: datetime | None = None,
    lookahead_days: int = 90,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    timezone_name = timezone_name or await calendar_timezone(session)
    zone = ZoneInfo(timezone_name)

    if after is None:
        after = datetime.now(zone)
    elif after.tzinfo is None:
        after = after.replace(tzinfo=zone)
    else:
        after = after.astimezone(zone)

    end = after + timedelta(days=lookahead_days)

    rows = await list_calendar_events(
        session,
        start=after,
        end=end,
        timezone_name=timezone_name,
    )

    candidates: list[tuple[datetime, CalendarEvent]] = []

    for row in rows:
        if row.status == "cancelled":
            continue

        interval = _event_interval(row, zone)
        if interval is None:
            continue

        start_at, event_end = interval

        if event_end <= after:
            continue

        candidates.append(
            (
                max(start_at, after),
                row,
            )
        )

    candidates.sort(
        key=lambda item: (
            item[0],
            0 if item[1].all_day else 1,
            item[1].title.casefold(),
        )
    )

    row = candidates[0][1] if candidates else None

    return {
        "timezone": timezone_name,
        "after": after.isoformat(),
        "lookahead_days": lookahead_days,
        "event": (
            _event_summary(row, zone)
            if row is not None
            else None
        ),
        "calendar_freshness": await _sources_freshness(session),
    }


async def free_busy(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    timezone_name = timezone_name or await calendar_timezone(session)
    zone = ZoneInfo(timezone_name)

    if start.tzinfo is None:
        start = start.replace(tzinfo=zone)
    else:
        start = start.astimezone(zone)

    if end.tzinfo is None:
        end = end.replace(tzinfo=zone)
    else:
        end = end.astimezone(zone)

    if end <= start:
        raise ValueError("Free/busy range end must be after start.")

    rows = await list_calendar_events(
        session,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )

    busy_events: list[dict[str, Any]] = []
    intervals: list[tuple[datetime, datetime]] = []

    for row in rows:
        if not _is_busy(row):
            continue

        interval = _event_interval(row, zone)

        if interval is None:
            continue

        busy_start = max(start, interval[0])
        busy_end = min(end, interval[1])

        if busy_end <= busy_start:
            continue

        intervals.append((busy_start, busy_end))
        busy_events.append(_event_summary(row, zone))

    merged = _merge_intervals(intervals)

    return {
        "timezone": timezone_name,
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "busy": [
            {
                "start": item[0].isoformat(),
                "end": item[1].isoformat(),
            }
            for item in merged
        ],
        "busy_events": busy_events,
        "is_free": not merged,
        "calendar_freshness": await _sources_freshness(session),
    }


async def conflicts(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    result = await free_busy(
        session,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )

    return {
        **result,
        "has_conflict": bool(result["busy"]),
        "conflict_count": len(result["busy_events"]),
    }


async def find_open_slots(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    duration_minutes: int,
    day_start: time,
    day_end: time,
    timezone_name: str | None = None,
    limit: int = 10,
    include_weekends: bool = False,
) -> dict[str, Any]:
    timezone_name = timezone_name or await calendar_timezone(session)
    zone = ZoneInfo(timezone_name)

    if start.tzinfo is None:
        start = start.replace(tzinfo=zone)
    else:
        start = start.astimezone(zone)

    if end.tzinfo is None:
        end = end.replace(tzinfo=zone)
    else:
        end = end.astimezone(zone)

    if end <= start:
        raise ValueError("Slot-search range end must be after start.")

    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be greater than zero.")

    if day_end <= day_start:
        raise ValueError("day_end must be after day_start.")

    rows = await list_calendar_events(
        session,
        start=start,
        end=end,
        timezone_name=timezone_name,
    )

    busy_intervals: list[tuple[datetime, datetime]] = []

    for row in rows:
        if not _is_busy(row):
            continue

        interval = _event_interval(row, zone)

        if interval is not None:
            busy_intervals.append(interval)

    busy = _merge_intervals(busy_intervals)
    duration = timedelta(minutes=duration_minutes)
    slots: list[dict[str, str]] = []
    day = start.date()

    while day <= end.date() and len(slots) < limit:
        if include_weekends or day.weekday() < 5:
            window_start = datetime.combine(
                day,
                day_start,
                tzinfo=zone,
            )
            window_end = datetime.combine(
                day,
                day_end,
                tzinfo=zone,
            )

            window_start = max(window_start, start)
            window_end = min(window_end, end)

            if window_end > window_start:
                cursor = window_start

                for busy_start, busy_end in busy:
                    if busy_end <= cursor:
                        continue

                    if busy_start >= window_end:
                        break

                    clipped_start = max(
                        busy_start,
                        window_start,
                    )
                    clipped_end = min(
                        busy_end,
                        window_end,
                    )

                    if clipped_start - cursor >= duration:
                        slots.append(
                            {
                                "start": cursor.isoformat(),
                                "end": (
                                    cursor + duration
                                ).isoformat(),
                            }
                        )

                        if len(slots) >= limit:
                            break

                    cursor = max(cursor, clipped_end)

                if (
                    len(slots) < limit
                    and window_end - cursor >= duration
                ):
                    slots.append(
                        {
                            "start": cursor.isoformat(),
                            "end": (
                                cursor + duration
                            ).isoformat(),
                        }
                    )

        day += timedelta(days=1)

    return {
        "timezone": timezone_name,
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "duration_minutes": duration_minutes,
        "working_hours": {
            "start": day_start.isoformat(
                timespec="minutes"
            ),
            "end": day_end.isoformat(
                timespec="minutes"
            ),
        },
        "include_weekends": include_weekends,
        "slot_count": len(slots),
        "slots": slots,
        "calendar_freshness": await _sources_freshness(session),
    }
