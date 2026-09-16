from __future__ import annotations

import asyncio
# JACE_STEP4C4C_GOOGLE_CALENDAR_SYNC

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jace.calendar.models import (
    CalendarEvent,
    CalendarSource,
    CalendarSyncState,
)
from jace.calendar.normalized import (
    NormalizedCalendarEvent,
)
from jace.calendar.service import (
    DEFAULT_TIMEZONE,
    get_or_create_sync_state,
    mark_sync_error,
    mark_sync_success,
    upsert_provider_calendar_source,
    upsert_provider_event,
)
from jace.connections.oauth import valid_access_token
from jace.connections.service import (
    _loads_object,
    list_provider_connections,
)
from jace.db.models import utc_now


GOOGLE_CALENDAR_API = (
    "https://www.googleapis.com/calendar/v3"
)
GOOGLE_CALENDAR_READ_SCOPE = (
    "https://www.googleapis.com/auth/calendar.readonly"
)
HTTP_TIMEOUT_SECONDS = 30.0
EVENT_PAGE_SIZE = 2500
CALENDAR_PAGE_SIZE = 250

# Keep the initial import useful without pulling an unlimited amount of very
# old history. Google's documented incremental-sync sample uses an initial
# timeMin filter and then persists nextSyncToken for later change-only sync.
INITIAL_HISTORY_DAYS = 365


class GoogleCalendarSyncError(RuntimeError):
    pass


class GoogleSyncTokenExpired(
    GoogleCalendarSyncError
):
    pass


@dataclass(slots=True)
class CalendarSyncResult:
    source_id: str
    calendar_id: str
    name: str
    mode: str
    changed: int = 0
    deleted: int = 0
    pages: int = 0
    error: str | None = None


@dataclass(slots=True)
class ConnectionSyncResult:
    connection_id: str
    account_hint: str | None
    status: str
    calendars_discovered: int = 0
    calendars_synced: int = 0
    events_changed: int = 0
    events_deleted: int = 0
    errors: list[str] = field(
        default_factory=list,
    )
    calendars: list[
        CalendarSyncResult
    ] = field(
        default_factory=list,
    )


@dataclass(slots=True)
class GoogleCalendarSyncSummary:
    provider_id: str = "google"
    status: str = "ok"
    connections_seen: int = 0
    connections_synced: int = 0
    calendars_discovered: int = 0
    calendars_synced: int = 0
    events_changed: int = 0
    events_deleted: int = 0
    needs_reconnect: bool = False
    duplicate_connections_ignored: int = 0
    duplicate_sources_removed: int = 0
    duplicate_events_removed: int = 0
    errors: list[str] = field(
        default_factory=list,
    )
    connections: list[
        ConnectionSyncResult
    ] = field(
        default_factory=list,
    )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return asdict(
            self
        )


def _scope_set(
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

    return {
        str(value).strip().casefold()
        for value in raw
        if str(value).strip()
    }


def _has_calendar_scope(
    config_json: str,
) -> bool:
    scopes = _scope_set(
        config_json
    )
    return (
        GOOGLE_CALENDAR_READ_SCOPE.casefold()
        in scopes
        or "https://www.googleapis.com/auth/calendar".casefold()
        in scopes
    )


def _safe_timezone(
    value: object,
    fallback: str = DEFAULT_TIMEZONE,
) -> str:
    if (
        isinstance(value, str)
        and value.strip()
    ):
        return value.strip()

    return fallback


def _parse_datetime(
    value: object,
) -> datetime | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    raw = value.strip()

    if not raw:
        return None

    if raw.endswith(
        "Z"
    ):
        raw = (
            raw[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            raw
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc,
        )

    return parsed


def _parse_date(
    value: object,
) -> date | None:
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return date.fromisoformat(
            value
        )
    except ValueError:
        return None


def _email_identity(
    value: object,
) -> dict[str, Any]:
    if not isinstance(
        value,
        dict,
    ):
        return {}

    result: dict[str, Any] = {}

    for source_key, target_key in (
        ("email", "email"),
        ("displayName", "name"),
        ("id", "id"),
        ("self", "self"),
    ):
        item = value.get(
            source_key
        )

        if item is not None:
            result[
                target_key
            ] = item

    return result


def _attendees(
    value: object,
) -> list[dict[str, Any]]:
    if not isinstance(
        value,
        list,
    ):
        return []

    result: list[
        dict[str, Any]
    ] = []

    for item in value:
        if not isinstance(
            item,
            dict,
        ):
            continue

        attendee = _email_identity(
            item
        )

        for key in (
            "responseStatus",
            "optional",
            "organizer",
            "resource",
            "comment",
            "additionalGuests",
        ):
            if key in item:
                attendee[
                    key
                ] = item[
                    key
                ]

        if attendee:
            result.append(
                attendee
            )

    return result


def _meeting_url(
    event: dict[str, Any],
) -> str | None:
    hangout = event.get(
        "hangoutLink"
    )

    if isinstance(
        hangout,
        str,
    ) and hangout:
        return hangout

    conference = event.get(
        "conferenceData"
    )

    if not isinstance(
        conference,
        dict,
    ):
        return None

    entry_points = conference.get(
        "entryPoints"
    )

    if not isinstance(
        entry_points,
        list,
    ):
        return None

    for entry in entry_points:
        if not isinstance(
            entry,
            dict,
        ):
            continue

        uri = entry.get(
            "uri"
        )
        entry_type = entry.get(
            "entryPointType"
        )

        if (
            isinstance(uri, str)
            and uri
            and entry_type
            in {
                "video",
                "more",
            }
        ):
            return uri

    return None


def _reminders(
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = event.get(
        "reminders"
    )

    if not isinstance(
        raw,
        dict,
    ):
        return []

    result: list[
        dict[str, Any]
    ] = []

    if raw.get(
        "useDefault"
    ):
        result.append(
            {
                "use_default": True,
            }
        )

    overrides = raw.get(
        "overrides"
    )

    if isinstance(
        overrides,
        list,
    ):
        for item in overrides:
            if isinstance(
                item,
                dict,
            ):
                result.append(
                    dict(item)
                )

    return result


def _normalize_google_event(
    raw: dict[str, Any],
    *,
    source_timezone: str,
) -> NormalizedCalendarEvent | None:
    event_id = raw.get(
        "id"
    )

    if not isinstance(
        event_id,
        str,
    ) or not event_id:
        return None

    status = str(
        raw.get(
            "status"
        )
        or "confirmed"
    )

    # Cancelled/deleted entries in incremental sync often omit start/end.
    if status == "cancelled":
        return NormalizedCalendarEvent(
            external_event_id=event_id,
            title=str(
                raw.get(
                    "summary"
                )
                or "Cancelled event"
            ),
            all_day=False,
            timezone=source_timezone,
            external_series_id=(
                raw.get(
                    "recurringEventId"
                )
                if isinstance(
                    raw.get(
                        "recurringEventId"
                    ),
                    str,
                )
                else None
            ),
            ical_uid=(
                raw.get(
                    "iCalUID"
                )
                if isinstance(
                    raw.get(
                        "iCalUID"
                    ),
                    str,
                )
                else None
            ),
            external_version=(
                raw.get(
                    "etag"
                )
                if isinstance(
                    raw.get(
                        "etag"
                    ),
                    str,
                )
                else None
            ),
            provider_data=raw,
            deleted=True,
        )

    start = raw.get(
        "start"
    )
    end = raw.get(
        "end"
    )

    if not isinstance(
        start,
        dict,
    ) or not isinstance(
        end,
        dict,
    ):
        return None

    start_date = _parse_date(
        start.get(
            "date"
        )
    )
    end_date = _parse_date(
        end.get(
            "date"
        )
    )

    all_day = (
        start_date is not None
        and end_date is not None
    )

    timezone_name = _safe_timezone(
        start.get(
            "timeZone"
        ),
        _safe_timezone(
            end.get(
                "timeZone"
            ),
            source_timezone,
        ),
    )

    start_at = None
    end_at = None

    if not all_day:
        start_at = _parse_datetime(
            start.get(
                "dateTime"
            )
        )
        end_at = _parse_datetime(
            end.get(
                "dateTime"
            )
        )

        if (
            start_at is None
            or end_at is None
        ):
            return None

    recurrence = raw.get(
        "recurrence"
    )
    recurrence_items = (
        [
            str(item)
            for item in recurrence
            if isinstance(
                item,
                str,
            )
        ]
        if isinstance(
            recurrence,
            list,
        )
        else []
    )

    recurring_event_id = raw.get(
        "recurringEventId"
    )

    organizer = _email_identity(
        raw.get(
            "organizer"
        )
    )

    original_start = raw.get(
        "originalStartTime"
    )

    metadata: dict[str, Any] = {
        "event_type": raw.get(
            "eventType"
        ),
        "html_link": raw.get(
            "htmlLink"
        ),
        "creator": _email_identity(
            raw.get(
                "creator"
            )
        ),
        "transparency": raw.get(
            "transparency"
        ),
        "locked": raw.get(
            "locked"
        ),
    }

    if isinstance(
        original_start,
        dict,
    ):
        metadata[
            "original_start_time"
        ] = original_start

    return NormalizedCalendarEvent(
        external_event_id=event_id,
        title=str(
            raw.get(
                "summary"
            )
            or "Untitled event"
        ),
        all_day=all_day,
        timezone=timezone_name,
        start_at=start_at,
        end_at=end_at,
        start_date=start_date,
        end_date_exclusive=end_date,
        external_series_id=(
            recurring_event_id
            if isinstance(
                recurring_event_id,
                str,
            )
            else None
        ),
        ical_uid=(
            raw.get(
                "iCalUID"
            )
            if isinstance(
                raw.get(
                    "iCalUID"
                ),
                str,
            )
            else None
        ),
        external_version=(
            raw.get(
                "etag"
            )
            if isinstance(
                raw.get(
                    "etag"
                ),
                str,
            )
            else None
        ),
        description=str(
            raw.get(
                "description"
            )
            or ""
        ),
        location=str(
            raw.get(
                "location"
            )
            or ""
        ),
        meeting_url=_meeting_url(
            raw
        ),
        status=(
            status
            if status
            in {
                "confirmed",
                "tentative",
                "cancelled",
            }
            else "confirmed"
        ),
        availability=(
            "free"
            if raw.get(
                "transparency"
            )
            == "transparent"
            else "busy"
        ),
        visibility=str(
            raw.get(
                "visibility"
            )
            or "default"
        ),
        organizer=organizer,
        attendees=_attendees(
            raw.get(
                "attendees"
            )
        ),
        reminders=_reminders(
            raw
        ),
        recurrence_rule=(
            recurrence_items[0]
            if recurrence_items
            else None
        ),
        recurrence={
            "rules":
                recurrence_items,
        },
        provider_created_at=_parse_datetime(
            raw.get(
                "created"
            )
        ),
        provider_updated_at=_parse_datetime(
            raw.get(
                "updated"
            )
        ),
        provider_data=raw,
        metadata=metadata,
    )


async def _google_get(
    access_token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization":
            f"Bearer {access_token}",
        "Accept":
            "application/json",
        "User-Agent":
            "Jace-Desktop",
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(
            f"{GOOGLE_CALENDAR_API}{path}",
            headers=headers,
            params=params,
        )

    if response.status_code == 410:
        raise GoogleSyncTokenExpired(
            "Google Calendar sync token expired."
        )

    if response.status_code == 401:
        raise GoogleCalendarSyncError(
            "Google rejected the current token. "
            "Reconnect the Google account."
        )

    if response.status_code == 403:
        raise GoogleCalendarSyncError(
            "Google denied Calendar access. Enable the Calendar API, "
            "add calendar.readonly to the OAuth consent configuration, "
            "then reconnect the Google account."
        )

    if response.status_code >= 400:
        detail = ""

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(
            payload,
            dict,
        ):
            error = payload.get(
                "error"
            )

            if isinstance(
                error,
                dict,
            ):
                message = error.get(
                    "message"
                )

                if isinstance(
                    message,
                    str,
                ):
                    detail = message

        raise GoogleCalendarSyncError(
            detail
            or (
                "Google Calendar API returned "
                f"HTTP {response.status_code}."
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleCalendarSyncError(
            "Google Calendar returned unreadable JSON."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise GoogleCalendarSyncError(
            "Google Calendar returned an unexpected response."
        )

    return payload


async def _list_google_calendars(
    access_token: str,
) -> list[dict[str, Any]]:
    calendars: list[
        dict[str, Any]
    ] = []
    page_token: str | None = None

    while True:
        params: dict[str, Any] = {
            "maxResults":
                CALENDAR_PAGE_SIZE,
            "showHidden":
                "true",
            "showDeleted":
                "false",
        }

        if page_token:
            params[
                "pageToken"
            ] = page_token

        payload = await _google_get(
            access_token,
            "/users/me/calendarList",
            params=params,
        )

        items = payload.get(
            "items"
        )

        if isinstance(
            items,
            list,
        ):
            calendars.extend(
                item
                for item in items
                if isinstance(
                    item,
                    dict,
                )
            )

        next_page = payload.get(
            "nextPageToken"
        )

        if not isinstance(
            next_page,
            str,
        ) or not next_page:
            break

        page_token = next_page

    return calendars


async def _soft_clear_source_events(
    session: AsyncSession,
    source_id: str,
) -> None:
    now = utc_now()

    await session.execute(
        update(
            CalendarEvent
        )
        .where(
            CalendarEvent.source_id
            == source_id,
            CalendarEvent.deleted_at.is_(
                None
            ),
        )
        .values(
            deleted_at=now,
            sync_state="synced",
            sync_error=None,
            updated_at=now,
        )
    )


async def _sync_source_events_once(
    session: AsyncSession,
    *,
    source: CalendarSource,
    access_token: str,
    sync_token: str | None,
) -> CalendarSyncResult:
    result = CalendarSyncResult(
        source_id=source.id,
        calendar_id=(
            source.external_calendar_id
            or ""
        ),
        name=source.name,
        mode=(
            "incremental"
            if sync_token
            else "full"
        ),
    )

    if not source.external_calendar_id:
        result.error = (
            "Google calendar source has no external calendar ID."
        )
        return result

    if not sync_token:
        # A fresh full sync is authoritative for the subset being imported.
        await _soft_clear_source_events(
            session,
            source.id,
        )

    page_token: str | None = None
    next_sync_token: str | None = None

    while True:
        params: dict[str, Any] = {
            "maxResults":
                EVENT_PAGE_SIZE,
            "singleEvents":
                "true",
            "showDeleted":
                "true",
        }

        if sync_token:
            params[
                "syncToken"
            ] = sync_token
        else:
            # Follow Google's documented sample: limit old history on initial
            # sync, then persist nextSyncToken for subsequent change-only sync.
            params[
                "timeMin"
            ] = (
                datetime.now(
                    timezone.utc
                )
                - timedelta(
                    days=INITIAL_HISTORY_DAYS
                )
            ).isoformat()

        if page_token:
            params[
                "pageToken"
            ] = page_token

        encoded_calendar_id = quote(
            source.external_calendar_id,
            safe="",
        )

        payload = await _google_get(
            access_token,
            (
                f"/calendars/"
                f"{encoded_calendar_id}/events"
            ),
            params=params,
        )

        result.pages += 1

        items = payload.get(
            "items"
        )

        if isinstance(
            items,
            list,
        ):
            for raw in items:
                if not isinstance(
                    raw,
                    dict,
                ):
                    continue

                normalized = _normalize_google_event(
                    raw,
                    source_timezone=source.timezone,
                )

                if normalized is None:
                    continue

                await upsert_provider_event(
                    session,
                    source,
                    normalized,
                )

                if normalized.deleted:
                    result.deleted += 1
                else:
                    result.changed += 1

        next_page = payload.get(
            "nextPageToken"
        )

        if isinstance(
            next_page,
            str,
        ) and next_page:
            page_token = next_page
            continue

        raw_sync_token = payload.get(
            "nextSyncToken"
        )

        if isinstance(
            raw_sync_token,
            str,
        ) and raw_sync_token:
            next_sync_token = raw_sync_token

        break

    if not next_sync_token:
        raise GoogleCalendarSyncError(
            "Google Calendar did not return nextSyncToken "
            "after the final page."
        )

    await mark_sync_success(
        session,
        source,
        sync_token=next_sync_token,
        provider_state={
            "provider":
                "google",
            "mode":
                result.mode,
            "single_events":
                True,
            "initial_history_days":
                INITIAL_HISTORY_DAYS,
        },
        full_sync=(
            result.mode
            == "full"
        ),
    )

    return result


async def _sync_source_events(
    session: AsyncSession,
    *,
    source: CalendarSource,
    access_token: str,
) -> CalendarSyncResult:
    sync_state = await get_or_create_sync_state(
        session,
        source,
    )

    try:
        return await _sync_source_events_once(
            session,
            source=source,
            access_token=access_token,
            sync_token=sync_state.sync_token,
        )
    except GoogleSyncTokenExpired:
        # Google requires the local store for this collection to be cleared and
        # a new full synchronization to be performed after HTTP 410.
        sync_state.sync_token = None
        sync_state.last_error = None
        await session.flush()

        return await _sync_source_events_once(
            session,
            source=source,
            access_token=access_token,
            sync_token=None,
        )



# JACE_STEP4C4C_DEDUP_FIX
def _google_connection_identity(
    connection: Any,
) -> str:
    """
    Stable identity used only to avoid syncing the same Google account twice.

    Prefer the verified email because it also matches older Jace connection
    rows that may predate oauth_subject persistence. Fall back to the OAuth
    subject, then account hint, then the row ID.
    """
    config = _loads_object(
        connection.config_json
    )

    email = config.get(
        "email"
    )

    if isinstance(email, str) and email.strip():
        return (
            "email:"
            + email.strip().casefold()
        )

    hint = connection.account_hint

    if (
        isinstance(hint, str)
        and "@" in hint
        and hint.strip()
    ):
        return (
            "email:"
            + hint.strip().casefold()
        )

    subject = config.get(
        "oauth_subject"
    )

    if (
        isinstance(subject, str)
        and subject.strip()
    ):
        return (
            "subject:"
            + subject.strip().casefold()
        )

    if isinstance(hint, str) and hint.strip():
        return (
            "hint:"
            + hint.strip().casefold()
        )

    return (
        "connection:"
        + str(connection.id)
    )


def _canonical_google_connection_groups(
    connections: list[Any],
) -> list[tuple[Any, list[Any]]]:
    """
    Group historical/current rows that refer to the same Google account.

    list_provider_connections() is already newest-first. Prefer the newest row
    that currently records Calendar permission, then the newest row overall.
    """
    groups: dict[
        str,
        list[Any],
    ] = {}

    for connection in connections:
        key = _google_connection_identity(
            connection
        )
        groups.setdefault(
            key,
            [],
        ).append(
            connection
        )

    result: list[
        tuple[Any, list[Any]]
    ] = []

    for rows in groups.values():
        canonical = next(
            (
                row
                for row in rows
                if _has_calendar_scope(
                    row.config_json
                )
            ),
            rows[0],
        )

        result.append(
            (
                canonical,
                rows,
            )
        )

    return result


async def _source_event_count(
    session: AsyncSession,
    source_id: str,
) -> int:
    return int(
        (
            await session.execute(
                select(
                    func.count(
                        CalendarEvent.id
                    )
                ).where(
                    CalendarEvent.source_id
                    == source_id
                )
            )
        ).scalar_one()
    )


async def _reconcile_google_sources_for_account(
    session: AsyncSession,
    *,
    canonical_connection: Any,
    connection_rows: list[Any],
) -> tuple[int, int]:
    """
    Collapse duplicate cached Google calendars created by historical duplicate
    connection rows.

    This only mutates Jace's local cache. Google Calendar is never written to.
    Duplicate cached events are discarded and the surviving source's sync token
    is cleared so the next operation performs a clean authoritative full sync.
    """
    connection_ids = [
        str(row.id)
        for row in connection_rows
    ]

    statement = (
        select(
            CalendarSource
        )
        .where(
            CalendarSource.provider_id
            == "google",
            CalendarSource.connection_id.in_(
                connection_ids
            ),
        )
        .order_by(
            CalendarSource.updated_at.desc()
        )
    )

    sources = list(
        (
            await session.execute(
                statement
            )
        ).scalars().all()
    )

    by_calendar: dict[
        str,
        list[CalendarSource],
    ] = {}

    for source in sources:
        external_id = (
            source.external_calendar_id
        )

        if not external_id:
            continue

        by_calendar.setdefault(
            external_id,
            [],
        ).append(
            source
        )

    removed_sources = 0
    removed_events = 0

    for external_id, rows in by_calendar.items():
        canonical_source = next(
            (
                row
                for row in rows
                if row.connection_id
                == canonical_connection.id
            ),
            rows[0],
        )

        duplicates = [
            row
            for row in rows
            if row.id
            != canonical_source.id
        ]

        if duplicates:
            # Force a clean full re-import after deleting duplicate caches.
            state = await session.get(
                CalendarSyncState,
                canonical_source.id,
            )

            if state is not None:
                state.sync_token = None
                state.delta_url = None
                state.last_error = None
                state.updated_at = utc_now()

        for duplicate in duplicates:
            removed_events += await _source_event_count(
                session,
                duplicate.id,
            )

            # CalendarEvent and CalendarSyncState both have ON DELETE CASCADE.
            await session.delete(
                duplicate
            )
            removed_sources += 1

        # A surviving source from an older connection is adopted by the
        # canonical current connection instead of creating a second source.
        adopted_from_old_connection = (
            canonical_source.connection_id
            != canonical_connection.id
        )

        canonical_source.connection_id = (
            canonical_connection.id
        )
        canonical_source.account_hint = (
            canonical_connection.account_hint
        )
        canonical_source.updated_at = (
            utc_now()
        )

        # If we adopted an old source, its cursor belongs to the same logical
        # Google account/calendar, but forcing one full sync is safer and also
        # guarantees the cache is complete after reconciliation.
        if adopted_from_old_connection:
            state = await session.get(
                CalendarSyncState,
                canonical_source.id,
            )
            if state is not None:
                state.sync_token = None
                state.delta_url = None
                state.last_error = None
                state.updated_at = utc_now()

    await session.flush()

    return (
        removed_sources,
        removed_events,
    )


async def _existing_google_sources(
    session: AsyncSession,
    connection_id: str,
) -> list[CalendarSource]:
    statement = (
        select(
            CalendarSource
        )
        .where(
            CalendarSource.provider_id
            == "google",
            CalendarSource.connection_id
            == connection_id,
        )
    )

    return list(
        (
            await session.execute(
                statement
            )
        ).scalars().all()
    )


async def _sync_google_calendars_unlocked(
    session: AsyncSession,
) -> GoogleCalendarSyncSummary:
    summary = GoogleCalendarSyncSummary()

    connections = await list_provider_connections(
        session,
        "google",
    )

    configured = [
        row
        for row in connections
        if row.status
        == "configured"
    ]

    summary.connections_seen = len(
        configured
    )

    if not configured:
        summary.status = (
            "not_connected"
        )
        return summary

    connection_groups = _canonical_google_connection_groups(
        configured
    )

    summary.duplicate_connections_ignored = (
        len(configured)
        - len(connection_groups)
    )

    for connection, connection_rows in connection_groups:
        removed_sources, removed_events = (
            await _reconcile_google_sources_for_account(
                session,
                canonical_connection=connection,
                connection_rows=connection_rows,
            )
        )
        summary.duplicate_sources_removed += (
            removed_sources
        )
        summary.duplicate_events_removed += (
            removed_events
        )

        connection_result = ConnectionSyncResult(
            connection_id=connection.id,
            account_hint=connection.account_hint,
            status="pending",
        )
        summary.connections.append(
            connection_result
        )

        if not _has_calendar_scope(
            connection.config_json
        ):
            message = (
                f"{connection.account_hint or connection.label}: "
                "Google Calendar read permission is not granted. "
                "Reconnect Google after adding calendar.readonly."
            )
            connection_result.status = (
                "needs_access"
            )
            connection_result.errors.append(
                message
            )
            summary.errors.append(
                message
            )
            summary.needs_reconnect = True
            continue

        try:
            access_token = await valid_access_token(
                session,
                connection,
            )

            calendar_entries = await _list_google_calendars(
                access_token
            )

            connection_result.calendars_discovered = len(
                calendar_entries
            )
            summary.calendars_discovered += len(
                calendar_entries
            )

            seen_ids: set[
                str
            ] = set()

            for entry in calendar_entries:
                calendar_id = entry.get(
                    "id"
                )

                if not isinstance(
                    calendar_id,
                    str,
                ) or not calendar_id:
                    continue

                if entry.get(
                    "deleted"
                ):
                    continue

                seen_ids.add(
                    calendar_id
                )

                access_role = str(
                    entry.get(
                        "accessRole"
                    )
                    or "reader"
                )
                timezone_name = _safe_timezone(
                    entry.get(
                        "timeZone"
                    ),
                    DEFAULT_TIMEZONE,
                )
                color = entry.get(
                    "backgroundColor"
                )

                if not (
                    isinstance(
                        color,
                        str,
                    )
                    and color.startswith(
                        "#"
                    )
                ):
                    color = "#4285f4"

                source = await upsert_provider_calendar_source(
                    session,
                    provider_id="google",
                    connection_id=connection.id,
                    external_calendar_id=calendar_id,
                    name=str(
                        entry.get(
                            "summaryOverride"
                        )
                        or entry.get(
                            "summary"
                        )
                        or "Google Calendar"
                    ),
                    account_hint=connection.account_hint,
                    color=color,
                    timezone_name=timezone_name,
                    read_only=(
                        access_role
                        not in {
                            "writer",
                            "owner",
                        }
                    ),
                    is_primary=bool(
                        entry.get(
                            "primary"
                        )
                    ),
                    metadata={
                        "description":
                            entry.get(
                                "description"
                            ),
                        "location":
                            entry.get(
                                "location"
                            ),
                        "access_role":
                            access_role,
                        "foreground_color":
                            entry.get(
                                "foregroundColor"
                            ),
                        "selected":
                            entry.get(
                                "selected"
                            ),
                        "hidden":
                            entry.get(
                                "hidden"
                            ),
                    },
                )

                if source.sync_status == "missing":
                    # The calendar was previously removed from Google and has
                    # now reappeared. Restore provider sync and visibility.
                    source.sync_enabled = True
                    source.enabled = True
                    source.sync_status = "pending"

                if not source.sync_enabled:
                    continue

                try:
                    calendar_result = (
                        await _sync_source_events(
                            session,
                            source=source,
                            access_token=access_token,
                        )
                    )
                    connection_result.calendars.append(
                        calendar_result
                    )
                    connection_result.calendars_synced += 1
                    connection_result.events_changed += (
                        calendar_result.changed
                    )
                    connection_result.events_deleted += (
                        calendar_result.deleted
                    )
                except Exception as exc:
                    message = (
                        f"{source.name}: {exc}"
                    )
                    await mark_sync_error(
                        session,
                        source,
                        str(exc),
                    )
                    connection_result.errors.append(
                        message
                    )
                    connection_result.calendars.append(
                        CalendarSyncResult(
                            source_id=source.id,
                            calendar_id=calendar_id,
                            name=source.name,
                            mode="error",
                            error=str(exc),
                        )
                    )

            # If a calendar disappeared from Google's CalendarList, stop
            # synchronizing it but retain its cached events for audit/history.
            existing_sources = await _existing_google_sources(
                session,
                connection.id,
            )

            for source in existing_sources:
                external_id = (
                    source.external_calendar_id
                )

                if (
                    external_id
                    and external_id
                    not in seen_ids
                ):
                    source.sync_enabled = False
                    source.enabled = False
                    source.sync_status = (
                        "missing"
                    )
                    source.updated_at = (
                        utc_now()
                    )

            connection_result.status = (
                "ok"
                if not connection_result.errors
                else "partial"
            )
            if connection_result.errors:
                summary.errors.extend(
                    connection_result.errors
                )
            summary.connections_synced += 1
            summary.calendars_synced += (
                connection_result.calendars_synced
            )
            summary.events_changed += (
                connection_result.events_changed
            )
            summary.events_deleted += (
                connection_result.events_deleted
            )

        except Exception as exc:
            message = (
                f"{connection.account_hint or connection.label}: "
                f"{exc}"
            )
            connection_result.status = (
                "error"
            )
            connection_result.errors.append(
                message
            )
            summary.errors.append(
                message
            )

    if summary.errors:
        summary.status = (
            "partial"
            if summary.connections_synced
            else "error"
        )

    await session.flush()

    return summary


_GOOGLE_SYNC_LOCK = asyncio.Lock()


async def sync_google_calendars(
    session: AsyncSession,
) -> GoogleCalendarSyncSummary:
    async with _GOOGLE_SYNC_LOCK:
        return await _sync_google_calendars_unlocked(
            session
        )
