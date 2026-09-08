from fastapi import APIRouter, HTTPException, Query

from jace.automations.parser import parse_automation_draft
from jace.automations.scheduler import (
    reschedule_automation,
    run_automation_now,
    scheduler_running,
    unschedule_automation,
)
from jace.automations.service import (
    allowed_tool_names,
    automation_counts,
    create_automation,
    delete_automation,
    get_automation,
    list_automations,
    list_notifications,
    list_runs,
    mark_all_notifications_read,
    mark_notification_read,
    run_tool_names,
    schedule_from_row,
    update_automation,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.schemas import (
    AutomationCreate,
    AutomationDraftRequest,
    AutomationDraftResponse,
    AutomationListResponse,
    AutomationNotificationListResponse,
    AutomationNotificationResponse,
    AutomationResponse,
    AutomationRunListResponse,
    AutomationRunResponse,
    AutomationStatusResponse,
    AutomationUpdate,
)


router = APIRouter(prefix="/automations", tags=["automations"])


def automation_response(row) -> AutomationResponse:
    return AutomationResponse(
        id=row.id,
        name=row.name,
        instruction=row.instruction,
        automation_type=row.automation_type,
        schedule=schedule_from_row(row),
        watcher_condition=row.watcher_condition,
        allowed_tools=allowed_tool_names(row),
        enabled=row.enabled,
        notify_on_success=row.notify_on_success,
        notify_on_failure=row.notify_on_failure,
        notify_on_condition=row.notify_on_condition,
        timeout_seconds=row.timeout_seconds,
        model=row.model,
        reasoning_mode=row.reasoning_mode,
        created_at=row.created_at,
        updated_at=row.updated_at,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_status=row.last_status,
        last_result=row.last_result,
    )


def run_response(row) -> AutomationRunResponse:
    return AutomationRunResponse(
        id=row.id,
        automation_id=row.automation_id,
        trigger_type=row.trigger_type,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        result=row.result,
        error=row.error,
        condition_met=row.condition_met,
        tool_names=run_tool_names(row),
        model=row.model,
    )


def notification_response(row) -> AutomationNotificationResponse:
    return AutomationNotificationResponse(
        id=row.id,
        automation_id=row.automation_id,
        run_id=row.run_id,
        title=row.title,
        body=row.body,
        level=row.level,
        created_at=row.created_at,
        read_at=row.read_at,
    )


@router.get("/status", response_model=AutomationStatusResponse)
async def automation_status():
    async with SessionLocal() as session:
        counts = await automation_counts(session)
    return AutomationStatusResponse(
        enabled=settings.automation_enabled,
        scheduler_running=scheduler_running(),
        timezone=settings.automation_scheduler_timezone,
        **counts,
    )


@router.get("", response_model=AutomationListResponse)
async def get_automations():
    async with SessionLocal() as session:
        rows = await list_automations(session)
    return AutomationListResponse(
        enabled=settings.automation_enabled,
        automations=[automation_response(row) for row in rows],
    )


@router.post("", response_model=AutomationResponse)
async def post_automation(request: AutomationCreate):
    async with SessionLocal() as session:
        try:
            row = await create_automation(
                session,
                name=request.name,
                instruction=request.instruction,
                automation_type=request.automation_type,
                schedule=request.schedule,
                watcher_condition=request.watcher_condition,
                allowed_tools=request.allowed_tools,
                enabled=request.enabled,
                notify_on_success=request.notify_on_success,
                notify_on_failure=request.notify_on_failure,
                notify_on_condition=request.notify_on_condition,
                timeout_seconds=request.timeout_seconds,
                model=request.model,
                reasoning_mode=request.reasoning_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await reschedule_automation(row.id)
    async with SessionLocal() as session:
        refreshed = await get_automation(session, row.id)
    return automation_response(refreshed or row)


@router.get("/{automation_id}", response_model=AutomationResponse)
async def get_single_automation(automation_id: str):
    async with SessionLocal() as session:
        row = await get_automation(session, automation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return automation_response(row)


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def patch_automation(automation_id: str, request: AutomationUpdate):
    async with SessionLocal() as session:
        row = await get_automation(session, automation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        try:
            row = await update_automation(
                session,
                row,
                name=request.name,
                instruction=request.instruction,
                automation_type=request.automation_type,
                schedule=request.schedule,
                watcher_condition=request.watcher_condition,
                watcher_condition_provided="watcher_condition" in request.model_fields_set,
                allowed_tools=request.allowed_tools,
                enabled=request.enabled,
                notify_on_success=request.notify_on_success,
                notify_on_failure=request.notify_on_failure,
                notify_on_condition=request.notify_on_condition,
                timeout_seconds=request.timeout_seconds,
                model=request.model,
                model_provided="model" in request.model_fields_set,
                reasoning_mode=request.reasoning_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await reschedule_automation(automation_id)
    async with SessionLocal() as session:
        refreshed = await get_automation(session, automation_id)
    return automation_response(refreshed or row)


@router.delete("/{automation_id}")
async def remove_automation(automation_id: str):
    async with SessionLocal() as session:
        row = await get_automation(session, automation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        await delete_automation(session, row)
    await unschedule_automation(automation_id)
    return {"success": True}


@router.post("/{automation_id}/run")
async def run_now(automation_id: str):
    async with SessionLocal() as session:
        row = await get_automation(session, automation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if not settings.automation_enabled:
        raise HTTPException(status_code=409, detail="Automation is disabled by backend configuration.")
    await run_automation_now(automation_id)
    return {"accepted": True, "automation_id": automation_id}


@router.get("/{automation_id}/runs", response_model=AutomationRunListResponse)
async def automation_runs(
    automation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    async with SessionLocal() as session:
        row = await get_automation(session, automation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        runs = await list_runs(session, automation_id, limit=limit)
    return AutomationRunListResponse(runs=[run_response(item) for item in runs])


@router.post("/draft", response_model=AutomationDraftResponse)
async def draft_automation(request: AutomationDraftRequest):
    try:
        return await parse_automation_draft(request.instruction, request.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/notifications/list", response_model=AutomationNotificationListResponse)
async def notifications(
    unread_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
):
    async with SessionLocal() as session:
        rows = await list_notifications(session, unread_only=unread_only, limit=limit)
    return AutomationNotificationListResponse(
        notifications=[notification_response(row) for row in rows]
    )


@router.post("/notifications/{notification_id}/read", response_model=AutomationNotificationResponse)
async def read_notification(notification_id: str):
    async with SessionLocal() as session:
        row = await mark_notification_read(session, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return notification_response(row)


@router.post("/notifications/read-all")
async def read_all_notifications():
    async with SessionLocal() as session:
        count = await mark_all_notifications_read(session)
    return {"success": True, "updated": count}
