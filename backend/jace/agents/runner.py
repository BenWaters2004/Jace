from __future__ import annotations

import asyncio
import json
from typing import Any

from jace.agents.config import agent_settings
from jace.agents.definitions import get_agent_definition
from jace.agents.models import AgentTask
from jace.agents.service import (
    get_task,
    task_allowed_tools,
    update_task_state,
)
from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, stream_chat
from jace.database import SessionLocal
from jace.db.conversations import get_conversation, model_history
from jace.db.settings import get_or_create_assistant_settings
from jace.runtime import runtime_events
from jace.tools import ensure_tools_registered
from jace.tools.base import ToolContext, ToolError
from jace.tools.permissions import (
    create_tool_audit,
    get_tool_permission,
    update_tool_audit,
)
from jace.tools.registry import registry


class AgentTaskCancelled(Exception):
    pass


def _normalise_tool_call(raw: dict[str, Any]) -> dict[str, Any] | None:
    function = raw.get("function") or {}
    name = function.get("name")

    if not isinstance(name, str) or not name:
        return None

    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    if not isinstance(arguments, dict):
        arguments = {}

    return {
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _dedupe_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in calls:
        call = _normalise_tool_call(raw)
        if call is None:
            continue

        fingerprint = json.dumps(call, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            continue

        seen.add(fingerprint)
        output.append(call)

    return output


async def _publish_task(task: AgentTask, *, event: str = "agent.task.changed") -> None:
    await runtime_events.publish(
        event,
        task_id=task.id,
        agent_id=task.agent_id,
        status=task.status,
        progress=task.progress,
        progress_message=task.progress_message,
        conversation_id=task.conversation_id,
    )


async def _set_state(
    task_id: str,
    *,
    status: str,
    progress: float,
    message: str,
    event_type: str,
    event_message: str,
    event_data: dict[str, Any] | None = None,
    started: bool = False,
) -> AgentTask:
    async with SessionLocal() as session:
        task = await get_task(session, task_id)
        if task is None:
            raise RuntimeError("Agent task disappeared during execution.")

        task = await update_task_state(
            session,
            task,
            status=status,
            progress=progress,
            progress_message=message,
            started=started,
            event_type=event_type,
            event_message=event_message,
            event_data_value=event_data,
        )

    await _publish_task(task)
    return task


async def _effective_tool_names(task: AgentTask) -> list[str]:
    ensure_tools_registered()

    definition = get_agent_definition(task.agent_id)
    if definition is None:
        return []

    scoped = set(task_allowed_tools(task)) & definition.all_tools
    usable: list[str] = []

    async with SessionLocal() as session:
        for name in scoped:
            tool = registry.get(name)
            if tool is None:
                continue

            # A global deny is always final. A task-specific allowed_tools list is
            # the explicit capability grant for this background run, equivalent
            # to the pre-approved scope used by Jace automations.
            if await get_tool_permission(session, name) == "deny":
                continue

            usable.append(name)

    return sorted(usable)


async def _execute_tool(
    *,
    task: AgentTask,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    definition = registry.get(tool_name)
    if definition is None:
        return {
            "role": "tool",
            "tool_name": tool_name,
            "content": "Unknown tool.",
        }

    allowed = set(task_allowed_tools(task))
    agent_definition = get_agent_definition(task.agent_id)

    if (
        tool_name not in allowed
        or agent_definition is None
        or tool_name not in agent_definition.all_tools
    ):
        return {
            "role": "tool",
            "tool_name": tool_name,
            "content": "Tool denied: this background task was not granted that capability.",
        }

    async with SessionLocal() as session:
        global_permission = await get_tool_permission(session, tool_name)

        audit = await create_tool_audit(
            session,
            conversation_id=task.conversation_id,
            tool_name=tool_name,
            permission_mode=f"agent:{task.id}",
            arguments=arguments,
            status="approved" if global_permission != "deny" else "denied",
        )

        if global_permission == "deny":
            await update_tool_audit(
                session,
                audit.id,
                status="denied",
                error="Globally denied tool cannot run in a background agent task.",
                completed=True,
            )
            return {
                "role": "tool",
                "tool_name": tool_name,
                "content": "Tool denied by Jace's global tool policy.",
            }

        try:
            result = await definition.execute(
                arguments,
                ToolContext(
                    session=session,
                    conversation_id=task.conversation_id,
                    user_message=task.instruction,
                ),
            )

            content = result.content[:8_000]
            display = (result.display or result.content)[:1_500]

            await update_tool_audit(
                session,
                audit.id,
                status="completed",
                result_preview=display,
                completed=True,
            )

            message: dict[str, Any] = {
                "role": "tool",
                "tool_name": tool_name,
                "content": content,
            }
            if result.images:
                message["images"] = result.images

            return message

        except (ToolError, ValueError) as exc:
            error = str(exc)

            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=error,
                completed=True,
            )

            return {
                "role": "tool",
                "tool_name": tool_name,
                "content": f"Tool failed: {error}",
            }

        except Exception as exc:
            error = f"Unexpected tool failure: {exc}"

            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=error,
                completed=True,
            )

            return {
                "role": "tool",
                "tool_name": tool_name,
                "content": error,
            }


async def _conversation_context(task: AgentTask) -> list[dict[str, Any]]:
    if (
        not task.conversation_id
        or agent_settings.conversation_context_messages <= 0
    ):
        return []

    async with SessionLocal() as session:
        conversation = await get_conversation(session, task.conversation_id)
        if conversation is None:
            return []

        history = model_history(
            conversation,
            max_messages=agent_settings.conversation_context_messages,
            max_chars=8_000,
        )

    # Tool-call structures from the primary chat are not needed by a background
    # specialist. Give it only the user-visible conversational context.
    return [
        {
            "role": item["role"],
            "content": str(item.get("content") or ""),
        }
        for item in history
        if item.get("role") in {"user", "assistant"}
    ]


async def execute_agent_task(
    task_id: str,
    *,
    cancel_event: asyncio.Event,
) -> None:
    ensure_tools_registered()

    async with SessionLocal() as session:
        task = await get_task(session, task_id)
        if task is None:
            return
        if task.cancel_requested or cancel_event.is_set():
            raise AgentTaskCancelled()

        definition = get_agent_definition(task.agent_id)
        if definition is None:
            raise RuntimeError(f"Unknown agent type: {task.agent_id}")

        profile = await get_or_create_assistant_settings(session)
        model = task.model or profile.default_model
        temperature = profile.temperature
        reasoning_mode = task.reasoning_mode

    await _set_state(
        task_id,
        status="running",
        progress=0.08,
        message="Starting",
        event_type="started",
        event_message=f"{definition.name} started work.",
        started=True,
    )

    tool_names = await _effective_tool_names(task)
    tool_schemas = registry.schemas(set(tool_names)) if tool_names else []

    context_messages = await _conversation_context(task)

    messages: list[dict[str, Any]] = [
        *context_messages,
        {
            "role": "user",
            "content": (
                "BACKGROUND TASK\n"
                f"Title: {task.title}\n"
                f"Assigned specialist: {definition.name}\n\n"
                f"Instruction:\n{task.instruction}\n"
                "END BACKGROUND TASK"
            ),
        },
    ]

    used_tools: list[str] = []
    final_text = ""

    for step in range(agent_settings.max_tool_steps):
        if cancel_event.is_set():
            raise AgentTaskCancelled()

        step_progress = min(0.20 + (step * 0.08), 0.75)

        await _set_state(
            task_id,
            status="thinking",
            progress=step_progress,
            message="Reasoning",
            event_type="thinking",
            event_message=f"{definition.name} is reasoning about the task.",
            event_data={"step": step + 1},
        )

        content_parts: list[str] = []
        raw_calls: list[dict[str, Any]] = []

        async for chunk in stream_chat(
            model=model,
            messages=messages,
            system_prompt=definition.system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tool_schemas or None,
        ):
            if cancel_event.is_set():
                raise AgentTaskCancelled()

            message = chunk.get("message") or {}
            content = message.get("content") or ""
            if content:
                content_parts.append(content)

            calls = message.get("tool_calls") or []
            if isinstance(calls, list):
                raw_calls.extend(
                    item for item in calls if isinstance(item, dict)
                )

        calls = _dedupe_tool_calls(raw_calls)

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts),
        }

        if calls:
            assistant_message["tool_calls"] = calls

        messages.append(assistant_message)

        if not calls:
            final_text = assistant_message["content"].strip()
            break

        for call in calls:
            if cancel_event.is_set():
                raise AgentTaskCancelled()

            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            used_tools.append(name)

            await _set_state(
                task_id,
                status="using_tool",
                progress=min(step_progress + 0.05, 0.82),
                message=f"Using {name}",
                event_type="tool_started",
                event_message=f"{definition.name} is using {name}.",
                event_data={
                    "tool_name": name,
                    "arguments": arguments,
                },
            )

            current_task: AgentTask
            async with SessionLocal() as session:
                current_task = await get_task(session, task_id)
                if current_task is None:
                    raise RuntimeError("Agent task disappeared during tool execution.")

            tool_message = await _execute_tool(
                task=current_task,
                tool_name=name,
                arguments=arguments,
            )
            messages.append(tool_message)

            async with SessionLocal() as session:
                current_task = await get_task(session, task_id)
                if current_task is not None:
                    await update_task_state(
                        session,
                        current_task,
                        status="thinking",
                        progress=min(step_progress + 0.07, 0.84),
                        progress_message="Reviewing tool result",
                        used_tools=used_tools,
                        event_type="tool_completed",
                        event_message=f"{name} returned to {definition.name}.",
                        event_data_value={"tool_name": name},
                    )
                    await _publish_task(current_task)

    else:
        if cancel_event.is_set():
            raise AgentTaskCancelled()

        # Force one final non-tool turn after the capability-step budget.
        parts: list[str] = []
        final_prompt = (
            definition.system_prompt
            + "\n\nTOOL LIMIT REACHED\n"
            + "Do not call another tool. Return the best final handoff using the "
            + "information already gathered.\nEND TOOL LIMIT REACHED"
        )

        async for chunk in stream_chat(
            model=model,
            messages=messages,
            system_prompt=final_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=None,
        ):
            if cancel_event.is_set():
                raise AgentTaskCancelled()

            content = (chunk.get("message") or {}).get("content") or ""
            if content:
                parts.append(content)

        final_text = "".join(parts).strip()

    if not final_text:
        final_text = "The background agent completed without a textual handoff."

    final_text = final_text[: agent_settings.result_max_chars]

    async with SessionLocal() as session:
        current = await get_task(session, task_id)
        if current is None:
            return

        current = await update_task_state(
            session,
            current,
            status="completed",
            progress=1.0,
            progress_message="Complete",
            result=final_text,
            used_tools=used_tools,
            completed=True,
            event_type="completed",
            event_message=f"{definition.name} completed the task.",
            event_data_value={"used_tools": sorted(set(used_tools)), "model": model},
        )

    await _publish_task(current, event="agent.task.completed")
