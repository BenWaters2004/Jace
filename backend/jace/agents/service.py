from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.agents.definitions import AgentDefinition, get_agent_definition
from jace.agents.models import AgentTask, AgentTaskEvent
from jace.db.models import utc_now
from jace.config import settings
from jace.agents.recovery_policy import has_recorded_action_activity, metadata_is_quarantined


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"running", "thinking", "using_tool", "waiting_permission"}
RECOVERABLE_STATUSES = {"queued", *ACTIVE_STATUSES}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def task_allowed_tools(task: AgentTask) -> list[str]:
    return _json_list(task.allowed_tools_json)


def task_used_tools(task: AgentTask) -> list[str]:
    return _json_list(task.used_tools_json)


def task_metadata(task: AgentTask) -> dict[str, Any]:
    return _json_object(task.metadata_json)


def event_data(event: AgentTaskEvent) -> dict[str, Any]:
    return _json_object(event.data_json)


async def append_event(
    session: AsyncSession,
    task: AgentTask,
    *,
    event_type: str,
    message: str,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> AgentTaskEvent:
    event = AgentTaskEvent(
        task_id=task.id,
        event_type=event_type,
        message=message[:1000],
        data_json=json.dumps(data or {}, ensure_ascii=False),
    )
    session.add(event)
    task.updated_at = utc_now()
    if commit:
        await session.commit()
        await session.refresh(event)
    else:
        await session.flush()
    return event


async def get_task(session: AsyncSession, task_id: str) -> AgentTask | None:
    return await session.get(AgentTask, task_id)


async def list_tasks(
    session: AsyncSession,
    *,
    status: str | None = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    limit: int = 100,
) -> list[AgentTask]:
    query = select(AgentTask)

    if status:
        query = query.where(AgentTask.status == status)
    if agent_id:
        query = query.where(AgentTask.agent_id == agent_id)
    if conversation_id:
        query = query.where(AgentTask.conversation_id == conversation_id)

    result = await session.execute(
        query.order_by(AgentTask.created_at.desc()).limit(max(1, min(limit, 500)))
    )
    return list(result.scalars().all())


async def list_events(
    session: AsyncSession,
    task_id: str,
    *,
    limit: int = 200,
) -> list[AgentTaskEvent]:
    result = await session.execute(
        select(AgentTaskEvent)
        .where(AgentTaskEvent.task_id == task_id)
        .order_by(AgentTaskEvent.created_at.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(result.scalars().all())


def _validate_tools(
    definition: AgentDefinition,
    requested: list[str] | None,
) -> list[str]:
    selected = list(definition.default_tools) if requested is None else list(requested)

    unknown = sorted(set(selected) - definition.all_tools)
    if unknown:
        raise ValueError(
            f"{definition.name} cannot be given these tools: {', '.join(unknown)}"
        )

    # Stable order, no duplicates.
    return list(dict.fromkeys(selected))


async def create_task(
    session: AsyncSession,
    *,
    agent_id: str,
    title: str,
    instruction: str,
    conversation_id: str | None = None,
    parent_task_id: str | None = None,
    priority: int = 0,
    model: str | None = None,
    reasoning_mode: str = "balanced",
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentTask:
    definition = get_agent_definition(agent_id)
    if definition is None:
        raise ValueError(f"Unknown agent type: {agent_id}")

    if parent_task_id:
        parent = await session.get(AgentTask, parent_task_id)
        if parent is None:
            raise ValueError("Parent agent task was not found.")

    selected_tools = _validate_tools(definition, allowed_tools)

    task = AgentTask(
        conversation_id=conversation_id,
        parent_task_id=parent_task_id,
        agent_id=definition.id,
        title=title.strip(),
        instruction=instruction.strip(),
        status="queued",
        priority=priority,
        model=model.strip() if model else None,
        reasoning_mode=reasoning_mode,
        allowed_tools_json=json.dumps(selected_tools, ensure_ascii=False),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        progress=0.0,
        progress_message="Queued",
    )
    session.add(task)
    await session.flush()

    await append_event(
        session,
        task,
        event_type="queued",
        message=f"{definition.name} task queued.",
        data={"agent_id": definition.id, "allowed_tools": selected_tools},
        commit=False,
    )

    await session.commit()
    await session.refresh(task)
    return task


async def update_task_state(
    session: AsyncSession,
    task: AgentTask,
    *,
    status: str,
    progress: float | None = None,
    progress_message: str | None = None,
    result: str | None = None,
    error: str | None = None,
    used_tools: list[str] | None = None,
    started: bool = False,
    completed: bool = False,
    event_type: str | None = None,
    event_message: str | None = None,
    event_data_value: dict[str, Any] | None = None,
) -> AgentTask:
    now = utc_now()

    task.status = status
    task.updated_at = now

    if progress is not None:
        task.progress = max(0.0, min(1.0, float(progress)))
    if progress_message is not None:
        task.progress_message = progress_message[:500]
    if result is not None:
        task.result = result
    if error is not None:
        task.error = error[:20_000]
    if used_tools is not None:
        task.used_tools_json = json.dumps(
            sorted(set(used_tools)), ensure_ascii=False
        )
    if started and task.started_at is None:
        task.started_at = now
    if completed:
        task.completed_at = now

    if event_type and event_message:
        await append_event(
            session,
            task,
            event_type=event_type,
            message=event_message,
            data=event_data_value,
            commit=False,
        )

    await session.commit()
    await session.refresh(task)
    return task


async def request_cancel(session: AsyncSession, task: AgentTask) -> AgentTask:
    if task.status in TERMINAL_STATUSES:
        return task

    task.cancel_requested = True

    if task.status == "queued":
        await update_task_state(
            session,
            task,
            status="cancelled",
            progress_message="Cancelled",
            completed=True,
            event_type="cancelled",
            event_message="Task cancelled before it started.",
        )
        return task

    await append_event(
        session,
        task,
        event_type="cancel_requested",
        message="Cancellation requested.",
        commit=False,
    )
    task.updated_at = utc_now()
    await session.commit()
    await session.refresh(task)
    return task


async def prepare_retry(session: AsyncSession, task: AgentTask) -> AgentTask:
    if task.status not in {"failed", "cancelled"}:
        raise ValueError("Only failed or cancelled agent tasks can be retried.")
    # C4C.3C: retry is not an acknowledgement that side effects are safe to duplicate.
    if metadata_is_quarantined(task):
        raise ValueError("Recovery-quarantined task cannot be retried. Inspect audit and start a new, explicitly authorised task.")

    task.status = "queued"
    task.progress = 0.0
    task.progress_message = "Queued for retry"
    task.result = None
    task.error = None
    task.cancel_requested = False
    task.started_at = None
    task.completed_at = None
    task.used_tools_json = "[]"
    metadata = task_metadata(task)
    metadata.pop("worker_crash_recoveries", None)
    metadata.pop("last_worker_crash", None)
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.updated_at = utc_now()

    await append_event(
        session,
        task,
        event_type="retried",
        message="Task queued for retry.",
        commit=False,
    )
    await session.commit()
    await session.refresh(task)
    return task



async def _hold_ambiguous_recovery(
    session: AsyncSession, task: AgentTask, *, reason: str,
) -> AgentTask:
    """Persist an actionable failed state, never redispatch an uncertain action."""
    metadata = task_metadata(task)
    metadata['recovery_quarantined'] = True
    metadata['recovery_quarantine_reason'] = reason  # A fixed enum, not raw command text.
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    return await update_task_state(
        session, task, status='failed', progress_message='Recovery requires manual review',
        error='RECOVERY REQUIRES MANUAL REVIEW: previous tool or approval activity may have side effects; no automatic replay.',
        completed=True, event_type='recovery_quarantined',
        event_message='Task was not replayed because recorded tool activity may have side effects.',
        event_data_value={'reason': reason},
    )


async def recover_task_after_worker_crash(
    session: AsyncSession,
    task: AgentTask,
    *,
    worker_id: str,
    error: str,
    max_recoveries: int = 1,
) -> AgentTask:
    """Recover one task whose executor coroutine exited unexpectedly.

    A worker crash is different from an ordinary specialist/tool failure: the
    task did not finish cleanly, so Jace gives it one automatic redispatch. The
    recovery count is persisted in task metadata so a task that repeatedly
    crashes executors cannot loop forever.
    """
    if task.status in TERMINAL_STATUSES:
        return task
    if task.cancel_requested:
        return await update_task_state(
            session,
            task,
            status="cancelled",
            progress_message="Cancelled",
            completed=True,
            event_type="cancelled",
            event_message=(
                f"{worker_id} exited after cancellation had already been requested."
            ),
            event_data_value={"worker_id": worker_id, "executor_exit": True},
        )

    # C4C.3C: persisted intent and audit evidence fences uncertain work.
    if settings.agent_safe_recovery_enabled and await has_recorded_action_activity(session, task):
        return await _hold_ambiguous_recovery(session, task, reason="worker_exit")

    metadata = task_metadata(task)
    raw_recoveries = metadata.get("worker_crash_recoveries", 0)
    try:
        recoveries = max(0, int(raw_recoveries))
    except (TypeError, ValueError):
        recoveries = 0

    previous_status = task.status
    if recoveries >= max_recoveries:
        metadata["worker_crash_recoveries"] = recoveries
        metadata["last_worker_crash"] = {
            "worker_id": worker_id,
            "error": error[:2000],
        }
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        return await update_task_state(
            session,
            task,
            status="failed",
            progress_message="Executor repeatedly crashed",
            error=(
                f"{worker_id} exited unexpectedly more than once while running "
                f"this task. Last executor error: {error}"
            ),
            completed=True,
            event_type="worker_crash_failed",
            event_message=(
                f"{worker_id} repeatedly exited unexpectedly; Jace stopped "
                "automatic recovery for this task."
            ),
            event_data_value={
                "worker_id": worker_id,
                "previous_status": previous_status,
                "error": error[:2000],
                "recovery_count": recoveries,
            },
        )

    recoveries += 1
    metadata["worker_crash_recoveries"] = recoveries
    metadata["last_worker_crash"] = {
        "worker_id": worker_id,
        "error": error[:2000],
    }
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.status = "queued"
    task.progress_message = f"Recovered after {worker_id} restarted"
    task.started_at = None
    task.completed_at = None
    task.cancel_requested = False
    task.error = None
    task.updated_at = utc_now()
    await append_event(
        session,
        task,
        event_type="worker_recovered",
        message=(
            f"Recovered task after {worker_id} exited unexpectedly. "
            "The task was returned to the dispatcher."
        ),
        data={
            "worker_id": worker_id,
            "previous_status": previous_status,
            "error": error[:2000],
            "recovery_count": recoveries,
        },
        commit=False,
    )
    await session.commit()
    await session.refresh(task)
    return task

async def recover_incomplete_tasks(session: AsyncSession) -> list[AgentTask]:
    result = await session.execute(
        select(AgentTask)
        .where(AgentTask.status.in_(RECOVERABLE_STATUSES))
        .order_by(AgentTask.priority.desc(), AgentTask.created_at.asc())
    )
    tasks = list(result.scalars().all())

    for task in tasks:
        if task.cancel_requested:
            task.status = "cancelled"
            task.progress_message = "Cancelled during restart recovery"
            task.completed_at = utc_now()
            await append_event(
                session,
                task,
                event_type="cancelled",
                message="Task was cancelled while Jace was offline.",
                commit=False,
            )
            continue

        # C4C.3C: do not replay tools just because the worker lost its lease.
        if settings.agent_safe_recovery_enabled and await has_recorded_action_activity(session, task):
            await _hold_ambiguous_recovery(session, task, reason="core_restart")
            continue

        if task.status != "queued":
            previous = task.status
            task.status = "queued"
            task.progress_message = "Recovered after Jace restart"
            task.started_at = None
            await append_event(
                session,
                task,
                event_type="recovered",
                message=f"Recovered task from {previous} state after restart.",
                data={"previous_status": previous},
                commit=False,
            )

    await session.commit()
    return [task for task in tasks if task.status == "queued"]


async def status_counts(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(AgentTask.status, func.count(AgentTask.id)).group_by(AgentTask.status)
    )
    return {str(status): int(count) for status, count in result.all()}
