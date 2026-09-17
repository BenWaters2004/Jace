from __future__ import annotations

# JACE_STEP4C5A_MICROSOFT_CALENDAR_WRITE

import json
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from jace.calendar.microsoft_sync import (
    GRAPH_API,
    HTTP_TIMEOUT_SECONDS,
    _normalize_event,
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
    utc_datetime,
)
from jace.tools.outlook import _microsoft_access_token
from jace.tools.registry import registry


def _error(
    response: httpx.Response,
    fallback: str,
) -> ToolError:
    detail = ""
    code = ""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw = payload.get("error")

        if isinstance(raw, dict):
            raw_code = raw.get("code")
            raw_message = raw.get("message")

            if isinstance(raw_code, str):
                code = raw_code.strip()

            if isinstance(raw_message, str):
                detail = raw_message.strip()

    detail = detail[:500]

    if response.status_code == 401:
        return ToolError(
            "Microsoft rejected the current token. Reconnect this Microsoft "
            "account in Settings > Connections."
        )

    if response.status_code == 403:
        return ToolError(
            "Microsoft denied Calendar write access. Add delegated "
            "Calendars.ReadWrite to the Jace Entra application, then reconnect "
            "the Microsoft account."
        )

    if response.status_code == 404:
        return ToolError(
            detail
            or "Microsoft Calendar could not find that calendar/event."
        )

    if code:
        return ToolError(
            f"{detail or fallback} ({code})"
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
            f"{GRAPH_API}{path}",
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
            "Microsoft Graph Calendar write request failed.",
        )

    if not response.content:
        return {}

    try:
        result = response.json()
    except ValueError as exc:
        raise ToolError(
            "Microsoft Graph returned an unreadable Calendar write response."
        ) from exc

    if not isinstance(
        result,
        dict,
    ):
        raise ToolError(
            "Microsoft Graph returned an unexpected Calendar write response."
        )

    return result


def _graph_time(
    value,
    timezone_name: str,
) -> dict[str, str]:
    utc = utc_datetime(
        value,
        timezone_name,
    )

    return {
        "dateTime":
            utc.replace(
                tzinfo=None
            ).isoformat(
                timespec="seconds"
            ),
        "timeZone":
            "UTC",
    }


def _graph_all_day(
    value,
) -> dict[str, str]:
    return {
        "dateTime":
            f"{value.isoformat()}T00:00:00",
        "timeZone":
            "UTC",
    }


def _create_payload(
    data: CalendarCreateEventInput,
    timezone_name: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject":
            data.title.strip(),
        "body": {
            "contentType":
                "Text",
            "content":
                data.description,
        },
        "location": {
            "displayName":
                data.location,
        },
        "showAs":
            "free"
            if data.availability == "free"
            else "busy",
        "sensitivity": {
            "default":
                "normal",
            "public":
                "normal",
            "private":
                "private",
            "confidential":
                "confidential",
        }[
            data.visibility
        ],
        "isAllDay":
            data.all_day,
    }

    if data.all_day:
        payload[
            "start"
        ] = _graph_all_day(
            data.start_date
        )
        payload[
            "end"
        ] = _graph_all_day(
            data.end_date_exclusive
        )
    else:
        payload[
            "start"
        ] = _graph_time(
            data.start_at,
            timezone_name,
        )
        payload[
            "end"
        ] = _graph_time(
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
        payload[
            "subject"
        ] = (
            data.title.strip()
            if data.title
            else ""
        )

    if "description" in data.model_fields_set:
        payload[
            "body"
        ] = {
            "contentType":
                "Text",
            "content":
                data.description
                or "",
        }

    if "location" in data.model_fields_set:
        payload[
            "location"
        ] = {
            "displayName":
                data.location
                or "",
        }

    if "availability" in data.model_fields_set:
        payload[
            "showAs"
        ] = (
            "free"
            if data.availability == "free"
            else "busy"
        )

    if "visibility" in data.model_fields_set:
        payload[
            "sensitivity"
        ] = {
            "default":
                "normal",
            "public":
                "normal",
            "private":
                "private",
            "confidential":
                "confidential",
        }[
            data.visibility
            or "default"
        ]

    if "all_day" in data.model_fields_set:
        payload[
            "isAllDay"
        ] = bool(
            data.all_day
        )

    if (
        data.start_date is not None
        and data.end_date_exclusive is not None
    ):
        payload[
            "start"
        ] = _graph_all_day(
            data.start_date
        )
        payload[
            "end"
        ] = _graph_all_day(
            data.end_date_exclusive
        )
        payload[
            "isAllDay"
        ] = True
    elif (
        data.start_at is not None
        and data.end_at is not None
    ):
        payload[
            "start"
        ] = _graph_time(
            data.start_at,
            timezone_name,
        )
        payload[
            "end"
        ] = _graph_time(
            data.end_at,
            timezone_name,
        )

        if (
            "all_day"
            in data.model_fields_set
            and data.all_day is False
        ):
            payload[
                "isAllDay"
            ] = False
    elif "all_day" in data.model_fields_set:
        raise ToolError(
            "Changing an event between timed/all-day requires the new "
            "start/end values in the same request."
        )

    return payload


async def microsoft_calendar_create_event_tool(
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
        provider_id="microsoft",
        capability_id="calendar.create",
        calendar=payload.calendar,
    )
    timezone_name = await effective_timezone(
        context,
        payload.timezone,
    )
    access_token, _ = await _microsoft_access_token(
        context
    )
    calendar_id = quote(
        source.external_calendar_id or "",
        safe="",
    )

    result = await _request(
        access_token,
        "POST",
        f"/me/calendars/{calendar_id}/events",
        payload=_create_payload(
            payload,
            timezone_name,
        ),
    )

    normalized = _normalize_event(
        result
    )

    if normalized is None:
        raise ToolError(
            "Microsoft created the event but Jace could not normalize the "
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
            f'Created Outlook Calendar event "{row.title}" '
            f'on {source.name} ({account}).'
        ),
        metadata={
            "provider":
                "microsoft",
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


async def microsoft_calendar_modify_event_tool(
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
        provider_id="microsoft",
        capability_id="calendar.modify",
        event_id=payload.event_id,
    )
    source = row.source
    access_token, _ = await _microsoft_access_token(
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
                f"/me/calendars/{calendar_id}"
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
                f'Deleted Outlook Calendar event "{row.title}" '
                f'from {source.name} ({account}).'
            ),
            metadata={
                "provider":
                    "microsoft",
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
            f"/me/calendars/{calendar_id}"
            f"/events/{event_id}"
        ),
        payload=_update_payload(
            payload,
            timezone_name,
        ),
    )

    normalized = _normalize_event(
        result
    )

    if normalized is None:
        raise ToolError(
            "Microsoft updated the event but Jace could not normalize the "
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
            f'Updated Outlook Calendar event "{updated.title}" '
            f'on {source.name} ({account}).'
        ),
        metadata={
            "provider":
                "microsoft",
            "calendar":
                source.name,
            "event_id":
                updated.id,
            "sensitive":
                True,
        },
    )


def register_microsoft_calendar_write_tools() -> None:
    definitions = [
        ToolDefinition(
            name="microsoft_calendar_create_event",
            label="Create Outlook Calendar event",
            description=(
                "Create a single Outlook/Microsoft Calendar event on the "
                "resolved account. Supports timed or all-day events, title, "
                "description, location, availability and visibility. This "
                "writes external calendar data and requires approval."
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
                "Update/reschedule or delete an existing Outlook/Microsoft "
                "Calendar event using the local event ID returned by Calendar "
                "Intelligence. This writes external calendar data and requires "
                "approval."
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
        registry.register(
            definition,
            replace=True,
        )
