from __future__ import annotations

# JACE_STEP4C5A_GOOGLE_CALENDAR_WRITE

import json
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from jace.calendar.google_sync import (
    GOOGLE_CALENDAR_API,
    HTTP_TIMEOUT_SECONDS,
    _normalize_google_event,
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
    CalendarCreateEventInput,
    CalendarModifyEventInput,
    effective_timezone,
    local_event_summary,
    resolve_create_source,
    resolve_modify_event,
)
from jace.tools.gmail import _google_access_token
from jace.tools.registry import registry


def _error(
    response: httpx.Response,
    fallback: str,
) -> ToolError:
    detail = ""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw = payload.get("error")

        if isinstance(raw, dict):
            message = raw.get("message")
            if isinstance(message, str):
                detail = message.strip()
        elif isinstance(raw, str):
            detail = raw.strip()

    detail = detail[:500]

    if response.status_code == 401:
        return ToolError(
            "Google rejected the current token. Reconnect this Google "
            "account in Settings > Connections."
        )

    if response.status_code == 403:
        return ToolError(
            "Google denied Calendar write access. Reconnect the Google "
            "account and confirm Jace has calendar.events permission."
        )

    if response.status_code == 404:
        return ToolError(
            detail
            or "Google Calendar could not find that calendar/event."
        )

    return ToolError(
        detail
        or fallback
    )


async def _request(
    access_token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization":
            f"Bearer {access_token}",
        "Accept":
            "application/json",
        "User-Agent":
            "Jace-Desktop",
    }

    if payload is not None:
        headers[
            "Content-Type"
        ] = "application/json"

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
    ) as client:
        response = await client.request(
            method,
            f"{GOOGLE_CALENDAR_API}{path}",
            headers=headers,
            json=payload,
        )

    expected = (
        {200, 201}
        if method != "DELETE"
        else {204}
    )

    if response.status_code not in expected:
        raise _error(
            response,
            "Google Calendar write request failed.",
        )

    if not response.content:
        return {}

    try:
        result = response.json()
    except ValueError as exc:
        raise ToolError(
            "Google Calendar returned an unreadable write response."
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise ToolError(
            "Google Calendar returned an unexpected write response."
        )

    return result


def _timed(
    value,
    timezone_name: str,
) -> dict[str, str]:
    if value.tzinfo is None:
        from zoneinfo import ZoneInfo
        value = value.replace(
            tzinfo=ZoneInfo(
                timezone_name
            )
        )

    return {
        "dateTime":
            value.isoformat(),
        "timeZone":
            timezone_name,
    }


def _create_payload(
    data: CalendarCreateEventInput,
    timezone_name: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary":
            data.title.strip(),
        "description":
            data.description,
        "location":
            data.location,
        "transparency":
            "transparent"
            if data.availability == "free"
            else "opaque",
        "visibility":
            data.visibility,
    }

    if data.all_day:
        payload[
            "start"
        ] = {
            "date":
                data.start_date.isoformat()
        }
        payload[
            "end"
        ] = {
            "date":
                data.end_date_exclusive.isoformat()
        }
    else:
        payload[
            "start"
        ] = _timed(
            data.start_at,
            timezone_name,
        )
        payload[
            "end"
        ] = _timed(
            data.end_at,
            timezone_name,
        )

    return payload


def _update_payload(
    data: CalendarModifyEventInput,
    timezone_name: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    if "title" in data.model_fields_set:
        payload["summary"] = (
            data.title.strip()
            if data.title
            else ""
        )

    if "description" in data.model_fields_set:
        payload["description"] = (
            data.description
            or ""
        )

    if "location" in data.model_fields_set:
        payload["location"] = (
            data.location
            or ""
        )

    if "availability" in data.model_fields_set:
        payload["transparency"] = (
            "transparent"
            if data.availability == "free"
            else "opaque"
        )

    if "visibility" in data.model_fields_set:
        payload["visibility"] = (
            data.visibility
            or "default"
        )

    target_all_day = (
        data.all_day
        if "all_day" in data.model_fields_set
        else None
    )

    if (
        data.start_date is not None
        and data.end_date_exclusive is not None
    ):
        payload["start"] = {
            "date":
                data.start_date.isoformat()
        }
        payload["end"] = {
            "date":
                data.end_date_exclusive.isoformat()
        }
    elif (
        data.start_at is not None
        and data.end_at is not None
    ):
        payload["start"] = _timed(
            data.start_at,
            timezone_name,
        )
        payload["end"] = _timed(
            data.end_at,
            timezone_name,
        )
    elif target_all_day is not None:
        raise ToolError(
            "Changing an event between timed/all-day requires the new "
            "start/end values in the same request."
        )

    return payload


async def google_calendar_create_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarCreateEventInput,
    )

    source, account = await resolve_create_source(
        context,
        provider_id="google",
        capability_id="calendar.create",
        calendar=payload.calendar,
    )
    timezone_name = await effective_timezone(
        context,
        payload.timezone,
    )
    access_token, _ = await _google_access_token(
        context
    )

    calendar_id = quote(
        source.external_calendar_id or "",
        safe="",
    )

    result = await _request(
        access_token,
        "POST",
        f"/calendars/{calendar_id}/events",
        payload=_create_payload(
            payload,
            timezone_name,
        ),
    )

    normalized = _normalize_google_event(
        result,
        source_timezone=source.timezone,
    )

    if normalized is None:
        raise ToolError(
            "Google created the event but Jace could not normalize the "
            "returned event. Refresh the Calendar workspace."
        )

    row = await upsert_provider_event(
        context.session,
        source,
        normalized,
    )
    await context.session.flush()

    response = {
        "status":
            "created",
        "account":
            account,
        "event":
            local_event_summary(
                row
            ),
    }

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=(
            f'Created Google Calendar event "{row.title}" '
            f'on {source.name} ({account}).'
        ),
        metadata={
            "provider":
                "google",
            "calendar":
                source.name,
            "event_id":
                row.id,
            "external_event_id":
                row.external_event_id,
            "sensitive":
                True,
        },
    )


async def google_calendar_modify_event_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        CalendarModifyEventInput,
    )

    row, account = await resolve_modify_event(
        context,
        provider_id="google",
        capability_id="calendar.modify",
        event_id=payload.event_id,
    )
    source = row.source
    access_token, _ = await _google_access_token(
        context
    )
    calendar_id = quote(
        source.external_calendar_id or "",
        safe="",
    )
    event_id = quote(
        row.external_event_id or "",
        safe="",
    )

    if payload.action == "delete":
        await _request(
            access_token,
            "DELETE",
            (
                f"/calendars/{calendar_id}"
                f"/events/{event_id}"
            ),
        )
        row.deleted_at = utc_now()
        row.sync_state = "synced"
        row.sync_error = None
        await context.session.flush()

        response = {
            "status":
                "deleted",
            "account":
                account,
            "event_id":
                row.id,
            "title":
                row.title,
            "calendar":
                source.name,
        }

        return ToolExecutionResult(
            content=json.dumps(
                response,
                ensure_ascii=False,
            ),
            display=(
                f'Deleted Google Calendar event "{row.title}" '
                f'from {source.name} ({account}).'
            ),
            metadata={
                "provider":
                    "google",
                "calendar":
                    source.name,
                "event_id":
                    row.id,
                "sensitive":
                    True,
            },
        )

    timezone_name = await effective_timezone(
        context,
        payload.timezone
        or row.timezone,
    )
    result = await _request(
        access_token,
        "PATCH",
        (
            f"/calendars/{calendar_id}"
            f"/events/{event_id}"
        ),
        payload=_update_payload(
            payload,
            timezone_name,
        ),
    )

    normalized = _normalize_google_event(
        result,
        source_timezone=source.timezone,
    )

    if normalized is None:
        raise ToolError(
            "Google updated the event but Jace could not normalize the "
            "returned event. Refresh the Calendar workspace."
        )

    updated = await upsert_provider_event(
        context.session,
        source,
        normalized,
    )
    await context.session.flush()

    response = {
        "status":
            "updated",
        "account":
            account,
        "event":
            local_event_summary(
                updated
            ),
    }

    return ToolExecutionResult(
        content=json.dumps(
            response,
            ensure_ascii=False,
        ),
        display=(
            f'Updated Google Calendar event "{updated.title}" '
            f'on {source.name} ({account}).'
        ),
        metadata={
            "provider":
                "google",
            "calendar":
                source.name,
            "event_id":
                updated.id,
            "sensitive":
                True,
        },
    )


def register_google_calendar_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="google_calendar_create_event",
            label="Create Google Calendar event",
            description=(
                "Create a single Google Calendar event on the resolved account. "
                "Supports timed or all-day events, title, description, location, "
                "availability and visibility. This writes external calendar data "
                "and requires approval."
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
                "Update/reschedule or delete an existing Google Calendar event "
                "using the local event ID returned by Calendar Intelligence. "
                "This writes external calendar data and requires approval."
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
        registry.register(
            definition,
            replace=True,
        )
