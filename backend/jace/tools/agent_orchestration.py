from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from jace.agents.definitions import get_agent_definition, list_agent_definitions
from jace.agents.manager import agent_manager
from jace.agents.service import (
    create_task,
    get_task,
    list_tasks,
    request_cancel,
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
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short human-readable task title for the office and task history.",
    )
    instruction: str = Field(
        min_length=1,
        max_length=30_000,
        description=(
            "Complete instruction for the background specialist. Include enough context "
            "for the agent to work independently without asking the user questions."
        ),
    )
    priority: int = Field(
        default=0,
        ge=-10,
        le=10,
        description="Priority from -10 (lowest) to 10 (highest). Usually leave at 0.",
    )
    reasoning_mode: ReasoningMode = Field(
        default="balanced",
        description="Reasoning mode for the delegated agent.",
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        max_length=40,
        description=(
            "Optional exact tool capability scope. Omit to use the specialist's safe "
            "default tool set. Only request optional write/execute tools when the user's "
            "task genuinely requires them; the delegation approval covers this scope."
        ),
    )


class AgentTaskIdInput(BaseModel):
    task_id: str = Field(
        min_length=1,
        max_length=36,
        description="Exact background task ID returned by a delegation/list/check call.",
    )


class ListAgentTasksInput(BaseModel):
    status: str | None = Field(
        default=None,
        max_length=30,
        description=(
            "Optional status filter such as queued, running, thinking, using_tool, "
            "waiting_permission, completed, failed or cancelled."
        ),
    )
    agent_id: AgentKind | None = Field(
        default=None,
        description="Optional specialist filter.",
    )
    limit: int = Field(default=10, ge=1, le=30)


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
        f"Task ID: {row.id}\n"
        f"Capabilities: {capability_text}"
    )

    return ToolExecutionResult(
        content=(
            "Background task created successfully.\n"
            f"task_id: {row.id}\n"
            f"agent: {definition.name}\n"
            f"title: {row.title}\n"
            "status: queued\n"
            f"allowed_tools: {capability_text}\n\n"
            "The task is asynchronous. Do not wait for it before continuing the "
            "conversation. Use check_agent_task later when its result is needed."
        ),
        display=display,
        metadata={
            "task_id": row.id,
            "agent_id": row.agent_id,
            "status": row.status,
        },
    )


async def _check(
    payload: AgentTaskIdInput,
    context: ToolContext,
) -> ToolExecutionResult:
    row = await get_task(context.session, payload.task_id)
    if row is None:
        raise ToolError("Background agent task not found.")

    summary = _task_summary(row, include_result=True)

    if row.status == "completed":
        content = (
            f"{_agent_label(row.agent_id)} completed '{row.title}'.\n"
            f"Task ID: {row.id}\n\n"
            f"RESULT\n{row.result or 'No textual result was returned.'}\nEND RESULT"
        )
    elif row.status == "failed":
        content = (
            f"{_agent_label(row.agent_id)} failed '{row.title}'.\n"
            f"Task ID: {row.id}\n"
            f"Error: {row.error or 'Unknown failure'}"
        )
    else:
        content = (
            f"{_agent_label(row.agent_id)} task '{row.title}' is {row.status}.\n"
            f"Task ID: {row.id}\n"
            f"Progress: {round(float(row.progress or 0.0) * 100)}%\n"
            f"Current activity: {row.progress_message or row.status}"
        )

    return ToolExecutionResult(
        content=content,
        display=content[:1500],
        metadata=summary,
    )


async def _list(
    payload: ListAgentTasksInput,
    context: ToolContext,
) -> ToolExecutionResult:
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


async def _cancel(
    payload: AgentTaskIdInput,
    context: ToolContext,
) -> ToolExecutionResult:
    row = await get_task(context.session, payload.task_id)
    if row is None:
        raise ToolError("Background agent task not found.")

    if row.status in {"completed", "failed", "cancelled"}:
        return ToolExecutionResult(
            content=(
                f"Task {row.id} is already {row.status}; no cancellation was necessary."
            ),
            display=f"{row.title}: already {row.status}",
        )

    await agent_manager.cancel(row.id)

    refreshed = await get_task(context.session, row.id)
    status = refreshed.status if refreshed else "cancellation_requested"

    return ToolExecutionResult(
        content=(
            f"Cancellation requested for {_agent_label(row.agent_id)} task "
            f"'{row.title}'. Task ID: {row.id}. Current status: {status}."
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
                "Delegate an independent task to a persistent Jace specialist so the "
                "primary conversation can continue immediately. Use this when the user "
                "explicitly asks for an agent/background task, or when substantial "
                "independent research, code inspection, file analysis, or comparison can "
                "run separately. Do NOT use for trivial questions or tiny actions that "
                "Jace can finish immediately. This call itself is approval-gated because "
                "it creates autonomous background work and may grant a scoped tool set."
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
            name="check_agent_task",
            label="Check agent task",
            description=(
                "Check one exact background agent task and retrieve its complete result "
                "when finished. Use an exact task ID returned by delegation or task listing."
            ),
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
            description=(
                "List recent Jace background-agent tasks, their IDs, specialists, status "
                "and short result/error previews. Use this when the user asks what agents "
                "are doing or when you need to recover a task ID."
            ),
            category="Agents",
            risk="read",
            default_permission="allow",
            input_model=ListAgentTasksInput,
            handler=_list,
        )
    )

    registry.register(
        ToolDefinition(
            name="cancel_agent_task",
            label="Cancel agent task",
            description=(
                "Request cancellation of an exact running or queued background agent task."
            ),
            category="Agents",
            risk="write",
            default_permission="ask",
            input_model=AgentTaskIdInput,
            handler=_cancel,
        )
    )
