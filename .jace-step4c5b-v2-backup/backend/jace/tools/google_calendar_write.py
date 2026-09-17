from __future__ import annotations

# JACE_STEP4C5B_GOOGLE_SCHEDULING_WRITE

import json
from datetime import timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel

from jace.calendar.google_sync import (
    GOOGLE_CALENDAR_API,
    HTTP_TIMEOUT_SECONDS,
    _normalize_google_event,
    _sync_source_events,
)
from jace.calendar.service import upsert_provider_event
from jace.db.models import utc_now
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.calendar_write_common import (
    CalendarAttendeeInput,
    CalendarCreateEventInput,
    CalendarModifyEventInput,
    CalendarRecurrenceInput,
    CalendarReminderInput,
    aware_datetime,
    effective_timezone,
    existing_attendee_count,
    first_occurrence_date,
    local_event_summary,
    mark_series_deleted,
    mark_series_pending,
    resolve_create_source,
    resolve_modify_event,
    source_metadata,
    target_external_event_id,
)
from jace.tools.gmail import _google_access_token
from jace.tools.registry import registry


def _error(response: httpx.Response, fallback: str) -> ToolError:
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        raw = payload.get("error")
        if isinstance(raw, dict) and isinstance(raw.get("message"), str):
            detail = raw["message"].strip()
        elif isinstance(raw, str):
            detail = raw.strip()
    if response.status_code == 401:
        return ToolError(
            "Google rejected the current token. Reconnect Google in Settings > Connections."
        )
    if response.status_code == 403:
        return ToolError(
            "Google denied Calendar write access. Confirm calendar.events is granted."
        )
    if response.status_code == 404:
        return ToolError(detail or "Google Calendar could not find that calendar/event.")
    return ToolError(detail[:500] or fallback)


async def _request(
    access_token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.request(
            method,
            f"{GOOGLE_CALENDAR_API}{path}",
            headers=headers,
            json=payload,
            params=params,
        )

    expected = {204} if method == "DELETE" else {200, 201}
    if response.status_code not in expected:
        raise _error(response, "Google Calendar write request failed.")
    if not response.content:
        return {}
    try:
        value = response.json()
    except ValueError as exc:
        raise ToolError(
            "Google Calendar returned an unreadable write response."
        ) from exc
    if not isinstance(value, dict):
        raise ToolError(
            "Google Calendar returned an unexpected write response."
        )
    return value


def _timed(value, timezone_name: str) -> dict[str, str]:
    return {
        "dateTime": aware_datetime(value, timezone_name).isoformat(),
        "timeZone": timezone_name,
    }


def _attendees(
    attendees: list[CalendarAttendeeInput],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for attendee in attendees:
        row: dict[str, Any] = {"email": attendee.email}
        if attendee.name:
            row["displayName"] = attendee.name
        if attendee.type == "optional":
            row["optional"] = True
        if attendee.type == "resource":
            row["resource"] = True
        result.append(row)
    return result


def _reminders(
    reminders: list[CalendarReminderInput],
) -> dict[str, Any]:
    if not reminders:
        return {"useDefault": False, "overrides": []}
    return {
        "useDefault": False,
        "overrides": [
            {
                "method": reminder.method,
                "minutes": reminder.minutes_before_start,
            }
            for reminder in reminders
        ],
    }


_WEEKDAY = {
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
    "sunday": "SU",
}


def _rrule(
    recurrence: CalendarRecurrenceInput,
    timezone_name: str,
) -> str:
    parts = [
        f"FREQ={recurrence.frequency.upper()}",
        f"INTERVAL={recurrence.interval}",
    ]
    if recurrence.weekdays:
        parts.append(
            "BYDAY=" + ",".join(_WEEKDAY[item] for item in recurrence.weekdays)
        )
    if recurrence.day_of_month is not None:
        parts.append(f"BYMONTHDAY={recurrence.day_of_month}")
    if recurrence.month is not None:
        parts.append(f"BYMONTH={recurrence.month}")
    if recurrence.count is not None:
        parts.append(f"COUNT={recurrence.count}")
    elif recurrence.until is not None:
        end = aware_datetime(
            __import__("datetime").datetime.combine(
                recurrence.until,
                __import__("datetime").time(23, 59, 59),
            ),
            timezone_name,
        ).astimezone(timezone.utc)
        parts.append(end.strftime("UNTIL=%Y%m%dT%H%M%SZ"))
    return "RRULE:" + ";".join(parts)


def _google_meet_supported(source) -> bool:
    metadata = source_metadata(source)
    allowed = metadata.get("allowed_conference_solution_types")
    if not isinstance(allowed, list):
        return True
    return "hangoutsMeet" in {str(item) for item in allowed}


def _conference() -> dict[str, Any]:
    return {
        "createRequest": {
            "requestId": f"jace-{uuid4().hex}",
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _base_create(
    data: CalendarCreateEventInput,
    timezone_name: str,
    *,
    meet_supported: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": data.title.strip(),
        "description": data.description,
        "location": data.location,
        "transparency": "transparent" if data.availability == "free" else "opaque",
        "visibility": data.visibility,
    }

    if data.all_day:
        payload["start"] = {"date": data.start_date.isoformat()}
        payload["end"] = {"date": data.end_date_exclusive.isoformat()}
    else:
        payload["start"] = _timed(data.start_at, timezone_name)
        payload["end"] = _timed(data.end_at, timezone_name)

    if data.attendees:
        payload["attendees"] = _attendees(data.attendees)
        payload["guestsCanModify"] = False
    if data.reminders is not None:
        payload["reminders"] = _reminders(data.reminders)
    if data.recurrence is not None:
        payload["recurrence"] = [_rrule(data.recurrence, timezone_name)]
    if data.online_meeting is not None:
        if data.online_meeting != "google_meet":
            raise ToolError(
                "Google Calendar can only create google_meet online meetings."
            )
        if not meet_supported:
            raise ToolError(
                "This Google calendar does not advertise Google Meet support."
            )
        payload["conferenceData"] = _conference()

    return payload


def _base_update(
    data: CalendarModifyEventInput,
    timezone_name: str,
    *,
    meet_supported: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    fields = data.model_fields_set

    if "title" in fields:
        payload["summary"] = data.title.strip() if data.title else ""
    if "description" in fields:
        payload["description"] = data.description or ""
    if "location" in fields:
        payload["location"] = data.location or ""
    if "availability" in fields:
        payload["transparency"] = (
            "transparent" if data.availability == "free" else "opaque"
        )
    if "visibility" in fields:
        payload["visibility"] = data.visibility or "default"

    if data.start_date is not None and data.end_date_exclusive is not None:
        payload["start"] = {"date": data.start_date.isoformat()}
        payload["end"] = {"date": data.end_date_exclusive.isoformat()}
    elif data.start_at is not None and data.end_at is not None:
        payload["start"] = _timed(data.start_at, timezone_name)
        payload["end"] = _timed(data.end_at, timezone_name)
    elif "all_day" in fields:
        raise ToolError(
            "Changing timed/all-day requires the new complete start/end values."
        )

    if "attendees" in fields and data.attendees is not None:
        payload["attendees"] = _attendees(data.attendees)
    if "reminders" in fields and data.reminders is not None:
        payload["reminders"] = _reminders(data.reminders)
    if "recurrence" in fields:
        payload["recurrence"] = (
            [_rrule(data.recurrence, timezone_name)]
            if data.recurrence is not None
            else []
        )
    if "online_meeting" in fields and data.online_meeting is not None:
        if data.online_meeting != "google_meet":
            raise ToolError(
                "Google Calendar can only create google_meet online meetings."
            )
        if not meet_supported:
            raise ToolError(
                "This Google calendar does not advertise Google Meet support."
            )
        payload["conferenceData"] = _conference()

    return payload


def _write_params(
    *,
    has_attendees: bool,
    notify_attendees: bool,
    has_conference: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if has_attendees:
        params["sendUpdates"] = "all" if notify_attendees else "none"
    if has_conference:
        params["conferenceDataVersion"] = 1
    return params


async def _refresh_series_cache(
    context: ToolContext,
    source,
    access_token: str,
    event,
) -> str | None:
    try:
        async with context.session.begin_nested():
            await _sync_source_events(
                context.session,
                source=source,
                access_token=access_token,
            )
        return None
    except Exception as exc:
        warning = (
            "Provider write succeeded, but Jace could not immediately refresh "
            f"the recurring-series cache: {exc}"
        )
        await mark_series_pending(context, event, warning)
        return warning


async def google_calendar_create_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CalendarCreateEventInput)

    source, account = await resolve_create_source(
        context,
        provider_id="google",
        capability_id="calendar.create",
        calendar=payload.calendar,
    )
    timezone_name = await effective_timezone(context, payload.timezone)
    access_token, _ = await _google_access_token(context)

    provider_payload = _base_create(
        payload,
        timezone_name,
        meet_supported=_google_meet_supported(source),
    )
    result = await _request(
        access_token,
        "POST",
        f"/calendars/{quote(source.external_calendar_id or '', safe='')}/events",
        payload=provider_payload,
        params=_write_params(
            has_attendees=bool(payload.attendees),
            notify_attendees=payload.notify_attendees,
            has_conference=payload.online_meeting == "google_meet",
        ),
    )
    normalized = _normalize_google_event(
        result,
        source_timezone=source.timezone,
    )
    if normalized is None:
        raise ToolError(
            "Google created the event but Jace could not normalize it. Refresh Calendar."
        )
    row = await upsert_provider_event(context.session, source, normalized)
    warning = None
    if payload.recurrence is not None:
        warning = await _refresh_series_cache(
            context,
            source,
            access_token,
            row,
        )
    await context.session.flush()

    response = {
        "status": "created",
        "account": account,
        "event": local_event_summary(row),
        "invitation": {
            "attendee_count": len(payload.attendees),
            "notifications": (
                "all" if payload.attendees and payload.notify_attendees
                else "suppressed" if payload.attendees
                else "none"
            ),
        },
        "warning": warning,
    }
    return ToolExecutionResult(
        content=json.dumps(response, ensure_ascii=False),
        display=(
            f'Created Google Calendar event "{row.title}" on '
            f"{source.name} ({account})."
        ),
        metadata={
            "provider": "google",
            "calendar": source.name,
            "event_id": row.id,
            "attendee_count": len(payload.attendees),
            "recurring": payload.recurrence is not None,
            "online_meeting": payload.online_meeting,
            "sensitive": True,
        },
    )


async def google_calendar_modify_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CalendarModifyEventInput)

    row, account = await resolve_modify_event(
        context,
        provider_id="google",
        capability_id="calendar.modify",
        event_id=payload.event_id,
    )
    source = row.source
    access_token, _ = await _google_access_token(context)
    provider_event_id = target_external_event_id(
        row,
        payload.recurrence_scope,
    )
    path = (
        f"/calendars/{quote(source.external_calendar_id or '', safe='')}"
        f"/events/{quote(provider_event_id, safe='')}"
    )

    attendee_count = (
        len(payload.attendees)
        if payload.attendees is not None
        else existing_attendee_count(row)
    )
    has_attendees = attendee_count > 0

    if payload.action == "delete":
        await _request(
            access_token,
            "DELETE",
            path,
            params=_write_params(
                has_attendees=has_attendees,
                notify_attendees=payload.notify_attendees,
                has_conference=False,
            ),
        )
        if payload.recurrence_scope == "series":
            await mark_series_deleted(context, row)
        else:
            row.deleted_at = utc_now()
            row.sync_state = "synced"
            row.sync_error = None
        await context.session.flush()

        return ToolExecutionResult(
            content=json.dumps(
                {
                    "status": "deleted",
                    "account": account,
                    "event_id": row.id,
                    "title": row.title,
                    "scope": payload.recurrence_scope,
                    "attendee_notifications": (
                        "all" if has_attendees and payload.notify_attendees
                        else "suppressed" if has_attendees
                        else "none"
                    ),
                },
                ensure_ascii=False,
            ),
            display=(
                f'Deleted Google Calendar '
                f'{"series" if payload.recurrence_scope == "series" else "event"} '
                f'"{row.title}" from {source.name} ({account}).'
            ),
            metadata={
                "provider": "google",
                "event_id": row.id,
                "scope": payload.recurrence_scope,
                "sensitive": True,
            },
        )

    timezone_name = await effective_timezone(
        context,
        payload.timezone or row.timezone,
    )
    provider_payload = _base_update(
        payload,
        timezone_name,
        meet_supported=_google_meet_supported(source),
    )
    result = await _request(
        access_token,
        "PATCH",
        path,
        payload=provider_payload,
        params=_write_params(
            has_attendees=has_attendees,
            notify_attendees=payload.notify_attendees,
            has_conference=payload.online_meeting == "google_meet",
        ),
    )
    normalized = _normalize_google_event(
        result,
        source_timezone=source.timezone,
    )
    if normalized is None:
        raise ToolError(
            "Google updated the event but Jace could not normalize it. Refresh Calendar."
        )
    updated = await upsert_provider_event(context.session, source, normalized)
    warning = None
    if payload.recurrence_scope == "series":
        warning = await _refresh_series_cache(
            context,
            source,
            access_token,
            updated,
        )
    await context.session.flush()

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "updated",
                "account": account,
                "event": local_event_summary(updated),
                "scope": payload.recurrence_scope,
                "attendee_notifications": (
                    "all" if has_attendees and payload.notify_attendees
                    else "suppressed" if has_attendees
                    else "none"
                ),
                "warning": warning,
            },
            ensure_ascii=False,
        ),
        display=(
            f'Updated Google Calendar '
            f'{"series" if payload.recurrence_scope == "series" else "event"} '
            f'"{updated.title}" on {source.name} ({account}).'
        ),
        metadata={
            "provider": "google",
            "event_id": updated.id,
            "scope": payload.recurrence_scope,
            "attendee_count": attendee_count,
            "online_meeting": payload.online_meeting,
            "sensitive": True,
        },
    )


def register_google_calendar_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="google_calendar_create_event",
            label="Create Google Calendar event",
            description=(
                "Create a Google Calendar event. Supports attendees/invitations, "
                "recurrence, reminders and Google Meet. External write: Ask."
            ),
            category="Calendar",
            risk="write",
            default_permission="ask",
            input_model=CalendarCreateEventInput,
            handler=google_calendar_create_event_tool,
            provider_id="google",
            capability_id="calendar.create",
        ),
        ToolDefinition(
            name="google_calendar_modify_event",
            label="Modify Google Calendar event",
            description=(
                "Update/reschedule/delete a Google Calendar occurrence or series. "
                "Can change attendees, reminders, recurrence and add Google Meet. "
                "External write: Ask."
            ),
            category="Calendar",
            risk="write",
            default_permission="ask",
            input_model=CalendarModifyEventInput,
            handler=google_calendar_modify_event_tool,
            provider_id="google",
            capability_id="calendar.modify",
        ),
    ]
    for definition in definitions:
        registry.register(definition, replace=True)
