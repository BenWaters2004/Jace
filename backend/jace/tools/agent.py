import asyncio
import json
from dataclasses import dataclass
from typing import Any

from jace.ai.engine import stream_chat
from jace.config import settings
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.approvals import approval_manager
from jace.tools.base import ToolContext, ToolError
from jace.tools.permissions import (
    create_tool_audit,
    get_tool_permission,
    permission_map,
    update_tool_audit,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


@dataclass
class AgentUsage:
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_count: int = 0
    prompt_eval_cached_count: int = 0
    prompt_eval_duration: int = 0
    eval_count: int = 0
    eval_duration: int = 0
    model: str = ""
    done_reason: str | None = None
    model_turns: int = 0
    tool_calls: int = 0

    def add_chunk(self, chunk: dict[str, Any]) -> None:
        self.total_duration += int(chunk.get("total_duration") or 0)
        self.load_duration += int(chunk.get("load_duration") or 0)
        self.prompt_eval_count += int(chunk.get("prompt_eval_count") or 0)
        self.prompt_eval_cached_count += int(chunk.get("prompt_eval_cached_count") or 0)
        self.prompt_eval_duration += int(chunk.get("prompt_eval_duration") or 0)
        self.eval_count += int(chunk.get("eval_count") or 0)
        self.eval_duration += int(chunk.get("eval_duration") or 0)
        self.model = str(chunk.get("model") or self.model)
        self.done_reason = chunk.get("done_reason")
        self.model_turns += 1

    def raw_metrics(self) -> dict[str, Any]:
        return {
            "total_duration": self.total_duration or None,
            "load_duration": self.load_duration or None,
            "prompt_eval_count": self.prompt_eval_count or None,
            "prompt_eval_cached_count": self.prompt_eval_cached_count or None,
            "prompt_eval_duration": self.prompt_eval_duration or None,
            "eval_count": self.eval_count or None,
            "eval_duration": self.eval_duration or None,
            "model_turns": self.model_turns,
            "tool_calls": self.tool_calls,
        }


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

    normalised: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }

    if "index" in function:
        normalised["function"]["index"] = function["index"]

    return normalised


def _dedupe_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    fingerprints: set[str] = set()

    for call in calls:
        normalised = _normalise_tool_call(call)
        if normalised is None:
            continue

        function = normalised["function"]
        fingerprint = json.dumps(
            {
                "name": function["name"],
                "arguments": function["arguments"],
                "index": function.get("index"),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

        if fingerprint in fingerprints:
            continue

        fingerprints.add(fingerprint)
        unique.append(normalised)

    return unique


async def routed_tool_names(user_message: str) -> list[str]:
    """Return permitted tool names that are relevant to this user message."""
    if not settings.tools_enabled:
        return []

    ensure_tools_registered()

    async with SessionLocal() as session:
        permissions = await permission_map(session)

    allowed_names = {
        definition.name
        for definition in registry.all()
        if permissions.get(definition.name, definition.default_permission) != "deny"
    }

    if settings.smart_tool_routing:
        selected = route_tool_names(user_message) & allowed_names
    else:
        selected = allowed_names

    return sorted(selected)


async def available_tool_count(user_message: str | None = None) -> int:
    if user_message is not None and settings.smart_tool_routing:
        return len(await routed_tool_names(user_message))

    if not settings.tools_enabled:
        return 0

    ensure_tools_registered()
    async with SessionLocal() as session:
        permissions = await permission_map(session)

    return sum(
        1
        for definition in registry.all()
        if permissions.get(definition.name, definition.default_permission) != "deny"
    )


def _tool_schemas_for_names(names: list[str]) -> list[dict[str, Any]]:
    if not settings.tools_enabled or not names:
        return []
    ensure_tools_registered()
    return registry.schemas(set(names))


async def _execute_tool_call(
    *,
    call: dict[str, Any],
    conversation_id: str | None,
    user_message: str,
):
    """
    Yield public tool events and finish with one private `_tool_message` event
    containing the role=tool message that must be sent back to Ollama.
    """
    function = call["function"]
    tool_name = function["name"]
    arguments = function.get("arguments") or {}
    definition = registry.get(tool_name)

    if definition is None:
        yield {
            "type": "tool_result",
            "call_id": "",
            "tool_name": tool_name,
            "label": tool_name,
            "status": "failed",
            "summary": "Unknown tool.",
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": "Unknown tool.",
            },
        }
        return

    async with SessionLocal() as session:
        permission = await get_tool_permission(session, tool_name)
        audit = await create_tool_audit(
            session,
            conversation_id=conversation_id,
            tool_name=tool_name,
            permission_mode=permission,
            arguments=arguments,
        )

    call_id = audit.id

    yield {
        "type": "tool_call",
        "call_id": call_id,
        "tool_name": tool_name,
        "label": definition.label,
        "description": definition.description,
        "risk": definition.risk,
        "permission": permission,
        "arguments": arguments,
    }

    if permission == "deny":
        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="denied",
                error="Tool is disabled by permission policy.",
                completed=True,
            )

        yield {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "status": "denied",
            "summary": "Tool is disabled by permission policy.",
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": "Tool execution was denied by Jace's permission policy.",
            },
        }
        return

    if permission == "ask":
        approval = approval_manager.create(
            conversation_id=conversation_id,
            tool_name=tool_name,
            label=definition.label,
            description=definition.description,
            risk=definition.risk,
            arguments=arguments,
        )

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="awaiting_approval",
                approval_id=approval.approval_id,
            )

        yield {
            "type": "approval_required",
            "approval_id": approval.approval_id,
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "description": definition.description,
            "risk": definition.risk,
            "arguments": arguments,
        }

        try:
            approved = await approval_manager.wait(approval.approval_id)
        except asyncio.TimeoutError:
            async with SessionLocal() as session:
                await update_tool_audit(
                    session,
                    audit.id,
                    status="timed_out",
                    error="User approval timed out.",
                    completed=True,
                )

            yield {
                "type": "tool_result",
                "call_id": call_id,
                "tool_name": tool_name,
                "label": definition.label,
                "status": "denied",
                "summary": "Approval timed out.",
            }
            yield {
                "type": "_tool_message",
                "message": {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": "Tool execution was not approved before the approval timeout.",
                },
            }
            return
        except asyncio.CancelledError:
            approval_manager.cancel(approval.approval_id)
            raise

        if not approved:
            async with SessionLocal() as session:
                await update_tool_audit(
                    session,
                    audit.id,
                    status="denied",
                    error="User denied tool execution.",
                    completed=True,
                )

            yield {
                "type": "tool_result",
                "call_id": call_id,
                "tool_name": tool_name,
                "label": definition.label,
                "status": "denied",
                "summary": "User denied this tool call.",
            }
            yield {
                "type": "_tool_message",
                "message": {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": "The user denied this tool call.",
                },
            }
            return

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="approved",
            )

    try:
        async with SessionLocal() as session:
            context = ToolContext(
                session=session,
                conversation_id=conversation_id,
                user_message=user_message,
            )
            result = await definition.execute(arguments, context)

        model_content = result.content[: settings.tool_result_max_chars]
        display = (result.display or result.content)[: settings.tool_audit_preview_chars]

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="completed",
                result_preview=display,
                completed=True,
            )

        yield {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "status": "completed",
            "summary": display,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": model_content,
            },
        }
        return

    except (ToolError, ValueError) as exc:
        message = str(exc)

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=message,
                completed=True,
            )

        yield {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "status": "failed",
            "summary": message,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": f"Tool failed: {message}",
            },
        }
        return

    except Exception as exc:
        message = f"Unexpected tool failure: {exc}"

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=message,
                completed=True,
            )

        yield {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "status": "failed",
            "summary": message,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": message,
            },
        }


async def stream_agent(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    reasoning_mode: str,
    temperature: float,
    conversation_id: str | None,
    user_message: str,
    tool_names: list[str] | None = None,
):
    """
    Streaming multi-turn agent loop.

    Normal answers keep streaming. If the model emits tool calls, their results
    are appended as role=tool messages and the model continues until it produces
    a turn with no more tool calls.
    """
    ensure_tools_registered()

    agent_messages = [dict(message) for message in messages]
    selected_tool_names = tool_names if tool_names is not None else await routed_tool_names(user_message)
    tools = _tool_schemas_for_names(selected_tool_names)
    usage = AgentUsage()

    for _step in range(settings.max_tool_steps):
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        raw_tool_calls: list[dict[str, Any]] = []
        final_chunk: dict[str, Any] | None = None

        async for chunk in stream_chat(
            model=model,
            messages=agent_messages,
            system_prompt=system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tools or None,
        ):
            message = chunk.get("message") or {}

            thinking = message.get("thinking") or ""
            if thinking:
                thinking_parts.append(thinking)

            content = message.get("content") or ""
            if content:
                content_parts.append(content)
                yield {"type": "token", "content": content}

            calls = message.get("tool_calls") or []
            if isinstance(calls, list):
                raw_tool_calls.extend(call for call in calls if isinstance(call, dict))

            if chunk.get("done"):
                final_chunk = chunk
                usage.add_chunk(chunk)

        tool_calls = _dedupe_tool_calls(raw_tool_calls)

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts),
        }
        if thinking_parts:
            assistant_message["thinking"] = "".join(thinking_parts)
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        agent_messages.append(assistant_message)

        if not tool_calls:
            yield {
                "type": "agent_done",
                "model": (final_chunk or {}).get("model", model),
                "done_reason": (final_chunk or {}).get("done_reason"),
                "metrics": usage.raw_metrics(),
            }
            return

        for call in tool_calls:
            usage.tool_calls += 1
            tool_message: dict[str, Any] | None = None

            async for event in _execute_tool_call(
                call=call,
                conversation_id=conversation_id,
                user_message=user_message,
            ):
                if event.get("type") == "_tool_message":
                    tool_message = event["message"]
                else:
                    yield event

            if tool_message is None:
                tool_name = call["function"]["name"]
                tool_message = {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": "Tool execution did not produce a result.",
                }

            agent_messages.append(tool_message)

    # The model kept asking for tools beyond the configured safety limit.
    # Generate one final response without tools so the user still gets a useful
    # answer and the loop cannot run forever.
    limit_prompt = (
        system_prompt
        + "\n\nTOOL LIMIT\n"
        + "The maximum number of tool steps for this request has been reached. "
        + "Do not request another tool. Answer using the information already available.\n"
        + "END TOOL LIMIT"
    )

    final_chunk: dict[str, Any] | None = None
    async for chunk in stream_chat(
        model=model,
        messages=agent_messages,
        system_prompt=limit_prompt,
        reasoning_mode=reasoning_mode,
        temperature=temperature,
        tools=None,
    ):
        message = chunk.get("message") or {}
        content = message.get("content") or ""
        if content:
            yield {"type": "token", "content": content}
        if chunk.get("done"):
            final_chunk = chunk
            usage.add_chunk(chunk)

    yield {
        "type": "agent_done",
        "model": (final_chunk or {}).get("model", model),
        "done_reason": (final_chunk or {}).get("done_reason"),
        "metrics": usage.raw_metrics(),
    }
