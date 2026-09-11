from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from jace.agents.config import agent_settings
from jace.agents.definitions import get_agent_definition
from jace.agents.models import AgentTask
from jace.agents.service import (
    get_task,
    task_allowed_tools,
    task_metadata,
    update_task_state,
)
from jace.ai.engine import stream_chat
from jace.config import settings
from jace.computer.service import list_workspaces
from jace.database import SessionLocal
from jace.db.conversations import add_message, get_conversation, model_history
from jace.db.settings import get_or_create_assistant_settings
from jace.memory.extractor import schedule_agent_memory_extraction
from jace.performance import chat_activity
from jace.runtime import runtime_events
from jace.tools import ensure_tools_registered
from jace.tools.base import ToolContext, ToolError
from jace.tools.permissions import (
    create_tool_audit,
    get_tool_permission,
    update_tool_audit,
)
from jace.tools.registry import registry

logger = logging.getLogger("uvicorn.error")


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


async def _publish_task(
    task: AgentTask,
    *,
    event: str = "agent.task.changed",
    **extra: Any,
) -> None:
    await runtime_events.publish(
        event,
        task_id=task.id,
        agent_id=task.agent_id,
        status=task.status,
        progress=task.progress,
        progress_message=task.progress_message,
        conversation_id=task.conversation_id,
        **extra,
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

            if await get_tool_permission(session, name) == "deny":
                continue

            usable.append(name)

    return sorted(usable)


def _director_work_mode(task: AgentTask) -> str:
    metadata = task_metadata(task)
    value = str(metadata.get("director_work_mode") or "").strip().casefold()
    if value in {"inspect", "modify", "create", "files", "research", "analysis", "general"}:
        return value
    return "inspect" if task.agent_id == "code" else "files" if task.agent_id == "files" else "general"


def _director_required_source_reads(task: AgentTask) -> int:
    metadata = task_metadata(task)
    raw = metadata.get("director_required_source_reads")
    try:
        return max(0, min(4, int(raw)))
    except (TypeError, ValueError):
        return 0


def _director_requires_workspace_context(task: AgentTask) -> bool:
    metadata = task_metadata(task)
    return metadata.get("director_managed") is True and task.agent_id in {"code", "files"}


def _director_requires_local_source(task: AgentTask) -> bool:
    if not _director_requires_workspace_context(task) or task.agent_id != "code":
        return False
    return _director_work_mode(task) in {"inspect", "modify"} and _director_required_source_reads(task) > 0


def _safe_workspace_inventory(root_path: str, *, max_entries: int = 80) -> list[str]:
    """Return names/types only from an already-approved readable workspace root."""
    try:
        root = Path(root_path)
        children = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError:
        return []
    output: list[str] = []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            kind = "dir" if child.is_dir() else "file"
        except OSError:
            continue
        output.append(f"{kind}:{child.name}")
        if len(output) >= max_entries:
            break
    return output


async def _readable_workspace_context() -> tuple[str, list[dict[str, Any]]]:
    """Describe user-approved readable workspaces without assuming any repository layout."""
    async with SessionLocal() as session:
        workspaces = await list_workspaces(session, active_only=True)

    readable = [
        workspace for workspace in workspaces
        if bool(getattr(workspace, "is_active", False))
        and bool(getattr(workspace, "read_enabled", False))
    ]
    catalog: list[dict[str, Any]] = []
    if not readable:
        return (
            "APPROVED READABLE WORKSPACES\n"
            "None are configured. Do not invent local evidence.\n"
            "END APPROVED READABLE WORKSPACES",
            catalog,
        )

    lines = ["APPROVED READABLE WORKSPACES"]
    for workspace in readable:
        inventory = _safe_workspace_inventory(str(workspace.root_path))
        catalog.append({
            "id": str(workspace.id),
            "label": str(workspace.label),
            "root_path": str(workspace.root_path),
            "write_enabled": bool(getattr(workspace, "write_enabled", False)),
            "inventory": inventory,
        })
        lines.append(
            f"- id={workspace.id} | label={workspace.label} | root={workspace.root_path} | "
            f"write_enabled={bool(getattr(workspace, 'write_enabled', False))}"
        )
        if inventory:
            lines.append("  top-level: " + ", ".join(inventory[:50]))
    lines.extend([
        "Workspace tool paths are ALWAYS relative to the selected workspace root.",
        "For list_workspace_files, begin with path='.' unless a listed relative directory is known to exist.",
        "Never pass the absolute root path as the tool path.",
        "Use the exact workspace id shown above.",
        "END APPROVED READABLE WORKSPACES",
    ])
    return "\n".join(lines), catalog


def _director_source_rules(workspace_context: str, task: AgentTask) -> str:
    mode = _director_work_mode(task)
    required = _director_required_source_reads(task)
    if mode == "create":
        return (
            "DIRECTOR PROJECT CREATION RULES\n"
            "This is a new-project/software creation task. Do not require source files that do not exist yet.\n"
            "- Inspect the workspace root and existing conventions if present.\n"
            "- If write/execute tools were explicitly authorised, create the requested artifacts and verify what you created.\n"
            "- If write tools are not available, produce a precise implementation/file plan and state that execution requires authorised write capability.\n"
            "- Never claim a file was created, modified, tested, or executed without successful tool evidence.\n"
            f"{workspace_context}\n"
            "END DIRECTOR PROJECT CREATION RULES"
        )
    return (
        "DIRECTOR PROJECT EVIDENCE RULES\n"
        "This is an existing-project investigation/change task. Do not answer project-specific implementation questions from memory.\n"
        "- Discover the project structure from the approved workspace rather than assuming folders, languages, or architecture.\n"
        "- Use list/search tools to locate relevant artifacts, then read the source that supports your conclusion.\n"
        f"- Successfully read at least {required} DISTINCT relevant source file(s) before presenting implementation claims.\n"
        "- Distinct means different paths; rereading one file never increases coverage.\n"
        "- Choose files because they are relevant to the observed flow/problem, not because of any predetermined directory naming convention.\n"
        "- Cite exact relative paths you actually read and at least one exact function/class/symbol present in those reads.\n"
        "- Never invent file names, functions, handlers, registries, layers, or architecture.\n"
        "- If evidence is incomplete, name the additional component/artifact that still needs inspection instead of guessing.\n"
        f"{workspace_context}\n"
        "END DIRECTOR PROJECT EVIDENCE RULES"
    )


def _required_source_read_count(task: AgentTask) -> int:
    return _director_required_source_reads(task) if _director_requires_local_source(task) else 0


def _source_coverage_status(
    task: AgentTask,
    source_paths: set[str],
    required_source_reads: int,
) -> tuple[bool, str]:
    del task
    distinct_count = len(source_paths)
    if distinct_count < required_source_reads:
        return False, f"{distinct_count}/{required_source_reads} distinct relevant source files read"
    return True, f"source requirements satisfied with {distinct_count} distinct file(s)"


def _source_coverage_nudge(task: AgentTask, source_paths: set[str]) -> str:
    del task
    if not source_paths:
        return (
            "Start from the approved workspace inventory. Use path='.' for a root listing or search_workspace_files "
            "with terms from the task, then read the most relevant source file."
        )
    return (
        "Inspect a DIFFERENT relevant source file that has not already been counted. Use the evidence already found "
        "to decide which adjacent component, caller/callee, configuration, test, or integration point needs inspection. "
        "Do not assume a directory name or project architecture."
    )


def _workspace_by_id(catalog: list[dict[str, Any]], workspace_id: str) -> dict[str, Any] | None:
    for item in catalog:
        if str(item.get("id") or "") == str(workspace_id or ""):
            return item
    return None


def _relative_if_inside_root(raw_path: str, root_path: str) -> str | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return "."
    raw_norm = raw.replace("\\", "/").rstrip("/")
    root_norm = str(root_path or "").replace("\\", "/").rstrip("/")
    if raw_norm.casefold() == root_norm.casefold():
        return "."
    prefix = root_norm + "/"
    if raw_norm.casefold().startswith(prefix.casefold()):
        relative = raw_norm[len(prefix):].lstrip("/")
        return relative or "."
    return None


def _repair_workspace_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Repair only safe, unambiguous workspace argument mistakes made by small local models."""
    workspace_tools = {
        "list_workspace_files", "read_workspace_file", "search_workspace_files", "workspace_file_info",
        "inspect_workspace_media", "create_workspace_directory", "write_workspace_file", "replace_workspace_text",
        "move_workspace_path", "delete_workspace_file", "run_workspace_command",
    }
    if tool_name not in workspace_tools or not catalog:
        return dict(arguments), []

    fixed = dict(arguments)
    notes: list[str] = []
    valid_ids = {str(item.get("id") or "") for item in catalog}
    supplied_id = str(fixed.get("workspace_id") or "")
    if supplied_id not in valid_ids and len(catalog) == 1:
        fixed["workspace_id"] = str(catalog[0]["id"])
        notes.append("replaced missing/invalid workspace_id with the sole approved workspace id")

    selected = _workspace_by_id(catalog, str(fixed.get("workspace_id") or ""))
    if selected is not None and "path" in fixed:
        raw_path = str(fixed.get("path") or "")
        relative = _relative_if_inside_root(raw_path, str(selected.get("root_path") or ""))
        if relative is not None and relative != raw_path:
            fixed["path"] = relative
            notes.append("converted an absolute workspace path to a workspace-relative path")
    if tool_name == "list_workspace_files" and not str(fixed.get("path") or "").strip():
        fixed["path"] = "."
        notes.append("defaulted list_workspace_files path to '.'")
    return fixed, notes


def _workspace_failure_nudge(
    tool_name: str,
    error: str,
    catalog: list[dict[str, Any]],
) -> str | None:
    if not catalog:
        return None
    lowered = (error or "").casefold()
    if tool_name == "list_workspace_files" and (
        "does not exist" in lowered or "cannot be accessed" in lowered or "not a directory" in lowered
    ):
        return (
            "WORKSPACE PATH CORRECTION: that directory path failed. Paths are relative to the approved workspace root. "
            "Call list_workspace_files with path='.' to rediscover the actual top-level structure, then choose an existing relative path."
        )
    if "unknown computer workspace" in lowered:
        ids = ", ".join(str(item.get("id") or "") for item in catalog)
        return f"WORKSPACE ID CORRECTION: use one of the approved workspace ids exactly as provided: {ids}."
    return None


def _source_evidence_dossier(records: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    seen_paths: set[str] = set()
    for record in records:
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        text = str(evidence.get("text") or "").strip()
        if not path or not text:
            continue
        normalized = path.replace("\\", "/").casefold()
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        chunks.append(f"SOURCE FILE: {path}\n{text[:6000]}\nEND SOURCE FILE: {path}")
    return "\n\n".join(chunks)[:14000]


async def _finalize_source_backed_handoff(
    *,
    task_id: str,
    cancel_event: asyncio.Event,
    task: AgentTask,
    model: str,
    reasoning_mode: str,
    temperature: float,
    system_prompt: str,
    evidence_records: list[dict[str, Any]],
    draft: str,
) -> str:
    """Turn successful raw source reads into a citation-bearing worker handoff.

    Small local models sometimes make the correct tool call and then emit an
    empty final message.  The source evidence is still valuable.  Give the
    worker a final no-tools pass over only that evidence so the Director gets a
    usable, verifiable handoff instead of the generic "completed without text"
    fallback.
    """
    dossier = _source_evidence_dossier(evidence_records)
    if not dossier:
        return draft

    prompt = (
        "SOURCE-BACKED FINAL HANDOFF\n"
        f"Task: {task.title}\n"
        f"Instruction: {task.instruction}\n\n"
        f"Previous draft (may be empty or unreliable):\n{draft or '[none]'}\n\n"
        "The following source excerpts were successfully read by Jace and are the ONLY authority "
        "for local implementation claims in this handoff.\n\n"
        f"{dossier}\n\n"
        "Write a concise specialist handoff to Jace. Requirements:\n"
        "- Cite every source file you rely on using its exact relative path.\n"
        "- Cite at least one exact function/class/symbol from the excerpts in backticks.\n"
        "- Separate verified source facts from hypotheses or missing evidence.\n"
        "- Do not invent any file, symbol, handler, registry, state, or architecture term.\n"
        "- If these excerpts are insufficient to establish the root cause, say exactly what additional "
        "file/flow needs inspection rather than guessing.\n"
        "- Do not call tools; this is the final handoff.\n"
        "END SOURCE-BACKED FINAL HANDOFF"
    )

    for attempt in range(2):
        parts, _ = await _background_model_turn(
            task_id=task_id,
            cancel_event=cancel_event,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                system_prompt
                + "\n\nYou are finalising a source-backed Code/File specialist handoff. "
                "Use only the supplied source excerpts for local implementation claims."
            ),
            reasoning_mode=reasoning_mode,
            temperature=min(float(temperature), 0.35),
            tools=None,
            progress=0.94 + (attempt * 0.01),
        )
        text = "".join(parts).strip()
        if text:
            return text

    # Keep this explicitly unverified.  The Director/Analyst can still inspect
    # the captured raw evidence directly rather than losing the successful read.
    paths = [
        str(record.get("evidence", {}).get("path") or "").strip()
        for record in evidence_records
        if isinstance(record.get("evidence"), dict)
    ]
    paths = [path for path in paths if path]
    return (
        "UNVERIFIED ANALYSIS: source inspection succeeded, but the Code/File specialist "
        "did not produce a textual source analysis after finalisation retries. "
        f"Successfully read: {', '.join(dict.fromkeys(paths)) or 'unknown source path'}. "
        "The Director should pass the captured source excerpts to Analyst rather than inventing a conclusion."
    )


def _parse_tool_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_evidence_payload(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    success: bool,
    content: str = "",
    display: str = "",
    error: str = "",
) -> dict[str, Any]:
    """Persist compact, inspectable evidence for Director verification.

    `used_tools_json` only proves that a model attempted a tool call.  The
    Director needs to know whether the call succeeded and what concrete source
    it returned before it can call a project-specific claim verified.
    """
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "success": bool(success),
        "arguments": arguments,
    }
    if display:
        payload["display"] = display[:1000]
    if error:
        payload["error"] = error[:1500]
    if not success:
        return payload

    parsed = _parse_tool_json(content)
    if tool_name == "read_workspace_file":
        payload["evidence"] = {
            "workspace": parsed.get("workspace"),
            "path": parsed.get("path"),
            "sha256": parsed.get("sha256"),
            "start_line": parsed.get("start_line"),
            "returned_lines": parsed.get("returned_lines"),
            "text": str(parsed.get("text") or "")[:5000],
        }
    elif tool_name == "search_workspace_files":
        results = parsed.get("results")
        if not isinstance(results, list):
            results = []
        payload["evidence"] = {
            "workspace": parsed.get("workspace"),
            "query": parsed.get("query"),
            "result_count": len(results),
            "results": results[:20],
            "files_scanned": parsed.get("files_scanned"),
        }
    elif tool_name == "list_workspace_files":
        entries = parsed.get("entries")
        if not isinstance(entries, list):
            entries = []
        payload["evidence"] = {
            "workspace": parsed.get("workspace"),
            "directory": parsed.get("directory"),
            "entries": entries[:40],
        }
    elif tool_name == "workspace_file_info":
        payload["evidence"] = {
            "workspace": parsed.get("workspace"),
            "path": parsed.get("path"),
            "type": parsed.get("type"),
            "sha256": parsed.get("sha256"),
        }
    else:
        # Web/retrieval tools vary in shape. Keep a bounded preview so the
        # Director can still distinguish a successful call from a failed one.
        payload["result_preview"] = content[:3000]
    return payload


async def _execute_tool(
    *,
    task: AgentTask,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    definition = registry.get(tool_name)
    if definition is None:
        message = {
            "role": "tool",
            "tool_name": tool_name,
            "content": "Unknown tool.",
        }
        return message, _tool_evidence_payload(
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            error="Unknown tool.",
        )

    allowed = set(task_allowed_tools(task))
    agent_definition = get_agent_definition(task.agent_id)
    if (
        tool_name not in allowed
        or agent_definition is None
        or tool_name not in agent_definition.all_tools
    ):
        error = "Tool denied: this background task was not granted that capability."
        message = {
            "role": "tool",
            "tool_name": tool_name,
            "content": error,
        }
        return message, _tool_evidence_payload(
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            error=error,
        )

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
            error = "Tool denied by Jace's global tool policy."
            await update_tool_audit(
                session,
                audit.id,
                status="denied",
                error="Globally denied tool cannot run in a background agent task.",
                completed=True,
            )
            message = {
                "role": "tool",
                "tool_name": tool_name,
                "content": error,
            }
            return message, _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=error,
            )
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

            return message, _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=True,
                content=content,
                display=display,
            )
        except (ToolError, ValueError) as exc:
            error = str(exc)

            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=error,
                completed=True,
            )

            message = {
                "role": "tool",
                "tool_name": tool_name,
                "content": f"Tool failed: {error}",
            }
            return message, _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=error,
            )
        except Exception as exc:
            error = f"Unexpected tool failure: {exc}"

            await update_tool_audit(
                session,
                audit.id,
                status="failed",
                error=error,
                completed=True,
            )

            message = {
                "role": "tool",
                "tool_name": tool_name,
                "content": error,
            }
            return message, _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=error,
            )


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
    # The user's orchestration command and Jace's acknowledgement are not task
    # context. Feeding them to the specialist caused responses such as
    # "I don't have access to an Analyst Agent" because the Analyst believed it
    # was being asked to launch another Analyst.
    original_request = str(task_metadata(task).get("original_request") or "").strip()

    if original_request:
        origin_index: int | None = None
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            if (
                item.get("role") == "user"
                and str(item.get("content") or "").strip() == original_request
            ):
                origin_index = index
                break

        if origin_index is not None:
            history = history[:origin_index]
    return [
        {
            "role": item["role"],
            "content": str(item.get("content") or ""),
        }
        for item in history
        if item.get("role") in {"user", "assistant"}
    ]


async def _background_model_turn(
    *,
    task_id: str,
    cancel_event: asyncio.Event,
    model: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    reasoning_mode: str,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    progress: float,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Give interactive Jace priority over background Ollama inference.
    A background task waits until chat is idle before starting a model turn. If
    the user starts speaking/chatting while the specialist is generating, the
    partial background turn is discarded and its Ollama stream is closed. The
    specialist resumes from the same stable context once Jace is idle again.

    Tool calls are only executed *after* a complete model turn, so yielding here
    cannot duplicate a side effect.
    """
    while True:
        if cancel_event.is_set():
            raise AgentTaskCancelled()

        await chat_activity.wait_for_idle(0.18)

        if cancel_event.is_set():
            raise AgentTaskCancelled()

        content_parts: list[str] = []
        raw_calls: list[dict[str, Any]] = []
        yielded_to_foreground = False
        stream = stream_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tools,
        )

        try:
            async for chunk in stream:
                if cancel_event.is_set():
                    raise AgentTaskCancelled()
                # A new interactive request started after this background turn
                # began. Release Ollama to foreground Jace.
                if chat_activity.active > 0:
                    yielded_to_foreground = True
                    break

                message = chunk.get("message") or {}

                content = message.get("content") or ""
                if content:
                    content_parts.append(content)
                calls = message.get("tool_calls") or []
                if isinstance(calls, list):
                    raw_calls.extend(
                        item for item in calls if isinstance(item, dict)
                    )
        finally:
            try:
                await stream.aclose()
            except Exception:
                pass

        if not yielded_to_foreground:
            return content_parts, raw_calls
        await _set_state(
            task_id,
            status="running",
            progress=progress,
            message="Paused while Jace responds",
            event_type="yielded_to_foreground",
            event_message="Background inference yielded to the primary conversation.",
        )

        logger.info(
            "Agent task %s yielded Ollama to foreground Jace.",
            task_id,
        )


async def _persist_completion_handoff(
    *,
    task_id: str,
    agent_name: str,
    agent_id: str,
    result: str,
) -> str | None:
    """
    Persist the specialist result into the originating conversation.

    This is the real shared handoff. It means the next primary Jace turn sees
    the result through normal conversation history even if no result tool is
    needed.
    """
    async with SessionLocal() as session:
        task = await get_task(session, task_id)
        if task is None or not task.conversation_id:
            return None

        metadata = task_metadata(task)

        # 11B.4: Director-managed child workers feed their result back to the
        # Director, which persists one combined user-facing handoff after the
        # dependency graph completes. Suppress each raw child result here so a
        # Research -> Analyst -> Code workflow does not flood the chat with
        # three separate specialist cards. The task/result remains fully
        # visible in Pixel Office and its memory curation still runs below.
        if (
            metadata.get("director_managed") is True
            or metadata.get("suppress_chat_handoff") is True
        ):
            return None

        existing_id = metadata.get("handoff_message_id")
        if isinstance(existing_id, str) and existing_id:
            return existing_id

        conversation = await get_conversation(session, task.conversation_id)
        if conversation is None:
            return None
        content = (
            f"{agent_name} finished the background task “{task.title}”.\n\n"
            f"{result}"
        ).strip()

        message = await add_message(
            session,
            conversation=conversation,
            role="assistant",
            content=content,
            status="complete",
            model=f"agent:{agent_id}",
        )
        # add_message commits. Mark the task after the message exists so a
        # restart cannot produce duplicate handoffs.
        metadata["handoff_message_id"] = message.id
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        await session.commit()

        return message.id


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
        memory_auto_extract = bool(
            getattr(profile, "memory_enabled", settings.memory_enabled)
            and getattr(profile, "memory_auto_extract", settings.memory_auto_extract)
        )

    # The task was delegated from an active chat request. Do not let the
    # background worker seize the same local model before Jace has acknowledged
    # the delegation and returned to idle.
    await chat_activity.wait_for_idle(0.18)
    if cancel_event.is_set():
        raise AgentTaskCancelled()

    task = await _set_state(
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

    requires_workspace_context = _director_requires_workspace_context(task)
    requires_local_source = _director_requires_local_source(task)
    workspace_context = ""
    workspace_catalog: list[dict[str, Any]] = []
    readable_workspace_count = 0
    worker_system_prompt = definition.system_prompt
    if requires_workspace_context:
        workspace_context, workspace_catalog = await _readable_workspace_context()
        readable_workspace_count = len(workspace_catalog)
        worker_system_prompt = (
            definition.system_prompt
            + "\n\n"
            + _director_source_rules(workspace_context, task)
        )
        logger.info(
            "Director-managed %s task %s has %d approved readable workspace(s); mode=%s.",
            definition.name,
            task_id,
            readable_workspace_count,
            _director_work_mode(task),
        )

    context_messages = await _conversation_context(task)
    messages: list[dict[str, Any]] = [
        *context_messages,
        {
            "role": "user",
            "content": (
                "BACKGROUND SPECIALIST ASSIGNMENT\n"
                f"You are the assigned specialist: {definition.name}.\n"
                "Do NOT create, call, delegate to, or wait for another agent. "
                "You are the worker who must perform this task.\n\n"
                f"Task: {task.title}\n"
                f"Instruction: {task.instruction}\n"
                + (f"\n{workspace_context}\n" if requires_workspace_context else "")
                + "Return your findings as a handoff to Jace.\n"
                "END BACKGROUND SPECIALIST ASSIGNMENT"
            ),
        },
    ]
    used_tools: list[str] = []
    final_text = ""
    successful_source_reads = 0
    successful_source_paths: set[str] = set()
    source_evidence_records: list[dict[str, Any]] = []
    required_source_reads = _required_source_read_count(task) if requires_local_source else 0
    evidence_nudges = 0
    max_evidence_nudges = 4 if requires_local_source else 0
    if requires_local_source:
        logger.info(
            "Director-managed %s task %s requires %d DISTINCT relevant source read(s) using project-discovered paths.",
            definition.name,
            task_id,
            required_source_reads,
        )

    # Director work is intentionally allowed a larger investigation budget than a
    # simple one-off agent task. The cap remains bounded by the global maximum.
    extra_steps = 8 if requires_local_source else 4 if requires_workspace_context else 0
    tool_step_limit = min(20, agent_settings.max_tool_steps + extra_steps)
    for step in range(tool_step_limit):
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
        content_parts, raw_calls = await _background_model_turn(
            task_id=task_id,
            cancel_event=cancel_event,
            model=model,
            messages=messages,
            system_prompt=worker_system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tool_schemas or None,
            progress=step_progress,
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
            proposed_text = assistant_message["content"].strip()
            coverage_ok, coverage_reason = _source_coverage_status(
                task, successful_source_paths, required_source_reads
            ) if requires_local_source else (True, "not required")
            if requires_local_source and not coverage_ok:
                if readable_workspace_count <= 0:
                    final_text = (
                        "UNVERIFIED: no approved readable computer workspace is configured, so I could not "
                        "inspect the requested project source. Configure the intended project directory as a readable "
                        "Computer workspace and rerun this task."
                    )
                    break

                if evidence_nudges < max_evidence_nudges:
                    evidence_nudges += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "SOURCE EVIDENCE REQUIRED BEFORE FINAL ANSWER.\n"
                            f"Coverage status: {coverage_reason}. "
                            f"Already-counted source paths: {', '.join(sorted(successful_source_paths)) or '[none]'}. "
                            "Do not answer from memory or assumptions. "
                            + _source_coverage_nudge(task, successful_source_paths)
                            + " Only after the full coverage requirement is satisfied may you produce the final handoff.\n"
                            f"{workspace_context}\n"
                            "END SOURCE EVIDENCE REQUIRED"
                        ),
                    })
                    logger.info(
                        "Director-managed %s task %s attempted to finish with incomplete source coverage (%s); forcing workspace inspection (%d/%d).",
                        definition.name,
                        task_id,
                        coverage_reason,
                        evidence_nudges,
                        max_evidence_nudges,
                    )
                    continue

                final_text = (
                    "UNVERIFIED: I could not complete the required source coverage after repeated evidence "
                    f"prompts ({coverage_reason}). No implementation claim from this task should be treated as verified."
                )
                break

            final_text = proposed_text
            break

        for call in calls:
            if cancel_event.is_set():
                raise AgentTaskCancelled()
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            if requires_workspace_context:
                repaired_arguments, repair_notes = _repair_workspace_tool_arguments(
                    name, arguments, workspace_catalog
                )
                if repair_notes:
                    logger.info(
                        "Agent task %s repaired %s arguments: %s",
                        task_id,
                        name,
                        "; ".join(repair_notes),
                    )
                    arguments = repaired_arguments
                    call["function"]["arguments"] = arguments
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
            async with SessionLocal() as session:
                current_task = await get_task(session, task_id)
                if current_task is None:
                    raise RuntimeError(
                        "Agent task disappeared during tool execution."
                    )

            tool_message, tool_execution = await _execute_tool(
                task=current_task,
                tool_name=name,
                arguments=arguments,
            )
            post_tool_nudge: str | None = None
            if bool(tool_execution.get("success")) and name == "read_workspace_file":
                evidence = tool_execution.get("evidence")
                if isinstance(evidence, dict):
                    try:
                        returned_lines = int(evidence.get("returned_lines") or 0)
                    except (TypeError, ValueError):
                        returned_lines = 0
                    if returned_lines > 0 and str(evidence.get("text") or "").strip():
                        source_path = str(evidence.get("path") or "").strip()
                        normalized_path = source_path.replace("\\", "/").casefold()
                        source_evidence_records.append(tool_execution)
                        if normalized_path and normalized_path not in successful_source_paths:
                            successful_source_paths.add(normalized_path)
                            successful_source_reads = len(successful_source_paths)
                            logger.info(
                                "Director-managed %s task %s verified DISTINCT source read %d/%d: %s",
                                definition.name,
                                task_id,
                                successful_source_reads,
                                required_source_reads,
                                source_path or "<unknown path>",
                            )
                            coverage_ok, coverage_reason = _source_coverage_status(
                                task, successful_source_paths, required_source_reads
                            )
                            if not coverage_ok:
                                post_tool_nudge = (
                                    f"SOURCE COVERAGE INCOMPLETE after reading {source_path}: {coverage_reason}. "
                                    + _source_coverage_nudge(task, successful_source_paths)
                                )
                                logger.info(
                                    "Director-managed %s task %s source coverage still incomplete after %s: %s",
                                    definition.name,
                                    task_id,
                                    source_path or "<unknown path>",
                                    coverage_reason,
                                )
                        else:
                            logger.info(
                                "Director-managed %s task %s reread source %s; duplicate path does not increase coverage (%d/%d).",
                                definition.name,
                                task_id,
                                source_path or "<unknown path>",
                                successful_source_reads,
                                required_source_reads,
                            )
                            coverage_ok, coverage_reason = _source_coverage_status(
                                task, successful_source_paths, required_source_reads
                            )
                            if not coverage_ok:
                                post_tool_nudge = (
                                    "DUPLICATE SOURCE READ DOES NOT COUNT. "
                                    f"You already inspected {source_path or 'that path'}. "
                                    f"Coverage is still incomplete: {coverage_reason}. "
                                    + _source_coverage_nudge(task, successful_source_paths)
                                )
            elif tool_execution.get("success") is not True:
                tool_error = str(tool_execution.get("error") or "unknown tool failure")
                logger.warning(
                    "Agent task %s tool %s failed: %s",
                    task_id,
                    name,
                    tool_error[:500],
                )
                if requires_workspace_context:
                    post_tool_nudge = _workspace_failure_nudge(name, tool_error, workspace_catalog)
            messages.append(tool_message)
            if post_tool_nudge:
                messages.append({"role": "user", "content": post_tool_nudge})
            async with SessionLocal() as session:
                current_task = await get_task(session, task_id)
                if current_task is not None:
                    succeeded = bool(tool_execution.get("success"))
                    current_task = await update_task_state(
                        session,
                        current_task,
                        status="thinking",
                        progress=min(step_progress + 0.07, 0.84),
                        progress_message=(
                            "Reviewing tool result" if succeeded else "Reviewing tool failure"
                        ),
                        used_tools=used_tools,
                        event_type="tool_completed",
                        event_message=(
                            f"{name} returned to {definition.name}."
                            if succeeded
                            else f"{name} failed for {definition.name}."
                        ),
                        event_data_value=tool_execution,
                    )
            if current_task is not None:
                await _publish_task(current_task)

    else:
        if cancel_event.is_set():
            raise AgentTaskCancelled()

        final_prompt = (
            worker_system_prompt
            + "\n\nTOOL LIMIT REACHED\n"
            + "Do not call another tool. Return the best final handoff using "
            + "the information already gathered.\nEND TOOL LIMIT REACHED"
        )
        parts, _ = await _background_model_turn(
            task_id=task_id,
            cancel_event=cancel_event,
            model=model,
            messages=messages,
            system_prompt=final_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=None,
            progress=0.90,
        )

        final_text = "".join(parts).strip()
        coverage_ok, coverage_reason = _source_coverage_status(
            task, successful_source_paths, required_source_reads
        ) if requires_local_source else (True, "not required")
        if requires_local_source and not coverage_ok:
            if readable_workspace_count <= 0:
                final_text = (
                    "UNVERIFIED: no approved readable computer workspace is configured, so I could not "
                    "inspect the requested project source."
                )
            else:
                final_text = (
                    "UNVERIFIED: the tool-step limit was reached before the required source coverage was complete "
                    f"({coverage_reason}). No local implementation claim from this task should be treated as verified."
                )

    coverage_ok, _coverage_reason = _source_coverage_status(
        task, successful_source_paths, required_source_reads
    ) if requires_local_source else (True, "not required")
    if (
        requires_local_source
        and coverage_ok
        and source_evidence_records
    ):
        final_text = await _finalize_source_backed_handoff(
            task_id=task_id,
            cancel_event=cancel_event,
            task=task,
            model=model,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            system_prompt=worker_system_prompt,
            evidence_records=source_evidence_records,
            draft=final_text,
        )

    if not final_text:
        final_text = "The background agent completed without a textual handoff."
    final_text = final_text[: agent_settings.result_max_chars]

    async with SessionLocal() as session:
        current = await get_task(session, task_id)
        if current is None:
            return
        completed_conversation_id = current.conversation_id
        completed_title = current.title
        completed_instruction = current.instruction
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
            event_data_value={
                "used_tools": sorted(set(used_tools)),
                "model": model,
            },
        )
    handoff_message_id = await _persist_completion_handoff(
        task_id=task_id,
        agent_name=definition.name,
        agent_id=definition.id,
        result=final_text,
    )

    # Director child handoffs are intermediate reasoning/evidence, not durable
    # truth. A later specialist may refute them and the Director may ultimately
    # mark them unverified. Never let an intermediate Director branch write to
    # long-term memory. Direct/single-agent tasks keep the normal 11B.3D curation.
    completed_metadata = task_metadata(current)
    if completed_metadata.get("director_managed") is True:
        logger.info(
            "Skipping automatic long-term memory extraction for Director child task %s (%s).",
            task_id,
            definition.name,
        )
    else:
        schedule_agent_memory_extraction(
            conversation_id=completed_conversation_id,
            source_message_id=handoff_message_id,
            agent_name=definition.name,
            task_title=completed_title,
            task_instruction=completed_instruction,
            agent_result=final_text,
            used_tools=sorted(set(used_tools)),
            enabled=memory_auto_extract,
        )

    await _publish_task(
        current,
        event="agent.task.completed",
        handoff_message_id=handoff_message_id,
        result_preview=final_text[:1000],
    )
