from __future__ import annotations

# JACE_STEP4C4A_UNIFIED_CALENDAR_SERVICE

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jace.calendar.models import CalendarEvent, CalendarSource, CalendarSyncState
from jace.calendar.normalized import NormalizedCalendarEvent
from jace.calendar.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarSourceUpdate, validate_timezone
from jace.db.models import utc_now

DEFAULT_TIMEZONE = "Europe/London"
JACE_DEFAULT_SOURCE_ID = "jace-default"
JACE_DEFAULT_COLOR = "#7c8cff"


def _json_loads_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _aware(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=ZoneInfo(timezone_name))


def _to_utc(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware(value, timezone_name).astimezone(timezone.utc)


def _db_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _range_dates(start: datetime, end: datetime, timezone_name: str) -> tuple[date, date]:
    zone = ZoneInfo(timezone_name)
    start_local = _aware(start, timezone_name).astimezone(zone)
    end_local = _aware(end, timezone_name).astimezone(zone)
    start_date = start_local.date()
    if end_local.timetz().replace(tzinfo=None) == time.min:
        end_date = end_local.date()
    else:
        end_date = end_local.date() + timedelta(days=1)
    return start_date, end_date


def _validate_window(
    *,
    all_day: bool,
    start_at: datetime | None,
    end_at: datetime | None,
    start_date: date | None,
    end_date_exclusive: date | None,
) -> None:
    if all_day:
        if start_date is None or end_date_exclusive is None:
            raise ValueError("All-day events require start_date and end_date_exclusive.")
        if end_date_exclusive <= start_date:
            raise ValueError("end_date_exclusive must be after start_date.")
        if start_at is not None or end_at is not None:
            raise ValueError("All-day events must not contain timed fields.")
        return

    if start_at is None or end_at is None:
        raise ValueError("Timed events require start_at and end_at.")
    if end_at <= start_at:
        raise ValueError("end_at must be after start_at.")
    if start_date is not None or end_date_exclusive is not None:
        raise ValueError("Timed events must not contain all-day date fields.")


async def ensure_default_jace_calendar(
    session: AsyncSession,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> CalendarSource:
    validate_timezone(timezone_name)
    row = await session.get(CalendarSource, JACE_DEFAULT_SOURCE_ID)
    if row is not None:
        return row

    row = CalendarSource(
        id=JACE_DEFAULT_SOURCE_ID,
        provider_id="jace",
        connection_id=None,
        external_calendar_id="jace",
        name="Jace",
        account_hint=None,
        color=JACE_DEFAULT_COLOR,
        timezone=timezone_name,
        read_only=False,
        enabled=True,
        sync_enabled=False,
        is_primary=True,
        sync_status="local",
        metadata_json="{}",
    )
    session.add(row)
    await session.flush()
    return row


async def list_calendar_sources(session: AsyncSession) -> list[CalendarSource]:
    statement = select(CalendarSource).order_by(CalendarSource.provider_id, CalendarSource.name)
    return list((await session.execute(statement)).scalars().all())


async def get_calendar_source(session: AsyncSession, source_id: str) -> CalendarSource | None:
    return await session.get(CalendarSource, source_id)


async def update_calendar_source(
    session: AsyncSession,
    row: CalendarSource,
    update: CalendarSourceUpdate,
) -> CalendarSource:
    fields = update.model_fields_set

    if "name" in fields and update.name is not None:
        row.name = update.name.strip()
    if "color" in fields and update.color is not None:
        # JACE_STEP4C4E_USER_CALENDAR_COLOR
        metadata = _json_loads_object(row.metadata_json)
        metadata["user_color"] = update.color
        row.metadata_json = _json_dumps(metadata)
        row.color = update.color
    if "timezone" in fields and update.timezone is not None:
        validate_timezone(update.timezone)
        row.timezone = update.timezone
    if "enabled" in fields and update.enabled is not None:
        row.enabled = update.enabled
    if "sync_enabled" in fields and update.sync_enabled is not None:
        if row.provider_id == "jace" and update.sync_enabled:
            raise ValueError("The local Jace calendar does not use provider sync.")
        row.sync_enabled = update.sync_enabled

    row.updated_at = utc_now()
    await session.flush()
    return row


async def upsert_provider_calendar_source(
    session: AsyncSession,
    *,
    provider_id: str,
    connection_id: str,
    external_calendar_id: str,
    name: str,
    account_hint: str | None,
    color: str,
    timezone_name: str,
    read_only: bool,
    is_primary: bool,
    metadata: dict[str, Any] | None = None,
) -> CalendarSource:
    if provider_id not in {"google", "microsoft"}:
        raise ValueError("Provider calendar sources must be Google or Microsoft.")
    validate_timezone(timezone_name)

    statement = select(CalendarSource).where(
        CalendarSource.provider_id == provider_id,
        CalendarSource.connection_id == connection_id,
        CalendarSource.external_calendar_id == external_calendar_id,
    )
    row = (await session.execute(statement)).scalar_one_or_none()

    if row is None:
        row = CalendarSource(
            provider_id=provider_id,
            connection_id=connection_id,
            external_calendar_id=external_calendar_id,
            name=name,
            account_hint=account_hint,
            color=color,
            timezone=timezone_name,
            read_only=read_only,
            enabled=True,
            sync_enabled=True,
            is_primary=is_primary,
            sync_status="pending",
            metadata_json=_json_dumps(metadata or {}),
        )
        session.add(row)
    else:
        # JACE_STEP4C4E_PRESERVE_PROVIDER_COLOR
        existing_metadata = _json_loads_object(row.metadata_json)
        next_metadata = dict(metadata or {})
        user_color = existing_metadata.get("user_color")

        if (
            isinstance(user_color, str)
            and re.fullmatch(r"#[0-9A-Fa-f]{6}", user_color)
        ):
            row.color = user_color
            next_metadata["user_color"] = user_color
        else:
            row.color = color

        row.name = name
        row.account_hint = account_hint
        row.timezone = timezone_name
        row.read_only = read_only
        row.is_primary = is_primary
        row.metadata_json = _json_dumps(next_metadata)
        row.updated_at = utc_now()

    await session.flush()
    return row


async def create_jace_event(session: AsyncSession, request: CalendarEventCreate) -> CalendarEvent:
    source = (
        await get_calendar_source(session, request.source_id)
        if request.source_id
        else await ensure_default_jace_calendar(session, timezone_name=request.timezone)
    )
    if source is None:
        raise ValueError("Calendar source not found.")
    if source.provider_id != "jace" or source.read_only:
        raise ValueError(
            "4C.4A only creates native Jace events. External provider writes are added in 4C.5."
        )

    start_at = _to_utc(request.start_at, request.timezone)
    end_at = _to_utc(request.end_at, request.timezone)
    _validate_window(
        all_day=request.all_day,
        start_at=start_at,
        end_at=end_at,
        start_date=request.start_date,
        end_date_exclusive=request.end_date_exclusive,
    )

    row = CalendarEvent(
        source_id=source.id,
        title=request.title.strip(),
        description=request.description,
        location=request.location,
        meeting_url=request.meeting_url,
        all_day=request.all_day,
        start_at=start_at,
        end_at=end_at,
        start_date=request.start_date,
        end_date_exclusive=request.end_date_exclusive,
        timezone=request.timezone,
        status=request.status,
        availability=request.availability,
        visibility=request.visibility,
        organizer_json=_json_dumps(request.organizer),
        attendees_json=_json_dumps(request.attendees),
        reminders_json=_json_dumps(request.reminders),
        recurrence_rule=request.recurrence_rule,
        recurrence_json=_json_dumps(request.recurrence),
        created_by=request.created_by,
        sync_state="local",
        metadata_json=_json_dumps(request.metadata),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row, attribute_names=["source"])
    return row


async def get_calendar_event(
    session: AsyncSession,
    event_id: str,
    *,
    include_deleted: bool = False,
) -> CalendarEvent | None:
    statement = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.source))
        .where(CalendarEvent.id == event_id)
    )
    if not include_deleted:
        statement = statement.where(CalendarEvent.deleted_at.is_(None))
    return (await session.execute(statement)).scalar_one_or_none()


async def list_calendar_events(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    timezone_name: str = DEFAULT_TIMEZONE,
    source_ids: Iterable[str] | None = None,
    include_disabled_sources: bool = False,
) -> list[CalendarEvent]:
    validate_timezone(timezone_name)
    start_utc = _to_utc(start, timezone_name)
    end_utc = _to_utc(end, timezone_name)
    if start_utc is None or end_utc is None or end_utc <= start_utc:
        raise ValueError("Calendar range end must be after start.")

    range_start_date, range_end_date = _range_dates(start, end, timezone_name)
    timed_overlap = and_(
        CalendarEvent.all_day.is_(False),
        CalendarEvent.start_at < end_utc,
        CalendarEvent.end_at > start_utc,
    )
    all_day_overlap = and_(
        CalendarEvent.all_day.is_(True),
        CalendarEvent.start_date < range_end_date,
        CalendarEvent.end_date_exclusive > range_start_date,
    )

    statement = (
        select(CalendarEvent)
        .join(CalendarSource)
        .options(selectinload(CalendarEvent.source))
        .where(
            CalendarEvent.deleted_at.is_(None),
            or_(timed_overlap, all_day_overlap),
        )
        .order_by(
            CalendarEvent.all_day.desc(),
            CalendarEvent.start_date,
            CalendarEvent.start_at,
            CalendarEvent.title,
        )
    )
    if not include_disabled_sources:
        statement = statement.where(CalendarSource.enabled.is_(True))

    ids = [value for value in (source_ids or []) if value]
    if ids:
        statement = statement.where(CalendarEvent.source_id.in_(ids))

    return list((await session.execute(statement)).scalars().all())


async def update_jace_event(
    session: AsyncSession,
    row: CalendarEvent,
    update: CalendarEventUpdate,
) -> CalendarEvent:
    if row.source.provider_id != "jace" or row.source.read_only:
        raise ValueError("4C.4A only edits native Jace events.")

    fields = update.model_fields_set
    for field_name in (
        "title", "description", "location", "meeting_url", "status",
        "availability", "visibility", "recurrence_rule",
    ):
        if field_name in fields:
            value = getattr(update, field_name)
            if field_name == "title" and value is not None:
                value = value.strip()
            setattr(row, field_name, value)

    if "timezone" in fields and update.timezone is not None:
        validate_timezone(update.timezone)
        row.timezone = update.timezone

    target_all_day = update.all_day if "all_day" in fields and update.all_day is not None else row.all_day
    target_start_at = update.start_at if "start_at" in fields else row.start_at
    target_end_at = update.end_at if "end_at" in fields else row.end_at
    target_start_date = update.start_date if "start_date" in fields else row.start_date
    target_end_date = (
        update.end_date_exclusive if "end_date_exclusive" in fields else row.end_date_exclusive
    )

    if target_all_day:
        if "all_day" in fields and update.all_day:
            target_start_at = None
            target_end_at = None
    else:
        if "all_day" in fields and update.all_day is False:
            target_start_date = None
            target_end_date = None
        target_start_at = _to_utc(target_start_at, row.timezone)
        target_end_at = _to_utc(target_end_at, row.timezone)

    _validate_window(
        all_day=target_all_day,
        start_at=target_start_at,
        end_at=target_end_at,
        start_date=target_start_date,
        end_date_exclusive=target_end_date,
    )

    row.all_day = target_all_day
    row.start_at = target_start_at
    row.end_at = target_end_at
    row.start_date = target_start_date
    row.end_date_exclusive = target_end_date

    if "organizer" in fields:
        row.organizer_json = _json_dumps(update.organizer or {})
    if "attendees" in fields:
        row.attendees_json = _json_dumps(update.attendees or [])
    if "reminders" in fields:
        row.reminders_json = _json_dumps(update.reminders or [])
    if "recurrence" in fields:
        row.recurrence_json = _json_dumps(update.recurrence or {})
    if "metadata" in fields:
        row.metadata_json = _json_dumps(update.metadata or {})

    row.local_revision += 1
    row.updated_at = utc_now()
    await session.flush()
    return row


async def delete_jace_event(session: AsyncSession, row: CalendarEvent) -> None:
    if row.source.provider_id != "jace" or row.source.read_only:
        raise ValueError("4C.4A only deletes native Jace events.")
    row.deleted_at = utc_now()
    row.local_revision += 1
    row.updated_at = row.deleted_at
    await session.flush()


async def get_or_create_sync_state(
    session: AsyncSession,
    source: CalendarSource,
) -> CalendarSyncState:
    row = await session.get(CalendarSyncState, source.id)
    if row is None:
        row = CalendarSyncState(source_id=source.id)
        session.add(row)
        await session.flush()
    return row


async def upsert_provider_event(
    session: AsyncSession,
    source: CalendarSource,
    normalized: NormalizedCalendarEvent,
) -> CalendarEvent | None:
    if source.provider_id not in {"google", "microsoft"}:
        raise ValueError("Provider event upsert requires an external calendar source.")

    statement = (
        select(CalendarEvent)
        .options(selectinload(CalendarEvent.source))
        .where(
            CalendarEvent.source_id == source.id,
            CalendarEvent.external_event_id == normalized.external_event_id,
        )
    )
    row = (await session.execute(statement)).scalar_one_or_none()

    if normalized.deleted:
        if row is not None:
            row.deleted_at = utc_now()
            row.sync_state = "synced"
            row.sync_error = None
            row.updated_at = utc_now()
            await session.flush()
        return row

    start_at = _to_utc(normalized.start_at, normalized.timezone)
    end_at = _to_utc(normalized.end_at, normalized.timezone)
    _validate_window(
        all_day=normalized.all_day,
        start_at=start_at,
        end_at=end_at,
        start_date=normalized.start_date,
        end_date_exclusive=normalized.end_date_exclusive,
    )

    if row is None:
        row = CalendarEvent(
            source_id=source.id,
            external_event_id=normalized.external_event_id,
            created_by="provider",
        )
        session.add(row)

    row.external_series_id = normalized.external_series_id
    row.original_event_id = normalized.original_event_id
    row.ical_uid = normalized.ical_uid
    row.external_version = normalized.external_version
    row.title = normalized.title or "Untitled event"
    row.description = normalized.description
    row.location = normalized.location
    row.meeting_url = normalized.meeting_url
    row.all_day = normalized.all_day
    row.start_at = start_at
    row.end_at = end_at
    row.start_date = normalized.start_date
    row.end_date_exclusive = normalized.end_date_exclusive
    row.timezone = normalized.timezone
    row.status = normalized.status
    row.availability = normalized.availability
    row.visibility = normalized.visibility
    row.organizer_json = _json_dumps(normalized.organizer)
    row.attendees_json = _json_dumps(normalized.attendees)
    row.reminders_json = _json_dumps(normalized.reminders)
    row.recurrence_rule = normalized.recurrence_rule
    row.recurrence_json = _json_dumps(normalized.recurrence)
    row.provider_created_at = _to_utc(normalized.provider_created_at, normalized.timezone)
    row.provider_updated_at = _to_utc(normalized.provider_updated_at, normalized.timezone)
    row.provider_data_json = _json_dumps(normalized.provider_data)
    row.metadata_json = _json_dumps(normalized.metadata)
    row.sync_state = "synced"
    row.sync_error = None
    row.deleted_at = None
    row.updated_at = utc_now()

    await session.flush()
    await session.refresh(row, attribute_names=["source"])
    return row


async def mark_sync_success(
    session: AsyncSession,
    source: CalendarSource,
    *,
    sync_token: str | None = None,
    delta_url: str | None = None,
    window_start_at: datetime | None = None,
    window_end_at: datetime | None = None,
    provider_state: dict[str, Any] | None = None,
    full_sync: bool = False,
) -> CalendarSyncState:
    state = await get_or_create_sync_state(session, source)
    now = utc_now()
    state.sync_token = sync_token
    state.delta_url = delta_url
    state.window_start_at = _to_utc(window_start_at, source.timezone)
    state.window_end_at = _to_utc(window_end_at, source.timezone)
    state.provider_state_json = _json_dumps(provider_state or {})
    state.last_attempt_at = now
    state.last_success_at = now
    state.last_error = None
    state.updated_at = now
    if full_sync:
        state.last_full_sync_at = now
    source.sync_status = "synced"
    source.last_synced_at = now
    source.updated_at = now
    await session.flush()
    return state


async def mark_sync_error(
    session: AsyncSession,
    source: CalendarSource,
    error: str,
) -> CalendarSyncState:
    state = await get_or_create_sync_state(session, source)
    now = utc_now()
    state.last_attempt_at = now
    state.last_error = error[:10_000]
    state.updated_at = now
    source.sync_status = "error"
    source.updated_at = now
    await session.flush()
    return state


async def calendar_counts(session: AsyncSession) -> dict[str, int]:
    source_count = int((await session.execute(select(func.count(CalendarSource.id)))).scalar_one())
    enabled_source_count = int((await session.execute(
        select(func.count(CalendarSource.id)).where(CalendarSource.enabled.is_(True))
    )).scalar_one())
    local_event_count = int((await session.execute(
        select(func.count(CalendarEvent.id)).join(CalendarSource).where(
            CalendarEvent.deleted_at.is_(None), CalendarSource.provider_id == "jace"
        )
    )).scalar_one())
    external_event_count = int((await session.execute(
        select(func.count(CalendarEvent.id)).join(CalendarSource).where(
            CalendarEvent.deleted_at.is_(None), CalendarSource.provider_id != "jace"
        )
    )).scalar_one())
    pending_sync_count = int((await session.execute(
        select(func.count(CalendarEvent.id)).where(
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.sync_state.in_(("pending_create", "pending_update", "pending_delete", "error")),
        )
    )).scalar_one())
    return {
        "source_count": source_count,
        "enabled_source_count": enabled_source_count,
        "local_event_count": local_event_count,
        "external_event_count": external_event_count,
        "pending_sync_count": pending_sync_count,
    }


def source_payload(row: CalendarSource) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "connection_id": row.connection_id,
        "external_calendar_id": row.external_calendar_id,
        "name": row.name,
        "account_hint": row.account_hint,
        "color": row.color,
        "timezone": row.timezone,
        "read_only": row.read_only,
        "enabled": row.enabled,
        "sync_enabled": row.sync_enabled,
        "is_primary": row.is_primary,
        "sync_status": row.sync_status,
        "metadata": _json_loads_object(row.metadata_json),
        "last_synced_at": _db_utc(row.last_synced_at),
        "created_at": _db_utc(row.created_at),
        "updated_at": _db_utc(row.updated_at),
    }


def event_payload(row: CalendarEvent) -> dict[str, Any]:
    source = row.source
    editable = source.provider_id == "jace" and not source.read_only

    # JACE_STEP4C4E_EVENT_ENRICHMENT_HINT
    event_metadata = _json_loads_object(row.metadata_json)
    provider_data = _json_loads_object(row.provider_data_json)
    event_type_value = (
        event_metadata.get("event_type")
        or provider_data.get("eventType")
    )
    event_type = (
        event_type_value
        if isinstance(event_type_value, str)
        else None
    )
    description_lower = (row.description or "").casefold()
    can_enrich_from_email = (
        source.provider_id == "google"
        and (
            event_type == "fromGmail"
            or (
                "created from an email" in description_lower
                and "gmail" in description_lower
            )
        )
    )

    return {
        "id": row.id,
        "source_id": row.source_id,
        "provider_id": source.provider_id,
        "calendar_name": source.name,
        "calendar_color": source.color,
        "account_hint": source.account_hint,
        "source_read_only": source.read_only,
        "external_event_id": row.external_event_id,
        "external_series_id": row.external_series_id,
        "original_event_id": row.original_event_id,
        "ical_uid": row.ical_uid,
        "title": row.title,
        "description": row.description,
        "location": row.location,
        "meeting_url": row.meeting_url,
        "all_day": row.all_day,
        "start_at": _db_utc(row.start_at),
        "end_at": _db_utc(row.end_at),
        "start_date": row.start_date,
        "end_date_exclusive": row.end_date_exclusive,
        "timezone": row.timezone,
        "status": row.status,
        "availability": row.availability,
        "visibility": row.visibility,
        "organizer": _json_loads_object(row.organizer_json),
        "attendees": _json_loads_list(row.attendees_json),
        "reminders": _json_loads_list(row.reminders_json),
        "recurrence_rule": row.recurrence_rule,
        "recurrence": _json_loads_object(row.recurrence_json),
        "created_by": row.created_by,
        "sync_state": row.sync_state,
        "sync_error": row.sync_error,
        "can_edit": editable,
        "can_delete": editable,
        "event_type": event_type,
        "can_enrich_from_email": can_enrich_from_email,
        "created_at": _db_utc(row.created_at),
        "updated_at": _db_utc(row.updated_at),
        "deleted_at": _db_utc(row.deleted_at),
    }
