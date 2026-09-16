from __future__ import annotations

import asyncio

# JACE_STEP4C4A_UNIFIED_CALENDAR_API

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from jace.calendar.schemas import (
    CalendarEventCreate,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdate,
    CalendarSourceListResponse,
    CalendarSourceResponse,
    CalendarSourceUpdate,
    CalendarStatusResponse,
)
from jace.calendar.service import (
    DEFAULT_TIMEZONE,
    calendar_counts,
    create_jace_event,
    delete_jace_event,
    ensure_default_jace_calendar,
    event_payload,
    get_calendar_event,
    get_calendar_source,
    list_calendar_events,
    list_calendar_sources,
    source_payload,
    update_calendar_source,
    update_jace_event,
)
from jace.calendar.google_sync import sync_google_calendars
from jace.database import SessionLocal
from jace.runtime import runtime_events

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/status", response_model=CalendarStatusResponse)
async def calendar_status():
    async with SessionLocal() as session:
        default_source = await ensure_default_jace_calendar(session)
        counts = await calendar_counts(session)
        await session.commit()
    return CalendarStatusResponse(
        default_calendar_id=default_source.id,
        timezone=default_source.timezone,
        **counts,
    )


@router.get("/sources", response_model=CalendarSourceListResponse)
async def calendar_sources():
    async with SessionLocal() as session:
        await ensure_default_jace_calendar(session)
        rows = await list_calendar_sources(session)
        await session.commit()
    return CalendarSourceListResponse(
        sources=[CalendarSourceResponse(**source_payload(row)) for row in rows]
    )


@router.patch("/sources/{source_id}", response_model=CalendarSourceResponse)
async def patch_calendar_source(source_id: str, request: CalendarSourceUpdate):
    async with SessionLocal() as session:
        row = await get_calendar_source(session, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar source not found.")
        try:
            row = await update_calendar_source(session, row, request)
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = CalendarSourceResponse(**source_payload(row))

    await runtime_events.publish(
        "calendar.changed",
        action="source_updated",
        source_id=source_id,
    )
    return response


@router.get("/events", response_model=CalendarEventListResponse)
async def calendar_events(
    start: datetime = Query(..., description="Inclusive range start."),
    end: datetime = Query(..., description="Exclusive range end."),
    timezone: str = Query(default=DEFAULT_TIMEZONE, min_length=1, max_length=100),
    source_id: list[str] | None = Query(default=None),
):
    async with SessionLocal() as session:
        try:
            rows = await list_calendar_events(
                session,
                start=start,
                end=end,
                timezone_name=timezone,
                source_ids=source_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CalendarEventListResponse(
        start=start,
        end=end,
        timezone=timezone,
        events=[CalendarEventResponse(**event_payload(row)) for row in rows],
    )


@router.post("/events", response_model=CalendarEventResponse)
async def create_calendar_event(request: CalendarEventCreate):
    async with SessionLocal() as session:
        try:
            row = await create_jace_event(session, request)
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = CalendarEventResponse(**event_payload(row))

    await runtime_events.publish(
        "calendar.changed",
        action="event_created",
        event_id=response.id,
        source_id=response.source_id,
    )
    return response



# JACE_STEP4C4C_GOOGLE_CALENDAR_SYNC_API
# JACE_STEP4C4C_SYNC_TRANSACTION_LOCK
_CALENDAR_SYNC_TRANSACTION_LOCK = asyncio.Lock()


@router.post("/sync")
async def sync_calendars():
    """Serialize provider sync through database commit."""
    async with _CALENDAR_SYNC_TRANSACTION_LOCK:
        async with SessionLocal() as session:
            try:
                google = await sync_google_calendars(session)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=502,
                    detail="Calendar synchronization failed: " + str(exc),
                ) from exc

    payload = google.as_dict()

    await runtime_events.publish(
        "calendar.changed",
        action="provider_sync",
        provider_id="google",
        calendars_synced=payload["calendars_synced"],
        events_changed=payload["events_changed"],
        events_deleted=payload["events_deleted"],
    )

    return {
        "status": payload["status"],
        "needs_reconnect": payload["needs_reconnect"],
        "calendars_synced": payload["calendars_synced"],
        "events_changed": payload["events_changed"],
        "events_deleted": payload["events_deleted"],
        "duplicate_connections_ignored": payload["duplicate_connections_ignored"],
        "duplicate_sources_removed": payload["duplicate_sources_removed"],
        "duplicate_events_removed": payload["duplicate_events_removed"],
        "errors": payload["errors"],
        "providers": [payload],
    }

@router.get("/events/{event_id}", response_model=CalendarEventResponse)
async def calendar_event(event_id: str):
    async with SessionLocal() as session:
        row = await get_calendar_event(session, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar event not found.")
        return CalendarEventResponse(**event_payload(row))


@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
async def patch_calendar_event(event_id: str, request: CalendarEventUpdate):
    async with SessionLocal() as session:
        row = await get_calendar_event(session, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar event not found.")
        try:
            row = await update_jace_event(session, row, request)
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response = CalendarEventResponse(**event_payload(row))

    await runtime_events.publish(
        "calendar.changed",
        action="event_updated",
        event_id=response.id,
        source_id=response.source_id,
    )
    return response


@router.delete("/events/{event_id}")
async def remove_calendar_event(event_id: str):
    async with SessionLocal() as session:
        row = await get_calendar_event(session, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Calendar event not found.")
        source_id = row.source_id
        try:
            await delete_jace_event(session, row)
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    await runtime_events.publish(
        "calendar.changed",
        action="event_deleted",
        event_id=event_id,
        source_id=source_id,
    )
    return {"success": True, "event_id": event_id}
