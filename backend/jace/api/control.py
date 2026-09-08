from __future__ import annotations

import json
import platform

from fastapi import APIRouter, HTTPException, Query

from jace.config import settings
from jace.control.service import (
    ControlError,
    active_session,
    authorize_sensitive_once,
    create_policy,
    delete_policy,
    emergency_stop_all,
    get_policy,
    get_session,
    list_action_audit,
    list_policies,
    list_sessions,
    list_windows_with_policy,
    start_session,
    stop_session,
    update_policy,
)
from jace.database import SessionLocal
from jace.schemas import (
    ControlActionListResponse,
    ControlActionResponse,
    ControlAppPolicyCreate,
    ControlAppPolicyListResponse,
    ControlAppPolicyResponse,
    ControlAppPolicyUpdate,
    ControlSessionCreate,
    ControlSessionListResponse,
    ControlSessionResponse,
    ControlStatusResponse,
    ControlWindowListResponse,
    ControlWindowResponse,
)


router = APIRouter(prefix="/control", tags=["control"])


def policy_response(row) -> ControlAppPolicyResponse:
    return ControlAppPolicyResponse(
        id=row.id,
        label=row.label,
        process_pattern=row.process_pattern,
        title_pattern=row.title_pattern,
        observe_enabled=row.observe_enabled,
        interact_enabled=row.interact_enabled,
        sensitive_enabled=row.sensitive_enabled,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def session_response(row) -> ControlSessionResponse:
    return ControlSessionResponse(
        id=row.id,
        conversation_id=row.conversation_id,
        status=row.status,
        step_count=row.step_count,
        max_steps=row.max_steps,
        remaining_steps=max(0, row.max_steps - row.step_count),
        store_screenshots=row.store_screenshots,
        sensitive_authorized_once=row.sensitive_authorized_once,
        started_at=row.started_at,
        updated_at=row.updated_at,
        ended_at=row.ended_at,
        stop_reason=row.stop_reason,
    )


def action_response(row) -> ControlActionResponse:
    try:
        arguments = json.loads(row.arguments_json or "{}")
        if not isinstance(arguments, dict):
            arguments = {}
    except json.JSONDecodeError:
        arguments = {}
    return ControlActionResponse(
        id=row.id,
        session_id=row.session_id,
        conversation_id=row.conversation_id,
        action_type=row.action_type,
        window_handle=row.window_handle,
        process_name=row.process_name,
        window_title=row.window_title,
        arguments=arguments,
        status=row.status,
        result_preview=row.result_preview,
        screenshot_attachment_id=row.screenshot_attachment_id,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


@router.get("/status", response_model=ControlStatusResponse)
async def control_status():
    async with SessionLocal() as session:
        policies = await list_policies(session)
        active = await active_session(session)
        visible_count = 0
        if platform.system() == "Windows" and settings.interactive_control_enabled:
            try:
                visible_count = len(await list_windows_with_policy(session))
            except Exception:
                visible_count = 0
        return ControlStatusResponse(
            enabled=settings.interactive_control_enabled,
            platform_supported=platform.system() == "Windows",
            active_session=session_response(active) if active else None,
            policy_count=len(policies),
            active_policy_count=sum(1 for item in policies if item.is_active),
            visible_window_count=visible_count,
            physical_failsafe="Move the mouse to the top-left corner (0,0) to block the next Jace GUI action.",
        )


@router.get("/windows", response_model=ControlWindowListResponse)
async def control_windows():
    if not settings.interactive_control_enabled:
        raise HTTPException(status_code=409, detail="Interactive control is disabled.")
    if platform.system() != "Windows":
        raise HTTPException(status_code=409, detail="Interactive control is currently supported on Windows only.")
    async with SessionLocal() as session:
        try:
            rows = await list_windows_with_policy(session)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ControlWindowListResponse(windows=[ControlWindowResponse(**row) for row in rows])


@router.get("/policies", response_model=ControlAppPolicyListResponse)
async def control_policies():
    async with SessionLocal() as session:
        rows = await list_policies(session)
    return ControlAppPolicyListResponse(policies=[policy_response(row) for row in rows])


@router.post("/policies", response_model=ControlAppPolicyResponse)
async def post_control_policy(request: ControlAppPolicyCreate):
    async with SessionLocal() as session:
        try:
            row = await create_policy(session, **request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return policy_response(row)


@router.patch("/policies/{policy_id}", response_model=ControlAppPolicyResponse)
async def patch_control_policy(policy_id: str, request: ControlAppPolicyUpdate):
    async with SessionLocal() as session:
        row = await get_policy(session, policy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Control app policy not found.")
        try:
            row = await update_policy(session, row, **request.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return policy_response(row)


@router.delete("/policies/{policy_id}")
async def remove_control_policy(policy_id: str):
    async with SessionLocal() as session:
        row = await get_policy(session, policy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Control app policy not found.")
        await delete_policy(session, row)
    return {"success": True}


@router.get("/sessions", response_model=ControlSessionListResponse)
async def control_sessions(limit: int = Query(default=50, ge=1, le=200)):
    async with SessionLocal() as session:
        rows = await list_sessions(session, limit=limit)
    return ControlSessionListResponse(sessions=[session_response(row) for row in rows])


@router.post("/sessions", response_model=ControlSessionResponse)
async def post_control_session(request: ControlSessionCreate):
    async with SessionLocal() as session:
        try:
            row = await start_session(session, **request.model_dump())
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session_response(row)


@router.post("/sessions/{session_id}/stop", response_model=ControlSessionResponse)
async def post_stop_control_session(session_id: str):
    async with SessionLocal() as session:
        try:
            row = await stop_session(session, session_id)
        except ControlError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session_response(row)


@router.post("/sessions/{session_id}/authorize-sensitive", response_model=ControlSessionResponse)
async def authorize_sensitive(session_id: str):
    async with SessionLocal() as session:
        try:
            row = await authorize_sensitive_once(session, session_id)
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session_response(row)


@router.post("/emergency-stop")
async def emergency_stop():
    async with SessionLocal() as session:
        count = await emergency_stop_all(session)
    return {"success": True, "stopped_sessions": count}


@router.get("/actions", response_model=ControlActionListResponse)
async def control_actions(
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    async with SessionLocal() as session:
        rows = await list_action_audit(session, session_id=session_id, limit=limit)
    return ControlActionListResponse(actions=[action_response(row) for row in rows])
