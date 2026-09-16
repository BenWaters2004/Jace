from __future__ import annotations

# JACE_STEP4C4D_MICROSOFT_CALENDAR_SYNC

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import html
import re
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jace.calendar.models import (
    CalendarEvent,
    CalendarSource,
    CalendarSyncState,
)
from jace.calendar.normalized import NormalizedCalendarEvent
from jace.calendar.service import (
    DEFAULT_TIMEZONE,
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


GRAPH_API = "https://graph.microsoft.com/v1.0"
MICROSOFT_CALENDAR_READ_SCOPE = "Calendars.Read"
HTTP_TIMEOUT_SECONDS = 30.0
CALENDAR_PAGE_SIZE = 100
EVENT_PAGE_SIZE = 1000

# Stable v1.0 calendarView sync window. We deliberately avoid Microsoft's beta
# per-calendar delta endpoint in Jace's core calendar layer.
HISTORY_DAYS = 365
FUTURE_DAYS = 730


class MicrosoftCalendarSyncError(RuntimeError):
    pass


@dataclass(slots=True)
class CalendarSyncResult:
    source_id: str
    calendar_id: str
    name: str
    changed: int = 0
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
    errors: list[str] = field(default_factory=list)
    calendars: list[CalendarSyncResult] = field(default_factory=list)


@dataclass(slots=True)
class MicrosoftCalendarSyncSummary:
    provider_id: str = "microsoft"
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
    stale_sources_removed: int = 0
    stale_events_removed: int = 0
    errors: list[str] = field(default_factory=list)
    connections: list[ConnectionSyncResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _scope_set(config_json: str) -> set[str]:
    config = _loads_object(config_json)
    raw = config.get("scopes", [])

    if not isinstance(raw, list):
        return set()

    result: set[str] = set()

    for value in raw:
        if not isinstance(value, str):
            continue

        cleaned = value.strip().casefold()

        if not cleaned:
            continue

        result.add(cleaned)

        # Microsoft can record delegated Graph scopes in either short or
        # resource-qualified form.
        if "/" in cleaned:
            result.add(cleaned.rsplit("/", 1)[-1])

    return result


def _has_calendar_scope(config_json: str) -> bool:
    scopes = _scope_set(config_json)

    return (
        MICROSOFT_CALENDAR_READ_SCOPE.casefold()
        in scopes
        or "calendars.readwrite" in scopes
    )


def _connection_identity(connection: Any) -> str:
    config = _loads_object(connection.config_json)

    email = config.get("email")
    if isinstance(email, str) and email.strip():
        return "email:" + email.strip().casefold()

    hint = connection.account_hint
    if isinstance(hint, str) and "@" in hint and hint.strip():
        return "email:" + hint.strip().casefold()

    subject = config.get("oauth_subject")
    if isinstance(subject, str) and subject.strip():
        return "subject:" + subject.strip().casefold()

    if isinstance(hint, str) and hint.strip():
        return "hint:" + hint.strip().casefold()

    return "connection:" + str(connection.id)


def _canonical_connection_groups(
    connections: list[Any],
) -> list[tuple[Any, list[Any]]]:
    groups: dict[str, list[Any]] = {}

    for connection in connections:
        groups.setdefault(
            _connection_identity(connection),
            [],
        ).append(connection)

    result: list[tuple[Any, list[Any]]] = []

    for rows in groups.values():
        canonical = next(
            (
                row
                for row in rows
                if _has_calendar_scope(row.config_json)
            ),
            rows[0],
        )
        result.append((canonical, rows))

    return result


def _parse_graph_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    raw = value.strip()

    # Graph often returns fractional seconds with seven digits; Python accepts
    # up to six. Truncate only the fractional part.
    match = re.match(
        r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
        r"(?:\.(?P<fraction>\d+))?"
        r"(?P<suffix>Z|[+-]\d{2}:\d{2})?$",
        raw,
    )

    if match:
        fraction = match.group("fraction")
        suffix = match.group("suffix") or ""
        raw = match.group("head")

        if fraction:
            raw += "." + fraction[:6]

        raw += suffix

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        # Calendar requests ask Graph to return UTC via Prefer.
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _date_from_graph_datetime(value: object) -> date | None:
    if not isinstance(value, str):
        return None

    raw = value.strip()

    if len(raw) < 10:
        return None

    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _address(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    email_address = value.get("emailAddress")

    if not isinstance(email_address, dict):
        return {}

    result: dict[str, Any] = {}

    name = email_address.get("name")
    address = email_address.get("address")

    if isinstance(name, str) and name:
        result["name"] = name

    if isinstance(address, str) and address:
        result["email"] = address

    return result


def _attendees(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    result: list[dict[str, Any]] = []

    for item in value:
        if not isinstance(item, dict):
            continue

        attendee = _address(item)

        attendee_type = item.get("type")
        if isinstance(attendee_type, str):
            attendee["type"] = attendee_type

        status = item.get("status")
        if isinstance(status, dict):
            response = status.get("response")
            response_time = status.get("time")

            if response is not None:
                attendee["response"] = response
            if response_time is not None:
                attendee["response_time"] = response_time

        if attendee:
            result.append(attendee)

    return result


def _strip_html(value: str) -> str:
    text = re.sub(
        r"(?is)<(?:script|style).*?>.*?</(?:script|style)>",
        " ",
        value,
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _description(event: dict[str, Any]) -> str:
    body = event.get("body")

    if not isinstance(body, dict):
        preview = event.get("bodyPreview")
        return preview if isinstance(preview, str) else ""

    content = body.get("content")

    if not isinstance(content, str):
        return ""

    content_type = body.get("contentType")

    if (
        isinstance(content_type, str)
        and content_type.casefold() == "html"
    ):
        return _strip_html(content)

    return content.strip()


def _meeting_url(event: dict[str, Any]) -> str | None:
    online = event.get("onlineMeeting")

    if isinstance(online, dict):
        join_url = online.get("joinUrl")

        if isinstance(join_url, str) and join_url:
            return join_url

    legacy = event.get("onlineMeetingUrl")

    if isinstance(legacy, str) and legacy:
        return legacy

    return None


def _normalize_event(
    raw: dict[str, Any],
) -> NormalizedCalendarEvent | None:
    event_id = raw.get("id")

    if not isinstance(event_id, str) or not event_id:
        return None

    # Full-window refresh uses absence from the authoritative calendarView to
    # model deletions, so individual rows normally aren't tombstones here.
    if raw.get("@removed") is not None:
        return NormalizedCalendarEvent(
            external_event_id=event_id,
            title=str(raw.get("subject") or "Deleted event"),
            all_day=False,
            timezone="UTC",
            provider_data=raw,
            deleted=True,
        )

    is_all_day = bool(raw.get("isAllDay"))
    start = raw.get("start")
    end = raw.get("end")

    if not isinstance(start, dict) or not isinstance(end, dict):
        return None

    start_value = start.get("dateTime")
    end_value = end.get("dateTime")

    if is_all_day:
        start_date = _date_from_graph_datetime(start_value)
        end_date = _date_from_graph_datetime(end_value)

        if start_date is None or end_date is None:
            return None

        start_at = None
        end_at = None
    else:
        start_at = _parse_graph_datetime(start_value)
        end_at = _parse_graph_datetime(end_value)
        start_date = None
        end_date = None

        if start_at is None or end_at is None:
            return None

    show_as = str(raw.get("showAs") or "busy").casefold()

    status = (
        "cancelled"
        if raw.get("isCancelled")
        else "tentative"
        if show_as == "tentative"
        else "confirmed"
    )

    sensitivity = str(
        raw.get("sensitivity")
        or "normal"
    ).casefold()

    visibility = {
        "normal": "default",
        "personal": "private",
        "private": "private",
        "confidential": "confidential",
    }.get(sensitivity, "default")

    recurrence = raw.get("recurrence")
    recurrence_payload = (
        recurrence
        if isinstance(recurrence, dict)
        else {}
    )

    series_master_id = raw.get("seriesMasterId")

    organizer = _address(raw.get("organizer"))

    reminders: list[dict[str, Any]] = []

    if raw.get("isReminderOn"):
        reminder_minutes = raw.get(
            "reminderMinutesBeforeStart"
        )
        reminders.append(
            {
                "method": "provider",
                "minutes_before": reminder_minutes,
            }
        )

    original_start = raw.get("originalStart")

    metadata: dict[str, Any] = {
        "type": raw.get("type"),
        "web_link": raw.get("webLink"),
        "original_start": original_start,
        "original_start_timezone": raw.get(
            "originalStartTimeZone"
        ),
        "original_end_timezone": raw.get(
            "originalEndTimeZone"
        ),
        "is_online_meeting": raw.get(
            "isOnlineMeeting"
        ),
        "online_meeting_provider": raw.get(
            "onlineMeetingProvider"
        ),
        "response_status": raw.get(
            "responseStatus"
        ),
    }

    return NormalizedCalendarEvent(
        external_event_id=event_id,
        title=str(raw.get("subject") or "Untitled event"),
        all_day=is_all_day,
        timezone="UTC",
        start_at=start_at,
        end_at=end_at,
        start_date=start_date,
        end_date_exclusive=end_date,
        external_series_id=(
            series_master_id
            if isinstance(series_master_id, str)
            else None
        ),
        original_event_id=None,
        ical_uid=(
            raw.get("iCalUId")
            if isinstance(raw.get("iCalUId"), str)
            else None
        ),
        external_version=(
            raw.get("@odata.etag")
            if isinstance(raw.get("@odata.etag"), str)
            else raw.get("changeKey")
            if isinstance(raw.get("changeKey"), str)
            else None
        ),
        description=_description(raw),
        location=(
            str(
                (
                    raw.get("location")
                    if isinstance(raw.get("location"), dict)
                    else {}
                ).get("displayName")
                or ""
            )
        ),
        meeting_url=_meeting_url(raw),
        status=status,
        availability=(
            "free"
            if show_as in {"free", "workingelsewhere"}
            else "busy"
        ),
        visibility=visibility,
        organizer=organizer,
        attendees=_attendees(raw.get("attendees")),
        reminders=reminders,
        recurrence_rule=None,
        recurrence=recurrence_payload,
        provider_created_at=_parse_graph_datetime(
            raw.get("createdDateTime")
        ),
        provider_updated_at=_parse_graph_datetime(
            raw.get("lastModifiedDateTime")
        ),
        provider_data=raw,
        metadata=metadata,
    )


async def _graph_get_url(
    access_token: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
        "Prefer": (
            'outlook.timezone="UTC", '
            f"odata.maxpagesize={EVENT_PAGE_SIZE}"
        ),
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(
            url,
            headers=headers,
            params=params,
        )

    if response.status_code == 401:
        raise MicrosoftCalendarSyncError(
            "Microsoft rejected the current token. "
            "Reconnect the Microsoft account."
        )

    if response.status_code == 403:
        raise MicrosoftCalendarSyncError(
            "Microsoft denied Calendar access. Add delegated Calendars.Read "
            "to the Jace Entra application, then reconnect Microsoft."
        )

    if response.status_code >= 400:
        detail = ""

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")

            if isinstance(error, dict):
                raw_message = error.get("message")
                raw_code = error.get("code")

                if isinstance(raw_message, str):
                    detail = raw_message[:500]

                if (
                    isinstance(raw_code, str)
                    and raw_code
                    and raw_code not in detail
                ):
                    detail = (
                        f"{detail} ({raw_code})"
                        if detail
                        else raw_code
                    )

        raise MicrosoftCalendarSyncError(
            detail
            or (
                "Microsoft Graph Calendar request returned "
                f"HTTP {response.status_code}."
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise MicrosoftCalendarSyncError(
            "Microsoft Graph Calendar returned unreadable JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise MicrosoftCalendarSyncError(
            "Microsoft Graph Calendar returned an unexpected response."
        )

    return payload


async def _graph_get(
    access_token: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _graph_get_url(
        access_token,
        f"{GRAPH_API}{path}",
        params=params,
    )


async def _list_calendars(
    access_token: str,
) -> list[dict[str, Any]]:
    url = f"{GRAPH_API}/me/calendars"
    params: dict[str, Any] | None = {
        "$top": CALENDAR_PAGE_SIZE,
    }
    calendars: list[dict[str, Any]] = []

    while url:
        payload = await _graph_get_url(
            access_token,
            url,
            params=params,
        )
        params = None

        values = payload.get("value")

        if isinstance(values, list):
            calendars.extend(
                item
                for item in values
                if isinstance(item, dict)
            )

        next_link = payload.get("@odata.nextLink")
        url = (
            next_link
            if isinstance(next_link, str)
            and next_link
            else ""
        )

    return calendars


def _calendar_color(raw: dict[str, Any]) -> str:
    hex_color = raw.get("hexColor")

    if (
        isinstance(hex_color, str)
        and re.fullmatch(
            r"#[0-9A-Fa-f]{6}",
            hex_color,
        )
    ):
        return hex_color

    color = str(raw.get("color") or "").casefold()

    mapping = {
        "lightblue": "#7fbeeb",
        "lightgreen": "#7ecf9a",
        "lightorange": "#f2aa67",
        "lightgray": "#aeb4bc",
        "lightyellow": "#e2c75b",
        "lightteal": "#58bfc0",
        "lightpink": "#e891ad",
        "lightbrown": "#b89578",
        "lightred": "#e17676",
        "maxcolor": "#777777",
    }

    return mapping.get(color, "#5b8def")


async def _source_event_count(
    session: AsyncSession,
    source_id: str,
) -> int:
    return int(
        (
            await session.execute(
                select(func.count(CalendarEvent.id)).where(
                    CalendarEvent.source_id == source_id
                )
            )
        ).scalar_one()
    )


async def _reconcile_source_identity(
    session: AsyncSession,
    *,
    canonical_connection: Any,
    connection_rows: list[Any],
    external_calendar_id: str,
) -> tuple[CalendarSource | None, int, int]:
    connection_ids = [
        str(row.id)
        for row in connection_rows
    ]

    identity_conditions = [
        CalendarSource.connection_id.in_(
            connection_ids
        )
    ]

    hint = canonical_connection.account_hint

    if isinstance(hint, str) and hint.strip():
        identity_conditions.append(
            func.lower(CalendarSource.account_hint)
            == hint.strip().casefold()
        )

    statement = (
        select(CalendarSource)
        .where(
            CalendarSource.provider_id == "microsoft",
            CalendarSource.external_calendar_id
            == external_calendar_id,
            or_(*identity_conditions),
        )
        .order_by(CalendarSource.updated_at.desc())
    )

    rows = list(
        (
            await session.execute(statement)
        ).scalars().all()
    )

    if not rows:
        return None, 0, 0

    canonical = next(
        (
            row
            for row in rows
            if row.connection_id
            == canonical_connection.id
        ),
        rows[0],
    )

    duplicate_rows = [
        row
        for row in rows
        if row.id != canonical.id
    ]

    removed_events = 0

    for duplicate in duplicate_rows:
        removed_events += await _source_event_count(
            session,
            duplicate.id,
        )
        await session.delete(duplicate)

    canonical.connection_id = canonical_connection.id
    canonical.account_hint = canonical_connection.account_hint
    canonical.enabled = True
    canonical.sync_enabled = True
    canonical.updated_at = utc_now()

    await session.flush()

    return (
        canonical,
        len(duplicate_rows),
        removed_events,
    )


async def _existing_sources_for_account(
    session: AsyncSession,
    *,
    connection: Any,
    connection_rows: list[Any],
) -> list[CalendarSource]:
    ids = [
        str(row.id)
        for row in connection_rows
    ]

    conditions = [
        CalendarSource.connection_id.in_(ids)
    ]

    hint = connection.account_hint

    if isinstance(hint, str) and hint.strip():
        conditions.append(
            func.lower(CalendarSource.account_hint)
            == hint.strip().casefold()
        )

    statement = (
        select(CalendarSource)
        .where(
            CalendarSource.provider_id == "microsoft",
            or_(*conditions),
        )
    )

    return list(
        (
            await session.execute(statement)
        ).scalars().all()
    )


async def _clear_source_cache(
    session: AsyncSession,
    source_id: str,
) -> int:
    count = await _source_event_count(
        session,
        source_id,
    )
    now = utc_now()

    await session.execute(
        update(CalendarEvent)
        .where(
            CalendarEvent.source_id == source_id,
            CalendarEvent.deleted_at.is_(None),
        )
        .values(
            deleted_at=now,
            sync_state="synced",
            sync_error=None,
            updated_at=now,
        )
    )

    return count


async def _sync_calendar_events(
    session: AsyncSession,
    *,
    source: CalendarSource,
    access_token: str,
) -> CalendarSyncResult:
    if not source.external_calendar_id:
        raise MicrosoftCalendarSyncError(
            "Microsoft calendar source has no calendar ID."
        )

    result = CalendarSyncResult(
        source_id=source.id,
        calendar_id=source.external_calendar_id,
        name=source.name,
    )

    await _clear_source_cache(
        session,
        source.id,
    )

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=HISTORY_DAYS)
    window_end = now + timedelta(days=FUTURE_DAYS)

    calendar_id = quote(
        source.external_calendar_id,
        safe="",
    )

    url = (
        f"{GRAPH_API}/me/calendars/"
        f"{calendar_id}/calendarView"
    )
    params: dict[str, Any] | None = {
        "startDateTime": window_start.isoformat(),
        "endDateTime": window_end.isoformat(),
        "$top": EVENT_PAGE_SIZE,
    }

    while url:
        payload = await _graph_get_url(
            access_token,
            url,
            params=params,
        )
        params = None
        result.pages += 1

        values = payload.get("value")

        if isinstance(values, list):
            for raw in values:
                if not isinstance(raw, dict):
                    continue

                normalized = _normalize_event(raw)

                if normalized is None:
                    continue

                await upsert_provider_event(
                    session,
                    source,
                    normalized,
                )

                if not normalized.deleted:
                    result.changed += 1

        next_link = payload.get("@odata.nextLink")
        url = (
            next_link
            if isinstance(next_link, str)
            and next_link
            else ""
        )

    await mark_sync_success(
        session,
        source,
        delta_url=None,
        window_start_at=window_start,
        window_end_at=window_end,
        provider_state={
            "provider": "microsoft",
            "mode": "v1_calendar_view_full_window",
            "history_days": HISTORY_DAYS,
            "future_days": FUTURE_DAYS,
        },
        full_sync=True,
    )

    return result


async def sync_microsoft_calendars(
    session: AsyncSession,
) -> MicrosoftCalendarSyncSummary:
    summary = MicrosoftCalendarSyncSummary()

    connections = await list_provider_connections(
        session,
        "microsoft",
    )

    configured = [
        row
        for row in connections
        if row.status == "configured"
    ]

    summary.connections_seen = len(configured)

    if not configured:
        summary.status = "not_connected"
        return summary

    groups = _canonical_connection_groups(
        configured
    )

    summary.duplicate_connections_ignored = (
        len(configured)
        - len(groups)
    )

    for connection, connection_rows in groups:
        connection_result = ConnectionSyncResult(
            connection_id=connection.id,
            account_hint=connection.account_hint,
            status="pending",
        )
        summary.connections.append(connection_result)

        if not _has_calendar_scope(
            connection.config_json
        ):
            message = (
                f"{connection.account_hint or connection.label}: "
                "Microsoft Calendars.Read is not granted. "
                "Reconnect Microsoft after adding the delegated permission."
            )
            connection_result.status = "needs_access"
            connection_result.errors.append(message)
            summary.errors.append(message)
            summary.needs_reconnect = True
            continue

        try:
            access_token = await valid_access_token(
                session,
                connection,
            )

            calendars = await _list_calendars(
                access_token
            )

            connection_result.calendars_discovered = len(
                calendars
            )
            summary.calendars_discovered += len(
                calendars
            )

            seen_ids: set[str] = set()

            for raw_calendar in calendars:
                calendar_id = raw_calendar.get("id")

                if (
                    not isinstance(calendar_id, str)
                    or not calendar_id
                ):
                    continue

                seen_ids.add(calendar_id)

                (
                    existing_source,
                    removed_sources,
                    removed_events,
                ) = await _reconcile_source_identity(
                    session,
                    canonical_connection=connection,
                    connection_rows=connection_rows,
                    external_calendar_id=calendar_id,
                )

                summary.duplicate_sources_removed += (
                    removed_sources
                )
                summary.duplicate_events_removed += (
                    removed_events
                )

                owner = _address(
                    {
                        "emailAddress":
                            raw_calendar.get("owner")
                    }
                    if isinstance(
                        raw_calendar.get("owner"),
                        dict,
                    )
                    else {}
                )

                source = await upsert_provider_calendar_source(
                    session,
                    provider_id="microsoft",
                    connection_id=connection.id,
                    external_calendar_id=calendar_id,
                    name=str(
                        raw_calendar.get("name")
                        or "Outlook Calendar"
                    ),
                    account_hint=connection.account_hint,
                    color=_calendar_color(
                        raw_calendar
                    ),
                    timezone_name=DEFAULT_TIMEZONE,
                    read_only=not bool(
                        raw_calendar.get(
                            "canEdit",
                            False,
                        )
                    ),
                    is_primary=bool(
                        raw_calendar.get(
                            "isDefaultCalendar"
                        )
                    ),
                    metadata={
                        "owner": owner,
                        "can_edit": raw_calendar.get(
                            "canEdit"
                        ),
                        "can_share": raw_calendar.get(
                            "canShare"
                        ),
                        "can_view_private_items":
                            raw_calendar.get(
                                "canViewPrivateItems"
                            ),
                        "is_removable":
                            raw_calendar.get(
                                "isRemovable"
                            ),
                        "is_tallying_responses":
                            raw_calendar.get(
                                "isTallyingResponses"
                            ),
                        "default_online_meeting_provider":
                            raw_calendar.get(
                                "defaultOnlineMeetingProvider"
                            ),
                        "allowed_online_meeting_providers":
                            raw_calendar.get(
                                "allowedOnlineMeetingProviders"
                            ),
                    },
                )

                if existing_source is not None:
                    source = existing_source
                    source.name = str(
                        raw_calendar.get("name")
                        or source.name
                    )
                    # JACE_STEP4C4E_MICROSOFT_COLOR_PRESERVATION
                    # Calendar service owns provider/user colour merging.
                    source.read_only = not bool(
                        raw_calendar.get(
                            "canEdit",
                            False,
                        )
                    )
                    source.is_primary = bool(
                        raw_calendar.get(
                            "isDefaultCalendar"
                        )
                    )

                if not source.sync_enabled:
                    continue

                try:
                    calendar_result = (
                        await _sync_calendar_events(
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
                except Exception as exc:
                    await mark_sync_error(
                        session,
                        source,
                        str(exc),
                    )
                    message = (
                        f"{source.name}: {exc}"
                    )
                    connection_result.errors.append(
                        message
                    )
                    connection_result.calendars.append(
                        CalendarSyncResult(
                            source_id=source.id,
                            calendar_id=calendar_id,
                            name=source.name,
                            error=str(exc),
                        )
                    )

            # Remove stale local Microsoft sources for this logical account.
            existing_sources = await _existing_sources_for_account(
                session,
                connection=connection,
                connection_rows=connection_rows,
            )

            for source in existing_sources:
                external_id = source.external_calendar_id

                if (
                    external_id
                    and external_id not in seen_ids
                ):
                    summary.stale_events_removed += (
                        await _source_event_count(
                            session,
                            source.id,
                        )
                    )
                    await session.delete(source)
                    summary.stale_sources_removed += 1

            await session.flush()

            connection_result.status = (
                "ok"
                if not connection_result.errors
                else "partial"
            )
            summary.connections_synced += 1
            summary.calendars_synced += (
                connection_result.calendars_synced
            )
            summary.events_changed += (
                connection_result.events_changed
            )

        except Exception as exc:
            message = (
                f"{connection.account_hint or connection.label}: "
                f"{exc}"
            )
            connection_result.status = "error"
            connection_result.errors.append(message)
            summary.errors.append(message)

    if summary.errors:
        summary.status = (
            "partial"
            if summary.connections_synced
            else "error"
        )

    await session.flush()

    return summary
