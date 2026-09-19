import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from jace.ai.engine import OllamaRequestError, stream_chat
from jace.config import settings
from jace.capabilities.security import validate_external_tool_binding
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
        if definition.capability_id is None
        and permissions.get(definition.name, definition.default_permission) != "deny"
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
        if definition.capability_id is None
        and permissions.get(definition.name, definition.default_permission) != "deny"
    )


def _tool_schemas_for_names(names: list[str]) -> list[dict[str, Any]]:
    if not settings.tools_enabled or not names:
        return []
    ensure_tools_registered()
    return registry.schemas(set(names))


# JACE_STEP4A4_AGENT_BINDING
_PERMISSION_ORDER = {
    "allow": 0,
    "ask": 1,
    "deny": 2,
}


def _effective_permission(
    tool_permission: str,
    capability_binding: dict[str, Any] | None,
) -> str:
    if not capability_binding:
        return tool_permission

    # JACE_STEP4A5_EXTERNAL_BINDING_REVALIDATION
    # Connection capability policy controls normal external access.
    # A global tool Deny remains an emergency kill switch.
    if tool_permission == "deny":
        return "deny"

    capability_permission = str(
        capability_binding.get("permission") or "ask"
    )

    if capability_permission not in _PERMISSION_ORDER:
        return "ask"

    return capability_permission


def _capability_binding_error(
    definition,
    capability_binding: dict[str, Any] | None,
) -> str | None:
    if definition.capability_id is None:
        return None

    if not capability_binding:
        return (
            "External tool execution was blocked because the runtime did not "
            "supply a connection capability binding."
        )

    if capability_binding.get("capability_id") != definition.capability_id:
        return (
            "External tool execution was blocked because its capability "
            "binding did not match."
        )

    if (
        definition.provider_id
        and capability_binding.get("provider_id") != definition.provider_id
    ):
        return (
            "External tool execution was blocked because its provider "
            "binding did not match."
        )

    if not capability_binding.get("connection_id"):
        return (
            "External tool execution was blocked because no connection "
            "was selected."
        )

    return None


async def _execute_tool_call(
    *,
    call: dict[str, Any],
    conversation_id: str | None,
    user_message: str,
    capability_bindings: dict[str, dict[str, Any]] | None = None,
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

    capability_binding = (
        capability_bindings or {}
    ).get(tool_name)

    binding_error = _capability_binding_error(
        definition,
        capability_binding,
    )

    if binding_error:
        yield {
            "type": "tool_result",
            "call_id": "",
            "tool_name": tool_name,
            "label": definition.label,
            "status": "denied",
            "summary": binding_error,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": binding_error,
            },
        }
        return

    async with SessionLocal() as session:
        capability_binding, runtime_binding_error = await validate_external_tool_binding(
            session,
            definition,
            capability_binding,
        )

    if runtime_binding_error:
        yield {
            "type": "tool_result",
            "call_id": "",
            "tool_name": tool_name,
            "label": definition.label,
            "status": "denied",
            "summary": runtime_binding_error,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": runtime_binding_error,
            },
        }
        return

    async with SessionLocal() as session:
        tool_permission = await get_tool_permission(
            session,
            tool_name,
        )
        permission = _effective_permission(
            tool_permission,
            capability_binding,
        )
        # JACE_STEP4B2_SHELL_ALWAYS_ASK
        # Shell execution is intentionally never persistently auto-approved.
        if tool_name == "run_shell_command" and permission != "deny":
            permission = "ask"
        audit = await create_tool_audit(
            session,
            conversation_id=conversation_id,
            tool_name=tool_name,
            permission_mode=permission,
            arguments=arguments,
            provider_id=(capability_binding or {}).get("provider_id"),
            connection_id=(capability_binding or {}).get("connection_id"),
            capability_id=(capability_binding or {}).get("capability_id"),
            account_hint=(capability_binding or {}).get("account_hint"),
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
        "provider_id": (capability_binding or {}).get("provider_id"),
        "connection_id": (capability_binding or {}).get("connection_id"),
        "capability_id": (capability_binding or {}).get("capability_id"),
        "account_hint": (capability_binding or {}).get("account_hint"),
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
            provider_id=(capability_binding or {}).get("provider_id"),
            connection_id=(capability_binding or {}).get("connection_id"),
            capability_id=(capability_binding or {}).get("capability_id"),
            account_hint=(capability_binding or {}).get("account_hint"),
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
            "provider_id": (capability_binding or {}).get("provider_id"),
            "connection_id": (capability_binding or {}).get("connection_id"),
            "capability_id": (capability_binding or {}).get("capability_id"),
            "account_hint": (capability_binding or {}).get("account_hint"),
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

    # Revalidate after any approval wait. A disconnect or policy change while
    # the modal is open must invalidate the pending external action.
    async with SessionLocal() as session:
        capability_binding, runtime_binding_error = await validate_external_tool_binding(
            session,
            definition,
            capability_binding,
        )

    if runtime_binding_error:
        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="denied",
                error=runtime_binding_error,
                completed=True,
            )

        yield {
            "type": "tool_result",
            "call_id": call_id,
            "tool_name": tool_name,
            "label": definition.label,
            "status": "denied",
            "summary": runtime_binding_error,
        }
        yield {
            "type": "_tool_message",
            "message": {
                "role": "tool",
                "tool_name": tool_name,
                "content": runtime_binding_error,
            },
        }
        return

    try:
        async with SessionLocal() as session:
            context = ToolContext(
                session=session,
                conversation_id=conversation_id,
                user_message=user_message,
                capability_binding=capability_binding,
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
        tool_message = {
            "role": "tool",
            "tool_name": tool_name,
            "content": model_content,
        }
        if result.images:
            tool_message["images"] = result.images

        yield {
            "type": "_tool_message",
            "message": tool_message,
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


# JACE_STEP4B1_V3_FILESYSTEM_EXECUTION_GUARD
_FILESYSTEM_INTELLIGENCE_TOOL_NAMES = {
    "workspace_overview",
    "workspace_tree",
    "workspace_recent_files",
    "find_workspace_paths",
    "preview_workspace_edit",
}

# These read-only tools have safe defaults once workspace_id can be resolved
# internally. If the small local model narrates instead of calling the only
# routed tool, Jace can synthesize the empty-argument call and still send it
# through the normal permission/audit executor.
_FILESYSTEM_AUTO_TOOL_NAMES = {
    "workspace_overview",
    "workspace_tree",
    "workspace_recent_files",
}


def _filesystem_auto_tool_name(
    selected_tool_names: list[str] | set[str] | tuple[str, ...],
) -> str | None:
    candidates = sorted(
        set(selected_tool_names)
        & _FILESYSTEM_AUTO_TOOL_NAMES
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


# JACE_STEP4C5A_CALENDAR_WRITE_COMPLETION_GUARD
_CALENDAR_WRITE_TOOL_NAMES = {
    "google_calendar_create_event",
    "google_calendar_modify_event",
    "microsoft_calendar_create_event",
    "microsoft_calendar_modify_event",
}

# JACE_STEP4C5B_STRICT_WRITE_COMPLETION
_CALENDAR_WRITE_REQUEST_RE = re.compile(
    r"\b(?:create|add|schedule|book|make|put|reschedule|move|update|change|"
    r"edit|cancel|delete|remove|invite|set)\b"
    r".{0,180}\b(?:calendar|event|meeting|appointment|series|occurrence|"
    r"attendee|attendees|guest|guests|reminder|reminders|google meet|"
    r"meet link|teams|teams link|online meeting)\b"
    r"|\b(?:reschedule|move|change)\b.{0,140}\b(?:to|from|at)\s+"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
    flags=re.IGNORECASE,
)

_WRITE_SUCCESS_RE = re.compile(
    r"\b(?:done|successfully|created|updated|moved|rescheduled|scheduled|"
    r"booked|deleted|removed|changed|cancelled|added|invited|saved)\b"
    r"|\ball set\b"
    r"|\bset up\b"
    r"|\bon (?:your|the) calendar\b",
    flags=re.IGNORECASE,
)

_WRITE_FAILURE_RE = re.compile(
    r"\b(?:couldn't|could not|didn't|did not|failed|denied|not changed|"
    r"not updated|not moved|not deleted|unable to)\b",
    flags=re.IGNORECASE,
)


def _calendar_write_request(message: str) -> bool:
    return bool(_CALENDAR_WRITE_REQUEST_RE.search(message or ""))


def _looks_like_write_success(content: str) -> bool:
    normalised = " ".join((content or "").strip().split())
    if not normalised:
        return False
    if _WRITE_FAILURE_RE.search(normalised):
        return False
    return bool(_WRITE_SUCCESS_RE.search(normalised))


_ELABORATE_REQUEST_RE = re.compile(
    r"\b(?:summari[sz]e|summary|explain|analyse|analyze|review|research|compare|overview|"
    r"tell me about|walk me through|describe|what changed|what does .* (?:say|contain|show))\b",
    flags=re.IGNORECASE,
)
_EXPLICIT_SHORT_RE = re.compile(
    r"\b(?:briefly|brief answer|short answer|one sentence|single sentence|in one sentence|concise)\b",
    flags=re.IGNORECASE,
)
_INCOMPLETE_TAIL_RE = re.compile(
    r"(?:\b(?:and|or|but|because|so|if|when|while|which|that|to|for|with|from|of|the|a|an|"
    r"no|not|is|are|was|were|has|have|had|will|would|can|could|should|may|might|this|these|"
    r"there|into|about|such as)\s*)$",
    flags=re.IGNORECASE,
)


def _looks_incomplete_response(
    content: str,
    *,
    done_reason: str | None,
    user_message: str,
    tool_calls_used: int,
) -> bool:
    """Conservatively detect a model turn that ended before answering fully.

    Small local models occasionally terminate a tool-finalisation turn after a
    clause fragment (for example, ``There is no``). Accept genuinely short
    answers, but retry clear truncations and suspiciously tiny research answers.
    """
    text = " ".join(content.strip().split())
    if not text:
        return True

    reason = (done_reason or "").lower()
    if reason in {"length", "max_tokens", "max_token", "limit"}:
        return True

    if text.endswith((",", ":", ";", "-", "—", "(", "[", "{")):
        return True
    if _INCOMPLETE_TAIL_RE.search(text):
        return True

    words = re.findall(r"\b[\w'’-]+\b", text)
    elaborate = bool(_ELABORATE_REQUEST_RE.search(user_message))
    explicit_short = bool(_EXPLICIT_SHORT_RE.search(user_message))

    if not explicit_short and elaborate:
        if tool_calls_used > 0 and len(words) < 24:
            return True
        if len(words) < 9:
            return True

    return False


async def _repair_final_response(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    reasoning_mode: str,
    temperature: float,
    usage: AgentUsage,
) -> tuple[list[str], dict[str, Any] | None]:
    """Regenerate one complete final answer from already-collected tool context."""
    repair_prompt = (
        system_prompt
        + "\n\nFINAL RESPONSE RECOVERY\n"
        + "The previous final-answer attempt ended incomplete. Do not call another tool. "
        + "Using the user request and tool results already present in the conversation, "
        + "write the complete user-facing answer now. Start the answer from the beginning, "
        + "do not mention the failed attempt, and make sure every requested part is answered.\n"
        + "END FINAL RESPONSE RECOVERY"
    )
    parts: list[str] = []
    final_chunk: dict[str, Any] | None = None
    async for chunk in stream_chat(
        model=model,
        messages=messages,
        system_prompt=repair_prompt,
        reasoning_mode=reasoning_mode,
        temperature=temperature,
        tools=None,
    ):
        message = chunk.get("message") or {}
        content = message.get("content") or ""
        if content:
            parts.append(content)
        if chunk.get("done"):
            final_chunk = chunk
            usage.add_chunk(chunk)
    return parts, final_chunk


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
    current_images: list[str] | None = None,
    attachment_context: str = "",
    capability_bindings: dict[str, dict[str, Any]] | None = None,
):
    """Streaming multi-turn agent loop with guarded final-answer recovery.

    Plain chat streams immediately.

    Tool-enabled turns previously buffered the *entire* model turn before
    emitting anything, so any request that routed a tool showed nothing until
    generation had completely finished — and voice output could not start until
    then either. Ollama emits ``tool_calls`` at the very start of a turn, so a
    short decision window is enough: content is held back only until
    ``settings.tool_stream_buffer_chars`` characters have arrived with no tool
    call, after which the held text is released and the rest streams live.

    Set ``JACE_TOOL_STREAM_BUFFER_CHARS`` to 0 to stream tool turns immediately,
    or to -1 to restore the old buffer-the-whole-turn behaviour.

    A clearly incomplete final turn is still automatically retried once before it
    is persisted as complete.
    """
    ensure_tools_registered()
    agent_messages = [dict(message) for message in messages]
    if agent_messages and agent_messages[-1].get("role") == "user":
        if attachment_context.strip():
            existing = str(agent_messages[-1].get("content") or "")
            agent_messages[-1]["content"] = (
                existing + "\n\n" + attachment_context.strip()
            ).strip()
        if current_images:
            agent_messages[-1]["images"] = current_images

    selected_tool_names = (
        tool_names if tool_names is not None else await routed_tool_names(user_message)
    )
    tools = _tool_schemas_for_names(selected_tool_names)

    usage = AgentUsage()
    calendar_write_requested = _calendar_write_request(user_message)
    calendar_write_completed = False
    calendar_write_attempted = False
    calendar_write_last_result: str | None = None
    calendar_write_retry_count = 0
    filesystem_intelligence_tools = {
        name
        for name in selected_tool_names
        if name in _FILESYSTEM_INTELLIGENCE_TOOL_NAMES
    }
    filesystem_intelligence_requested = bool(
        filesystem_intelligence_tools
    )
    filesystem_intelligence_attempted = False
    filesystem_intelligence_last_result: str | None = None
    filesystem_intelligence_retry_count = 0
    empty_response_retries = 0
    incomplete_response_retries = 0
    active_system_prompt = system_prompt
    if calendar_write_requested:
        supplied_calendar_write_tools = sorted(
            name
            for name in selected_tool_names
            if name in _CALENDAR_WRITE_TOOL_NAMES
        )
        active_system_prompt = (
            system_prompt
            + "\n\nCALENDAR WRITE CONTRACT\n"
            + "This request changes calendar data. A verbal acknowledgement is not execution. "
            + (
                "The executable provider calendar write tool supplied for this turn is: "
                + ", ".join(supplied_calendar_write_tools)
                + ". You MUST call it to perform the requested write. "
                if supplied_calendar_write_tools
                else (
                    "No executable provider calendar write tool was supplied for this turn. "
                    "You MUST NOT claim the calendar was changed. "
                )
            )
            + "For modifications, if the local event ID is unknown, call calendar_find_event first. "
            + "Do not say the calendar was created, scheduled, booked, changed, moved, updated, "
            + "deleted or otherwise written unless a provider calendar write tool in this turn "
            + "returns status=completed.\n"
            + "END CALENDAR WRITE CONTRACT"
        )

    if filesystem_intelligence_requested:
        active_system_prompt = (
            active_system_prompt
            + "\n\nFILESYSTEM INTELLIGENCE CONTRACT\n"
            + "The user's request requires inspecting an approved local workspace. "
            + "You MUST call the supplied filesystem intelligence tool before giving "
            + "the requested project/file answer. Do not merely say you need to list "
            + "workspaces or that you will inspect them. workspace_id may be omitted; "
            + "the tool will safely auto-select a single active readable workspace or "
            + "a uniquely named workspace from the user's request. If selection is "
            + "ambiguous, use the tool error/candidate IDs to clarify. Supplied "
            + "filesystem intelligence tools: "
            + ", ".join(sorted(filesystem_intelligence_tools))
            + ".\nEND FILESYSTEM INTELLIGENCE CONTRACT"
        )
    decision_window = int(settings.tool_stream_buffer_chars)
    # A turn with no tools cannot produce a tool call, so it always streams live.
    hold_for_tool_decision = (
        calendar_write_requested
        or filesystem_intelligence_requested
        or (bool(tools) and decision_window != 0)
    )

    for _step in range(settings.max_tool_steps):
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        raw_tool_calls: list[dict[str, Any]] = []
        final_chunk: dict[str, Any] | None = None

        # `released` means tokens for this turn are already visible to the user.
        released = not hold_for_tool_decision
        held_parts: list[str] = []
        held_chars = 0

        async for chunk in stream_chat(
            model=model,
            messages=agent_messages,
            system_prompt=active_system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tools or None,
        ):
            message = chunk.get("message") or {}

            thinking = message.get("thinking") or ""
            if thinking:
                thinking_parts.append(thinking)

            calls = message.get("tool_calls") or []
            if isinstance(calls, list) and calls:
                raw_tool_calls.extend(
                    call for call in calls if isinstance(call, dict)
                )
                # The turn is a tool-planning turn after all. Drop any narration
                # still inside the decision window instead of showing it.
                if not released:
                    held_parts = []
                    held_chars = 0

            content = message.get("content") or ""
            if content:
                content_parts.append(content)

                if released:
                    yield {"type": "token", "content": content}
                elif not raw_tool_calls:
                    held_parts.append(content)
                    held_chars += len(content)

                    if (
                        decision_window > 0
                        and held_chars >= decision_window
                        and not calendar_write_requested
                        and not filesystem_intelligence_requested
                    ):
                        # Enough prose with no tool call: this is an answer.
                        released = True
                        for held in held_parts:
                            yield {"type": "token", "content": held}
                        held_parts = []
                        held_chars = 0

            if chunk.get("done"):
                final_chunk = chunk
                usage.add_chunk(chunk)

        tool_calls = _dedupe_tool_calls(raw_tool_calls)
        content_text = "".join(content_parts)
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content_text,
        }
        if thinking_parts:
            assistant_message["thinking"] = "".join(thinking_parts)

        if (
            not tool_calls
            and filesystem_intelligence_requested
            and not filesystem_intelligence_attempted
        ):
            auto_tool_name = _filesystem_auto_tool_name(
                selected_tool_names
            )
            if auto_tool_name:
                tool_calls = [
                    {
                        "type": "function",
                        "function": {
                            "name": auto_tool_name,
                            "arguments": {},
                        },
                    }
                ]

        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        if not tool_calls:
            if (
                filesystem_intelligence_requested
                and not filesystem_intelligence_attempted
            ):
                if filesystem_intelligence_retry_count < 2:
                    filesystem_intelligence_retry_count += 1
                    active_system_prompt = (
                        system_prompt
                        + "\n\nFILESYSTEM INTELLIGENCE RECOVERY\n"
                        + "Your previous attempt described a future workspace action "
                        + "instead of executing it. Call one of these supplied tools now: "
                        + ", ".join(sorted(filesystem_intelligence_tools))
                        + ". Do not tell the user you are about to inspect/list/pull up "
                        + "the workspace. Execute the tool call first. workspace_id can be "
                        + "omitted when the workspace is unambiguous.\n"
                        + "END FILESYSTEM INTELLIGENCE RECOVERY"
                    )
                    continue

                content_text = (
                    "I couldn't inspect the workspace because no filesystem "
                    "intelligence tool executed successfully in this turn."
                )
                content_parts = [content_text]

            if not content_text.strip():
                if empty_response_retries < 1:
                    empty_response_retries += 1
                    active_system_prompt = (
                        system_prompt
                        + "\n\nEMPTY RESPONSE RECOVERY\n"
                        + "Your previous model turn produced no user-visible response. "
                        + "Respond to the user's latest request now. If one of the supplied "
                        + "tools is required, call it. Otherwise answer the user directly. "
                        + "Do not return an empty response.\n"
                        + "END EMPTY RESPONSE RECOVERY"
                    )
                    continue
                raise OllamaRequestError(
                    "Ollama returned an empty assistant response twice."
                )

            done_reason = (final_chunk or {}).get("done_reason")
            incomplete = _looks_incomplete_response(
                content_text,
                done_reason=done_reason,
                user_message=user_message,
                tool_calls_used=usage.tool_calls,
            )

            if incomplete and incomplete_response_retries < 1:
                incomplete_response_retries += 1

                if not released and usage.tool_calls == 0:
                    # The model answered prematurely instead of using the tools
                    # routed for this request. Discard the fragment and retry the
                    # decision turn with stronger instructions.
                    active_system_prompt = (
                        system_prompt
                        + "\n\nINCOMPLETE TOOL-TURN RECOVERY\n"
                        + "Your previous attempt ended with an incomplete answer before the user's request was fulfilled. "
                        + "Use the supplied tool that is appropriate for the request before answering when external/tool data is needed. "
                        + "If the user supplied a URL or bare domain and asked to read or summarise it, call read_web_page directly "
                        + "using https:// for a bare domain. Do not merely say that information is unavailable without attempting the supplied tool.\n"
                        + "END INCOMPLETE TOOL-TURN RECOVERY"
                    )
                    continue

                if not released and usage.tool_calls > 0:
                    # Tool results already exist. Regenerate the final answer once
                    # with tools removed so another planning cycle cannot replace
                    # the answer with another fragment/tool call.
                    repaired_parts, repaired_final = await _repair_final_response(
                        model=model,
                        messages=agent_messages,
                        system_prompt=system_prompt,
                        reasoning_mode=reasoning_mode,
                        temperature=temperature,
                        usage=usage,
                    )
                    repaired_text = "".join(repaired_parts).strip()
                    if repaired_text:
                        content_parts = repaired_parts
                        content_text = "".join(repaired_parts)
                        final_chunk = repaired_final or final_chunk
                        assistant_message = {
                            "role": "assistant",
                            "content": content_text,
                        }

                elif released:
                    # Plain-chat tokens are already visible. Ask for a natural
                    # continuation and stream only the continuation.
                    agent_messages.append(assistant_message)
                    continuation_prompt = (
                        system_prompt
                        + "\n\nCONTINUATION RECOVERY\n"
                        + "The immediately preceding assistant message was cut off. Continue exactly where it stopped, "
                        + "without repeating its existing text, and finish the answer completely.\n"
                        + "END CONTINUATION RECOVERY"
                    )
                    continuation_parts: list[str] = []
                    continuation_final: dict[str, Any] | None = None
                    async for chunk in stream_chat(
                        model=model,
                        messages=agent_messages,
                        system_prompt=continuation_prompt,
                        reasoning_mode=reasoning_mode,
                        temperature=temperature,
                        tools=None,
                    ):
                        message = chunk.get("message") or {}
                        continuation = message.get("content") or ""
                        if continuation:
                            continuation_parts.append(continuation)
                            yield {"type": "token", "content": continuation}
                        if chunk.get("done"):
                            continuation_final = chunk
                            usage.add_chunk(chunk)
                    if continuation_parts:
                        content_text += "".join(continuation_parts)
                        final_chunk = continuation_final or final_chunk

            if (
                calendar_write_requested
                and not calendar_write_completed
            ):
                supplied_write_tools = {
                    name
                    for name in selected_tool_names
                    if name in _CALENDAR_WRITE_TOOL_NAMES
                }
                clarification = (
                    "?" in content_text
                    or bool(
                        re.search(
                            r"\b(?:which|what time|what date|which calendar|"
                            r"which account|clarify|need to know)\b",
                            content_text,
                            flags=re.IGNORECASE,
                        )
                    )
                )
                if (
                    supplied_write_tools
                    and not calendar_write_attempted
                    and not clarification
                    and calendar_write_retry_count < 2
                ):
                    calendar_write_retry_count += 1
                    active_system_prompt = (
                        system_prompt
                        + "\n\nCALENDAR WRITE RECOVERY\n"
                        + "The user asked you to change calendar data, but no provider calendar "
                        + "write tool has executed yet. Find the event if necessary, then call the "
                        + "supplied provider write tool before answering. Do not claim success without "
                        + "a completed write result.\n"
                        + "END CALENDAR WRITE RECOVERY"
                    )
                    continue
                # JACE_STEP4C5B_V2_NO_PENDING_WRITE_PROSE
                # A Calendar write turn may finish only with a required
                # clarification or with evidence that the provider write
                # completed. Never finish with processing/executing prose.
                if not clarification:
                    if calendar_write_last_result:
                        content_text = (
                            "I didn't complete the calendar change. "
                            + calendar_write_last_result
                            + " The event has not been confirmed as changed."
                        )
                    else:
                        content_text = (
                            "I didn't complete the calendar change because no "
                            "calendar write tool completed successfully. The "
                            "event has not been confirmed as changed."
                        )

                    content_parts = [
                        content_text
                    ]

            agent_messages.append({"role": "assistant", "content": content_text})

            # Short answers can finish inside the decision window, and the repair
            # path replaces content_parts wholesale. Release the final/repaired
            # answer here, never a discarded planning fragment.
            if not released:
                for content in content_parts:
                    yield {"type": "token", "content": content}

            yield {
                "type": "agent_done",
                "model": (final_chunk or {}).get("model", model),
                "done_reason": (final_chunk or {}).get("done_reason"),
                "metrics": usage.raw_metrics(),
            }
            return

        # Internal tool-planning turn. Keep it in model context but do not expose
        # its narration to the user.
        agent_messages.append(assistant_message)
        active_system_prompt = system_prompt
        empty_response_retries = 0
        incomplete_response_retries = 0

        for call in tool_calls:
            usage.tool_calls += 1
            tool_message: dict[str, Any] | None = None
            async for event in _execute_tool_call(
                call=call,
                conversation_id=conversation_id,
                user_message=user_message,
                capability_bindings=capability_bindings,
            ):
                if event.get("type") == "_tool_message":
                    tool_message = event["message"]
                else:
                    event_tool_name = str(event.get("tool_name") or "")
                    if (
                        event.get("type") == "tool_call"
                        and event_tool_name in _FILESYSTEM_INTELLIGENCE_TOOL_NAMES
                    ):
                        filesystem_intelligence_attempted = True
                    if (
                        event.get("type") == "tool_result"
                        and event_tool_name in _FILESYSTEM_INTELLIGENCE_TOOL_NAMES
                    ):
                        filesystem_intelligence_last_result = str(
                            event.get("summary")
                            or event.get("status")
                            or ""
                        )

                    if (
                        event.get("type") == "tool_call"
                        and event_tool_name in _CALENDAR_WRITE_TOOL_NAMES
                    ):
                        calendar_write_attempted = True
                    if (
                        event.get("type") == "tool_result"
                        and event_tool_name in _CALENDAR_WRITE_TOOL_NAMES
                    ):
                        calendar_write_last_result = str(
                            event.get("summary")
                            or event.get("status")
                            or ""
                        )
                        if event.get("status") == "completed":
                            calendar_write_completed = True
                    yield event
            if tool_message is None:
                tool_name = call["function"]["name"]
                tool_message = {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": "Tool execution did not produce a result.",
                }
            agent_messages.append(tool_message)

    # Safety-limit finalisation: tools are removed and one complete answer is
    # generated from the information already gathered.
    if (
        calendar_write_requested
        and not calendar_write_completed
    ):
        system_prompt = (
            system_prompt
            + "\n\nCALENDAR WRITE TOOL LIMIT SAFETY\n"
            + "No provider calendar write completed in this turn. Do not claim the calendar "
            + "was created, moved, updated, deleted, cancelled, or otherwise changed. State "
            + "that the requested calendar change was not confirmed.\n"
            + "END CALENDAR WRITE TOOL LIMIT SAFETY"
        )

    limit_prompt = (
        system_prompt
        + "\n\nTOOL LIMIT\n"
        + "The maximum number of tool steps for this request has been reached. "
        + "Do not request another tool. Answer using the information already available.\n"
        + "END TOOL LIMIT"
    )
    final_chunk: dict[str, Any] | None = None
    final_content_parts: list[str] = []
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
            final_content_parts.append(content)
            yield {"type": "token", "content": content}
        if chunk.get("done"):
            final_chunk = chunk
            usage.add_chunk(chunk)

    if not "".join(final_content_parts).strip():
        raise OllamaRequestError(
            "Ollama returned an empty response after reaching the tool step limit."
        )

    yield {
        "type": "agent_done",
        "model": (final_chunk or {}).get("model", model),
        "done_reason": (final_chunk or {}).get("done_reason"),
        "metrics": usage.raw_metrics(),
    }
