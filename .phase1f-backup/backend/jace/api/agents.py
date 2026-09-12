from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from jace.agents.config import agent_settings
from jace.agents.definitions import (
    get_agent_definition,
    list_agent_definitions,
)
from jace.agents.manager import agent_manager
from jace.agents.readiness import (
    build_agent_readiness_snapshot,
    get_agent_readiness,
)
from jace.agents.schemas import (
    AgentDefinitionListResponse,
    AgentDefinitionResponse,
    AgentStatusResponse,
    AgentTaskCreate,
    AgentTaskEventResponse,
    AgentTaskEventsResponse,
    AgentTaskListResponse,
    AgentTaskResponse,
    AgentWorkerListResponse,
    AgentWorkerResponse,
)
from jace.agents.service import (
    create_task,
    event_data,
    get_task,
    list_events,
    list_tasks,
    prepare_retry,
    status_counts,
    task_allowed_tools,
    task_metadata,
    task_used_tools,
)
from jace.database import SessionLocal

router = APIRouter(prefix="/agents", tags=["agents"])


def _task_response(row) -> AgentTaskResponse:
    definition = get_agent_definition(row.agent_id)
    return AgentTaskResponse(
        id=row.id,
        conversation_id=row.conversation_id,
        parent_task_id=row.parent_task_id,
        agent_id=row.agent_id,
        agent_name=definition.name if definition else row.agent_id,
        agent_role=definition.role if definition else "Unknown",
        accent=definition.accent if definition else "#55dff5",
        glyph=definition.glyph if definition else "?",
        title=row.title,
        instruction=row.instruction,
        status=row.status,
        priority=row.priority,
        executor_id=agent_manager.executor_for_task(row.id),
        queue_position=agent_manager.queue_position(row.id),
        progress=row.progress,
        progress_message=row.progress_message,
        model=row.model,
        reasoning_mode=row.reasoning_mode,
        allowed_tools=task_allowed_tools(row),
        used_tools=task_used_tools(row),
        metadata=task_metadata(row),
        result=row.result,
        error=row.error,
        cancel_requested=row.cancel_requested,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status():
    async with SessionLocal() as session:
        counts = await status_counts(session)

    return AgentStatusResponse(
        enabled=agent_settings.enabled,
        manager_running=agent_manager.running,
        workers=agent_manager.worker_count,
        active_tasks=agent_manager.active_count,
        queued_tasks=agent_manager.queued_count,
        counts=counts,
    )


@router.get("/workers", response_model=AgentWorkerListResponse)
async def agent_workers():
    """Expose the real executor slots used by the asyncio background-agent pool."""
    return AgentWorkerListResponse(
        workers=[
            AgentWorkerResponse(**snapshot)
            for snapshot in agent_manager.worker_snapshots()
        ]
    )


@router.get("/readiness")
async def agent_readiness():
    # Phase 1E: authoritative specialist readiness.
    return await build_agent_readiness_snapshot(
        manager_running=agent_manager.running,
    )

@router.get("", response_model=AgentDefinitionListResponse)
async def agent_definitions():
    return AgentDefinitionListResponse(
        agents=[
            AgentDefinitionResponse(
                id=definition.id,
                name=definition.name,
                role=definition.role,
                description=definition.description,
                default_tools=list(definition.default_tools),
                optional_tools=list(definition.optional_tools),
                accent=definition.accent,
                glyph=definition.glyph,
            )
            for definition in list_agent_definitions()
        ]
    )


@router.get("/tasks", response_model=AgentTaskListResponse)
async def get_agent_tasks(
    status: str | None = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    async with SessionLocal() as session:
        rows = await list_tasks(
            session,
            status=status,
            agent_id=agent_id,
            conversation_id=conversation_id,
            limit=limit,
        )
    return AgentTaskListResponse(tasks=[_task_response(row) for row in rows])


@router.post("/tasks", response_model=AgentTaskResponse)
async def post_agent_task(request: AgentTaskCreate):
    if not agent_settings.enabled:
        raise HTTPException(status_code=503, detail="Background agents are disabled.")
    if not agent_manager.running:
        raise HTTPException(
            status_code=503,
            detail="Agent manager is not currently accepting tasks.",
        )
    # Phase 1E: do not queue a specialist that cannot actually operate.
    try:
        readiness = await get_agent_readiness(
            request.agent_id,
            manager_running=agent_manager.running,
            model_override=request.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if readiness["status"] == "unavailable":
        raise HTTPException(
            status_code=409,
            detail=f'{readiness["agent_name"]} is unavailable: {readiness["summary"]}',
        )

    async with SessionLocal() as session:
        try:
            row = await create_task(
                session,
                agent_id=request.agent_id,
                title=request.title,
                instruction=request.instruction,
                conversation_id=request.conversation_id,
                parent_task_id=request.parent_task_id,
                priority=request.priority,
                model=request.model,
                reasoning_mode=request.reasoning_mode,
                allowed_tools=request.allowed_tools,
                metadata=request.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    queued = await agent_manager.enqueue(row.id, priority=row.priority)
    if not queued:
        raise HTTPException(
            status_code=503,
            detail="Agent manager is not currently accepting tasks.",
        )

    return _task_response(row)


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
async def get_single_agent_task(task_id: str):
    async with SessionLocal() as session:
        row = await get_task(session, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")

    return _task_response(row)


@router.get("/tasks/{task_id}/events", response_model=AgentTaskEventsResponse)
async def get_agent_task_events(
    task_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
):
    async with SessionLocal() as session:
        task = await get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Agent task not found.")

        rows = await list_events(session, task_id, limit=limit)
    return AgentTaskEventsResponse(
        events=[
            AgentTaskEventResponse(
                id=row.id,
                task_id=row.task_id,
                event_type=row.event_type,
                message=row.message,
                data=event_data(row),
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@router.post("/tasks/{task_id}/cancel", response_model=AgentTaskResponse)
async def cancel_agent_task(task_id: str):
    async with SessionLocal() as session:
        row = await get_task(session, task_id)

    if row is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")

    await agent_manager.cancel(task_id)

    async with SessionLocal() as session:
        refreshed = await get_task(session, task_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Agent task not found.")

    return _task_response(refreshed)


@router.post("/tasks/{task_id}/retry", response_model=AgentTaskResponse)
async def retry_agent_task(task_id: str):
    if not agent_settings.enabled:
        raise HTTPException(status_code=503, detail="Background agents are disabled.")
    if not agent_manager.running:
        raise HTTPException(
            status_code=503,
            detail="Agent manager is not currently accepting tasks.",
        )

    async with SessionLocal() as session:
        row = await get_task(session, task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Agent task not found.")

        readiness = await get_agent_readiness(
            row.agent_id,
            manager_running=agent_manager.running,
            model_override=row.model,
        )
        if readiness["status"] == "unavailable":
            raise HTTPException(
                status_code=409,
                detail=f'{readiness["agent_name"]} is unavailable: {readiness["summary"]}',
            )

        try:
            row = await prepare_retry(session, row)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    queued = await agent_manager.enqueue_when_released(
        row.id,
        priority=row.priority,
        timeout_seconds=2.0,
    )
    if not queued:
        raise HTTPException(
            status_code=503,
            detail=(
                "The task was prepared for retry but its previous executor "
                "did not release in time. It will be recovered if the agent "
                "manager restarts."
            ),
        )

    return _task_response(row)
