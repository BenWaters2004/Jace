from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from jace.agents.definitions import get_agent_definition
from jace.agents.director import launch_director_workflow
from jace.agents.manager import agent_manager
from jace.agents.service import (
    create_task,
    get_task,
    list_tasks,
    task_allowed_tools,
    task_used_tools,
)
from jace.tools.base import ToolContext, ToolDefinition, ToolExecutionResult, ToolError
from jace.tools.registry import registry

AgentKind = Literal["research", "code", "files", "analyst", "general"]
ReasoningMode = Literal["fast", "balanced", "deep"]


class DelegateAgentTaskInput(BaseModel):
    agent_id: AgentKind = Field(
        description=(
            "Specialist to use. research=current/public information; code=software "
            "engineering; files=local file inspection/organisation; analyst=analysis "
            "and comparison; general=other independent background work."
        )
    )
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(
        min_length=1,
        max_length=30_000,
        description=(
            "The work the specialist itself must perform. Do not phrase this as a request "
            "for the specialist to create or contact another agent."
        ),
    )
    priority: int = Field(default=0, ge=-10, le=10)
    reasoning_mode: ReasoningMode = "balanced"
    allowed_tools: list[str] | None = Field(default=None, max_length=40)


class DelegateAgentDirectorInput(BaseModel):
    objective: str = Field(
        min_length=1,
        max_length=30_000,
        description=(
            "The complete outcome Jace should achieve. The Agent Director will choose the "
            "smallest useful set of specialists, create dependencies, monitor them, and "
            "return one combined handoff."
        ),
    )
    reasoning_mode: ReasoningMode = "balanced"


class AgentTaskIdInput(BaseModel):
    task_id: str = Field(min_length=1, max_length=36)


class ListAgentTasksInput(BaseModel):
    status: str | None = Field(default=None, max_length=30)
    agent_id: AgentKind | None = None
    limit: int = Field(default=10, ge=1, le=30)


class LatestAgentResultInput(BaseModel):
    agent_id: AgentKind | None = Field(
        default=None,
        description=(
            "Optional specialist filter. Omit for natural references such as "
            "'the agent' or 'what did it find?'."
        ),
    )


def _agent_label(agent_id: str) -> str:
    definition = get_agent_definition(agent_id)
    return definition.name if definition else agent_id


def _task_summary(row, *, include_result: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": row.id,
        "agent_id": row.agent_id,
        "agent_name": _agent_label(row.agent_id),
        "title": row.title,
        "status": row.status,
        "progress": round(float(row.progress or 0.0), 3),
        "progress_message": row.progress_message,
        "allowed_tools": task_allowed_tools(row),
        "used_tools": task_used_tools(row),
        "cancel_requested": bool(row.cancel_requested),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error": row.error,
    }
    if include_result:
        summary["result"] = row.result
    elif row.result:
        summary["result_preview"] = row.result[:800]
    return summary


def _user_ready_task_result(row, *, scope: str | None = None) -> str:
    label = _agent_label(row.agent_id)
    scope_text = f" ({scope})" if scope else ""
    if row.status == "completed":
        return (
            f"{label} completed “{row.title}”{scope_text}.\n\n"
            f"{row.result or 'The agent completed but returned no textual result.'}"
        )
    if row.status == "failed":
        return (
            f"{label} failed “{row.title}”{scope_text}.\n\n"
            f"{row.error or 'No error detail was recorded.'}"
        )
    if row.status == "cancelled":
        return f"{label} task “{row.title}” was cancelled{scope_text}."
    return (
        f"{label} is still working on “{row.title}”{scope_text}.\n\n"
        f"Status: {row.status.replace('_', ' ')}\n"
        f"Progress: {round(float(row.progress or 0.0) * 100)}%\n"
        f"Current activity: {row.progress_message or row.status}"
    )


async def _delegate(
    payload: DelegateAgentTaskInput,
    context: ToolContext,
) -> ToolExecutionResult:
    if not agent_manager.running:
        raise ToolError("The background agent manager is not running.")
    definition = get_agent_definition(payload.agent_id)
    if definition is None:
        raise ToolError(f"Unknown specialist: {payload.agent_id}")
    try:
        row = await create_task(
            context.session,
            agent_id=definition.id,
            title=payload.title,
            instruction=payload.instruction,
            conversation_id=context.conversation_id,
            priority=payload.priority,
            reasoning_mode=payload.reasoning_mode,
            allowed_tools=payload.allowed_tools,
            metadata={
                "source": "primary_jace",
                "delegated_from_conversation": context.conversation_id,
                "original_request": context.user_message,
            },
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    queued = await agent_manager.enqueue(row.id, priority=row.priority)
    if not queued:
        raise ToolError(
            "The task was created but the agent manager did not accept it. "
            f"Task ID: {row.id}"
        )
    capability_text = ", ".join(task_allowed_tools(row)) or "no tools"
    display = (
        f"Delegated to {definition.name}: {row.title}\n"
        f"Task ID: {row.id}\nCapabilities: {capability_text}"
    )
    return ToolExecutionResult(
        content=(
            f"I've dispatched the {definition.name} to “{row.title}”. "
            "The task is queued in the background and the main conversation can continue. "
            f"Task ID: {row.id}."
        ),
        display=display,
        metadata={"task_id": row.id, "agent_id": row.agent_id, "status": row.status},
    )


async def _delegate_director(
    payload: DelegateAgentDirectorInput,
    context: ToolContext,
) -> ToolExecutionResult:
    if not agent_manager.running:
        raise ToolError("The background agent manager is not running.")
    workflow_id = launch_director_workflow(
        objective=payload.objective,
        conversation_id=context.conversation_id,
        reasoning_mode=payload.reasoning_mode,
    )
    content = (
        "The Agent Director accepted the objective and is planning the specialist workflow "
        "in the background. Jace does not need to wait for it before continuing this "
        f"conversation. Workflow ID: {workflow_id}."
    )
    return ToolExecutionResult(
        content=content,
        display=f"Agent Director started\nWorkflow ID: {workflow_id}",
        metadata={
            "workflow_id": workflow_id,
            "status": "planning",
            "objective": payload.objective,
        },
    )


async def _check(payload: AgentTaskIdInput, context: ToolContext) -> ToolExecutionResult:
    row = await get_task(context.session, payload.task_id)
    if row is None:
        raise ToolError("Background agent task not found.")
    content = _user_ready_task_result(row)
    return ToolExecutionResult(
        content=content,
        display=content[:1500],
        metadata=_task_summary(row, include_result=True),
    )


async def _list(payload: ListAgentTasksInput, context: ToolContext) -> ToolExecutionResult:
    rows = await list_tasks(
        context.session,
        status=payload.status,
        agent_id=payload.agent_id,
        conversation_id=None,
        limit=payload.limit,
    )
    if not rows:
        return ToolExecutionResult(
            content="No background agent tasks matched that request.",
            display="No background agent tasks matched.",
            metadata={"tasks": []},
        )
    lines = ["Background agent tasks:"]
    metadata_tasks: list[dict[str, Any]] = []
    for row in rows:
        metadata_tasks.append(_task_summary(row))
        result_suffix = ""
        if row.status == "completed" and row.result:
            result_suffix = f" — {row.result[:180].replace(chr(10), ' ')}"
        elif row.status == "failed" and row.error:
            result_suffix = f" — ERROR: {row.error[:180].replace(chr(10), ' ')}"
        lines.append(
            f"- {row.id} | {_agent_label(row.agent_id)} | {row.status} | "
            f"{row.title}{result_suffix}"
        )
    content = "\n".join(lines)
    return ToolExecutionResult(
        content=content,
        display=content[:1500],
        metadata={"tasks": metadata_tasks},
    )


async def _latest_result(
    payload: LatestAgentResultInput,
    context: ToolContext,
) -> ToolExecutionResult:
    rows = await list_tasks(
        context.session,
        agent_id=payload.agent_id,
        conversation_id=context.conversation_id,
        limit=25,
    )
    scope = "this conversation"
    if not rows and context.conversation_id:
        rows = await list_tasks(
            context.session,
            agent_id=payload.agent_id,
            conversation_id=None,
            limit=25,
        )
        scope = "recent Jace history"
    if not rows:
        specialist = f" for the {_agent_label(payload.agent_id)}" if payload.agent_id else ""
        return ToolExecutionResult(
            content=f"No background agent task{specialist} was found.",
            display="No matching background agent task found.",
            metadata={"task": None, "scope": scope},
        )
    row = rows[0]
    content = _user_ready_task_result(row, scope=scope)
    return ToolExecutionResult(
        content=content,
        display=content[:1500],
        metadata={"task": _task_summary(row, include_result=True), "scope": scope},
    )


async def _cancel(payload: AgentTaskIdInput, context: ToolContext) -> ToolExecutionResult:
    row = await get_task(context.session, payload.task_id)
    if row is None:
        raise ToolError("Background agent task not found.")
    if row.status in {"completed", "failed", "cancelled"}:
        return ToolExecutionResult(
            content=f"{row.title} is already {row.status}.",
            display=f"{row.title}: already {row.status}",
        )
    await agent_manager.cancel(row.id)
    refreshed = await get_task(context.session, row.id)
    status = refreshed.status if refreshed else "cancellation_requested"
    return ToolExecutionResult(
        content=(
            f"Cancellation requested for {_agent_label(row.agent_id)} task “{row.title}”. "
            f"Current status: {status}."
        ),
        display=f"Cancellation requested: {row.title}",
        metadata={"task_id": row.id, "status": status},
    )


def register_agent_orchestration_tools() -> None:
    registry.register(
        ToolDefinition(
            name="delegate_agent_task",
            label="Delegate background task",
            description=(
                "Delegate independent work to one persistent Jace specialist while the "
                "primary conversation remains available."
            ),
            category="Agents",
            risk="execute",
            default_permission="ask",
            input_model=DelegateAgentTaskInput,
            handler=_delegate,
        )
    )
    registry.register(
        ToolDefinition(
            name="delegate_agent_director",
            label="Agent Director",
            description=(
                "Give an open-ended multi-step objective to Jace's Agent Director. Use when "
                "the user wants Jace to investigate/diagnose/research/review something and "
                "then act on the findings, asks Jace to choose the right specialists, or "
                "asks multiple agents to coordinate without naming a worker. The Director "
                "chooses the smallest useful workflow, creates dependent background tasks, "
                "monitors them and returns one combined handoff. It grants child agents only "
                "their safe default capabilities."
            ),
            category="Agents",
            risk="execute",
            default_permission="ask",
            input_model=DelegateAgentDirectorInput,
            handler=_delegate_director,
        )
    )
    registry.register(
        ToolDefinition(
            name="check_agent_task",
            label="Check agent task",
            description="Read the real status/result of one exact background task.",
            category="Agents",
            risk="read",
            default_permission="allow",
            input_model=AgentTaskIdInput,
            handler=_check,
        )
    )
    registry.register(
        ToolDefinition(
            name="list_agent_tasks",
            label="List agent tasks",
            description="List recent Jace background tasks and their states.",
            category="Agents",
            risk="read",
            default_permission="allow",
            input_model=ListAgentTasksInput,
            handler=_list,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_latest_agent_result",
            label="Get latest agent result",
            description=(
                "Read the most recent real persisted background-agent result, preferring "
                "the current conversation."
            ),
            category="Agents",
            risk="read",
            default_permission="allow",
            input_model=LatestAgentResultInput,
            handler=_latest_result,
        )
    )
    registry.register(
        ToolDefinition(
            name="cancel_agent_task",
            label="Cancel agent task",
            description="Cancel one queued/running background agent task.",
            category="Agents",
            risk="write",
            default_permission="ask",
            input_model=AgentTaskIdInput,
            handler=_cancel,
        )
    )
