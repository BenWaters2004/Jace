from __future__ import annotations

# JACE_STEP4C5B_MICROSOFT_SCHEDULING_WRITE

import json
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from jace.calendar.microsoft_sync import (
    GRAPH_API,
    HTTP_TIMEOUT_SECONDS,
    _normalize_event,
    _sync_calendar_events,
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
from jace.tools.outlook import _microsoft_access_token
from jace.tools.registry import registry


def _error(response: httpx.Response, fallback: str) -> ToolError:
    detail = ""
    code = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw = payload.get("error")
        if isinstance(raw, dict):
            if isinstance(raw.get("code"), str):
                code = raw["code"].strip()
            if isinstance(raw.get("message"), str):
                detail = raw["message"].strip()

    if response.status_code == 401:
        return ToolError(
            "Microsoft rejected the current token. Reconnect Microsoft in "
            "Settings > Connections."
        )
    if response.status_code == 403:
        return ToolError(
            "Microsoft denied Calendar write access. Confirm delegated "
            "Calendars.ReadWrite is granted."
        )
    if response.status_code == 404:
        return ToolError(
            detail or "Microsoft Calendar could not find that calendar/event."
        )
    if code:
        return ToolError(f"{detail or fallback} ({code})")
    return ToolError(detail[:500] or fallback)


async def _request(
    access_token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
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
            f"{GRAPH_API}{path}",
            headers=headers,
            json=payload,
        )

    expected = {204} if method == "DELETE" else {200, 201}
    if response.status_code not in expected:
        raise _error(
            response,
            "Microsoft Graph Calendar write request failed.",
        )
    if not response.content:
        return {}
    try:
        value = response.json()
    except ValueError as exc:
        raise ToolError(
            "Microsoft Graph returned an unreadable Calendar write response."
        ) from exc
    if not isinstance(value, dict):
        raise ToolError(
            "Microsoft Graph returned an unexpected Calendar write response."
        )
    return value


def _graph_time(value, timezone_name: str) -> dict[str, str]:
    local = aware_datetime(value, timezone_name)
    return {
        "dateTime": local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "timeZone": timezone_name,
    }


def _graph_all_day(value, timezone_name: str) -> dict[str, str]:
    return {
        "dateTime": f"{value.isoformat()}T00:00:00",
        "timeZone": timezone_name,
    }


def _attendees(
    attendees: list[CalendarAttendeeInput],
) -> list[dict[str, Any]]:
    return [
        {
            "emailAddress": {
                "address": attendee.email,
                **(
                    {"name": attendee.name}
                    if attendee.name
                    else {}
                ),
            },
            "type": attendee.type,
        }
        for attendee in attendees
    ]


def _reminder_payload(
    reminders: list[CalendarReminderInput],
) -> dict[str, Any]:
    if not reminders:
        return {
            "isReminderOn": False,
        }

    if len(reminders) > 1:
        raise ToolError(
            "Microsoft Calendar supports one event reminder offset. "
            "Use one popup reminder."
        )

    reminder = reminders[0]
    if reminder.method != "popup":
        raise ToolError(
            "Microsoft Calendar event reminders do not support Jace's email "
            "reminder mode. Use popup."
        )

    return {
        "isReminderOn": True,
        "reminderMinutesBeforeStart": reminder.minutes_before_start,
    }


_DAY = {
    "monday": "monday",
    "tuesday": "tuesday",
    "wednesday": "wednesday",
    "thursday": "thursday",
    "friday": "friday",
    "saturday": "saturday",
    "sunday": "sunday",
}


def _recurrence_payload(
    recurrence: CalendarRecurrenceInput,
    timezone_name: str,
    first_date,
) -> dict[str, Any]:
    pattern: dict[str, Any] = {
        "interval": recurrence.interval,
    }

    if recurrence.frequency == "daily":
        pattern["type"] = "daily"
    elif recurrence.frequency == "weekly":
        pattern["type"] = "weekly"
        pattern["daysOfWeek"] = (
            [_DAY[item] for item in recurrence.weekdays]
            if recurrence.weekdays
            else [_DAY[first_date.strftime("%A").casefold()]]
        )
        pattern["firstDayOfWeek"] = "monday"
    elif recurrence.frequency == "monthly":
        pattern["type"] = "absoluteMonthly"
        pattern["dayOfMonth"] = recurrence.day_of_month or first_date.day
    else:
        pattern["type"] = "absoluteYearly"
        pattern["dayOfMonth"] = recurrence.day_of_month or first_date.day
        pattern["month"] = recurrence.month or first_date.month

    recurrence_range: dict[str, Any] = {
        "startDate": first_date.isoformat(),
        "recurrenceTimeZone": timezone_name,
    }
    if recurrence.count is not None:
        recurrence_range.update(
            {
                "type": "numbered",
                "numberOfOccurrences": recurrence.count,
            }
        )
    elif recurrence.until is not None:
        recurrence_range.update(
            {
                "type": "endDate",
                "endDate": recurrence.until.isoformat(),
            }
        )
    else:
        recurrence_range["type"] = "noEnd"

    return {
        "pattern": pattern,
        "range": recurrence_range,
    }


def _teams_supported(source) -> bool:
    metadata = source_metadata(source)
    allowed = metadata.get("allowed_online_meeting_providers")
    if not isinstance(allowed, list) or not allowed:
        return True
    return "teamsForBusiness" in {str(item) for item in allowed}


def _online_meeting_payload(
    data,
    source,
) -> dict[str, Any]:
    if data.online_meeting is None:
        return {}
    if data.online_meeting != "microsoft_teams":
        raise ToolError(
            "Microsoft Calendar can only create microsoft_teams online meetings."
        )
    if not _teams_supported(source):
        raise ToolError(
            "This Microsoft calendar does not advertise Teams as an allowed "
            "online meeting provider."
        )
    return {
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
    }


def _validate_notifications(
    *,
    attendee_count: int,
    notify_attendees: bool,
) -> None:
    if attendee_count > 0 and not notify_attendees:
        raise ToolError(
            "Microsoft Graph does not provide a reliable silent organizer write "
            "for an event with attendees. Leave notify_attendees=true or remove "
            "the attendees from this requested write."
        )


def _base_create(
    data: CalendarCreateEventInput,
    timezone_name: str,
    source,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject": data.title.strip(),
        "body": {
            "contentType": "Text",
            "content": data.description,
        },
        "location": {
            "displayName": data.location,
        },
        "showAs": "free" if data.availability == "free" else "busy",
        "sensitivity": {
            "default": "normal",
            "public": "normal",
            "private": "private",
            "confidential": "confidential",
        }[data.visibility],
        "isAllDay": data.all_day,
        "allowNewTimeProposals": data.allow_new_time_proposals,
    }

    if data.all_day:
        payload["start"] = _graph_all_day(data.start_date, timezone_name)
        payload["end"] = _graph_all_day(
            data.end_date_exclusive,
            timezone_name,
        )
    else:
        payload["start"] = _graph_time(data.start_at, timezone_name)
        payload["end"] = _graph_time(data.end_at, timezone_name)

    if data.attendees:
        payload["attendees"] = _attendees(data.attendees)
    if data.reminders is not None:
        payload.update(_reminder_payload(data.reminders))
    if data.recurrence is not None:
        payload["recurrence"] = _recurrence_payload(
            data.recurrence,
            timezone_name,
            first_occurrence_date(data, timezone_name),
        )
    payload.update(_online_meeting_payload(data, source))
    return payload


def _base_update(
    data: CalendarModifyEventInput,
    timezone_name: str,
    source,
    event,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    fields = data.model_fields_set

    if "title" in fields:
        payload["subject"] = data.title.strip() if data.title else ""
    if "description" in fields:
        payload["body"] = {
            "contentType": "Text",
            "content": data.description or "",
        }
    if "location" in fields:
        payload["location"] = {"displayName": data.location or ""}
    if "availability" in fields:
        payload["showAs"] = "free" if data.availability == "free" else "busy"
    if "visibility" in fields:
        payload["sensitivity"] = {
            "default": "normal",
            "public": "normal",
            "private": "private",
            "confidential": "confidential",
        }[data.visibility or "default"]
    if "allow_new_time_proposals" in fields:
        payload["allowNewTimeProposals"] = bool(
            data.allow_new_time_proposals
        )

    if data.start_date is not None and data.end_date_exclusive is not None:
        payload["start"] = _graph_all_day(data.start_date, timezone_name)
        payload["end"] = _graph_all_day(
            data.end_date_exclusive,
            timezone_name,
        )
        payload["isAllDay"] = True
    elif data.start_at is not None and data.end_at is not None:
        payload["start"] = _graph_time(data.start_at, timezone_name)
        payload["end"] = _graph_time(data.end_at, timezone_name)
        if "all_day" in fields:
            payload["isAllDay"] = bool(data.all_day)
    elif "all_day" in fields:
        raise ToolError(
            "Changing timed/all-day requires the new complete start/end values."
        )

    if "attendees" in fields and data.attendees is not None:
        payload["attendees"] = _attendees(data.attendees)
    if "reminders" in fields and data.reminders is not None:
        payload.update(_reminder_payload(data.reminders))
    if "recurrence" in fields:
        payload["recurrence"] = (
            _recurrence_payload(
                data.recurrence,
                timezone_name,
                first_occurrence_date(
                    data,
                    timezone_name,
                    fallback_event=event,
                ),
            )
            if data.recurrence is not None
            else None
        )
    payload.update(_online_meeting_payload(data, source))
    return payload


async def _refresh_series_cache(
    context: ToolContext,
    source,
    access_token: str,
    event,
) -> str | None:
    try:
        async with context.session.begin_nested():
            await _sync_calendar_events(
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


async def microsoft_calendar_create_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CalendarCreateEventInput)

    source, account = await resolve_create_source(
        context,
        provider_id="microsoft",
        capability_id="calendar.create",
        calendar=payload.calendar,
    )
    _validate_notifications(
        attendee_count=len(payload.attendees),
        notify_attendees=payload.notify_attendees,
    )
    timezone_name = await effective_timezone(context, payload.timezone)
    access_token, _ = await _microsoft_access_token(context)

    result = await _request(
        access_token,
        "POST",
        f"/me/calendars/{quote(source.external_calendar_id or '', safe='')}/events",
        payload=_base_create(
            payload,
            timezone_name,
            source,
        ),
    )
    normalized = _normalize_event(result)
    if normalized is None:
        raise ToolError(
            "Microsoft created the event but Jace could not normalize it. "
            "Refresh Calendar."
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

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "created",
                "account": account,
                "event": local_event_summary(row),
                "invitation": {
                    "attendee_count": len(payload.attendees),
                    "notifications": (
                        "provider_managed" if payload.attendees else "none"
                    ),
                },
                "warning": warning,
            },
            ensure_ascii=False,
        ),
        display=(
            f'Created Outlook Calendar event "{row.title}" on '
            f"{source.name} ({account})."
        ),
        metadata={
            "provider": "microsoft",
            "calendar": source.name,
            "event_id": row.id,
            "attendee_count": len(payload.attendees),
            "recurring": payload.recurrence is not None,
            "online_meeting": payload.online_meeting,
            "sensitive": True,
        },
    )


async def microsoft_calendar_modify_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CalendarModifyEventInput)

    row, account = await resolve_modify_event(
        context,
        provider_id="microsoft",
        capability_id="calendar.modify",
        event_id=payload.event_id,
    )
    source = row.source
    attendee_count = (
        len(payload.attendees)
        if payload.attendees is not None
        else existing_attendee_count(row)
    )
    _validate_notifications(
        attendee_count=attendee_count,
        notify_attendees=payload.notify_attendees,
    )

    access_token, _ = await _microsoft_access_token(context)
    provider_event_id = target_external_event_id(
        row,
        payload.recurrence_scope,
    )
    path = (
        f"/me/calendars/{quote(source.external_calendar_id or '', safe='')}"
        f"/events/{quote(provider_event_id, safe='')}"
    )

    if payload.action == "delete":
        await _request(access_token, "DELETE", path)
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
                        "provider_managed" if attendee_count else "none"
                    ),
                },
                ensure_ascii=False,
            ),
            display=(
                f'Deleted Outlook Calendar '
                f'{"series" if payload.recurrence_scope == "series" else "event"} '
                f'"{row.title}" from {source.name} ({account}).'
            ),
            metadata={
                "provider": "microsoft",
                "event_id": row.id,
                "scope": payload.recurrence_scope,
                "sensitive": True,
            },
        )

    timezone_name = await effective_timezone(
        context,
        payload.timezone or row.timezone,
    )
    result = await _request(
        access_token,
        "PATCH",
        path,
        payload=_base_update(
            payload,
            timezone_name,
            source,
            row,
        ),
    )
    normalized = _normalize_event(result)
    if normalized is None:
        raise ToolError(
            "Microsoft updated the event but Jace could not normalize it. "
            "Refresh Calendar."
        )
    updated = await upsert_provider_event(
        context.session,
        source,
        normalized,
    )
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
                    "provider_managed" if attendee_count else "none"
                ),
                "warning": warning,
            },
            ensure_ascii=False,
        ),
        display=(
            f'Updated Outlook Calendar '
            f'{"series" if payload.recurrence_scope == "series" else "event"} '
            f'"{updated.title}" on {source.name} ({account}).'
        ),
        metadata={
            "provider": "microsoft",
            "event_id": updated.id,
            "scope": payload.recurrence_scope,
            "attendee_count": attendee_count,
            "online_meeting": payload.online_meeting,
            "sensitive": True,
        },
    )


def register_microsoft_calendar_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="microsoft_calendar_create_event",
            label="Create Outlook Calendar event",
            description=(
                "Create an Outlook/Microsoft Calendar event. Supports attendees, "
                "recurrence, one reminder and Teams where supported. Microsoft "
                "may send invitations/updates automatically. External write: Ask."
            ),
            category="Calendar",
            risk="write",
            default_permission="ask",
            input_model=CalendarCreateEventInput,
            handler=microsoft_calendar_create_event_tool,
            provider_id="microsoft",
            capability_id="calendar.create",
        ),
        ToolDefinition(
            name="microsoft_calendar_modify_event",
            label="Modify Outlook Calendar event",
            description=(
                "Update/reschedule/delete an Outlook occurrence or series. Can "
                "change attendees, recurrence, reminder and add Teams. Changes "
                "to meetings may notify attendees. External write: Ask."
            ),
            category="Calendar",
            risk="write",
            default_permission="ask",
            input_model=CalendarModifyEventInput,
            handler=microsoft_calendar_modify_event_tool,
            provider_id="microsoft",
            capability_id="calendar.modify",
        ),
    ]
    for definition in definitions:
        registry.register(definition, replace=True)
