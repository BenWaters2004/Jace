from __future__ import annotations

import asyncio
import json
import logging
import re
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


# Local workspace capabilities are treated as a capability class rather than
# project-specific file assumptions. Greenfield design work is intentionally
# isolated from unrelated approved workspaces unless the user explicitly targets
# one. This prevents a new-project design from silently inheriting Jace (or any
# other existing project) just because that workspace happens to be approved.
WORKSPACE_READ_TOOLS = {
    "list_computer_workspaces",
    "list_workspace_files",
    "read_workspace_file",
    "search_workspace_files",
    "workspace_file_info",
    "inspect_workspace_media",
}
WORKSPACE_WRITE_TOOLS = {
    "run_workspace_command",
    "create_workspace_directory",
    "write_workspace_file",
    "replace_workspace_text",
    "move_workspace_path",
    "delete_workspace_file",
}
WORKSPACE_TOOLS = WORKSPACE_READ_TOOLS | WORKSPACE_WRITE_TOOLS


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


def _director_creation_execution(task: AgentTask) -> bool:
    metadata = task_metadata(task)
    return metadata.get("director_creation_execution") is True


def _director_original_request(task: AgentTask) -> str:
    metadata = task_metadata(task)
    return str(metadata.get("original_request") or metadata.get("director_objective") or task.instruction or "").strip()


def _greenfield_needs_prior_context(task: AgentTask) -> bool:
    """Whether a new-project request explicitly asks to carry prior project context forward."""
    text = _director_original_request(task).casefold()
    return bool(re.search(
        r"\b(?:extend|reuse|integrate|continue|adapt|port|migrate|clone|same|previous|existing|current)\b|"
        r"\b(?:based on|from|using) (?:this|that|the previous|our existing|my existing)\b|"
        r"\b(?:this|current) project\b",
        text,
    ))


def _workspace_target_matches(task: AgentTask, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only workspaces the user explicitly targeted for greenfield execution.

    Never infer that an arbitrary approved workspace is the destination for a new
    project. Matching is deliberately conservative: exact workspace id, full root
    path, label, or an explicit "current/this workspace" phrase when exactly one
    workspace exists.
    """
    if not catalog:
        return []
    text = _director_original_request(task).casefold().replace("\\", "/")
    matched: list[dict[str, Any]] = []
    for item in catalog:
        workspace_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        root = str(item.get("root_path") or "").strip().replace("\\", "/")
        if workspace_id and workspace_id.casefold() in text:
            matched.append(item)
            continue
        if root and root.casefold() in text:
            matched.append(item)
            continue
        # Labels are only matched as quoted/named workspace-like references to
        # avoid accidental matches on generic words such as "project".
        if label and len(label) >= 3:
            label_folded = label.casefold()
            patterns = (
                f'workspace {label_folded}',
                f'workspace "{label_folded}"',
                f"workspace '{label_folded}'",
                f'in {label_folded} workspace',
                f'into {label_folded} workspace',
            )
            if any(pattern in text for pattern in patterns):
                matched.append(item)
    if not matched and len(catalog) == 1 and re.search(r"\b(?:this|current)\s+workspace\b", text):
        matched.append(catalog[0])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in matched:
        key = str(item.get("id") or item.get("root_path") or "")
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _director_requires_workspace_context(task: AgentTask) -> bool:
    metadata = task_metadata(task)
    if metadata.get("director_managed") is not True or task.agent_id not in {"code", "files"}:
        return False
    # Greenfield design/planning should work even when no workspace exists.
    # Actual creation may still use an approved workspace when one is available.
    if task.agent_id == "code" and _director_work_mode(task) == "create":
        return _director_creation_execution(task)
    return True


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


def _render_workspace_context(catalog: list[dict[str, Any]]) -> str:
    if not catalog:
        return (
            "APPROVED READABLE WORKSPACES\n"
            "None are available for this task. Do not invent local evidence or assume another approved workspace is the target.\n"
            "END APPROVED READABLE WORKSPACES"
        )
    lines = ["APPROVED READABLE WORKSPACES"]
    for item in catalog:
        lines.append(
            f"- id={item.get('id')} | label={item.get('label')} | root={item.get('root_path')} | "
            f"write_enabled={bool(item.get('write_enabled'))}"
        )
        inventory = item.get("inventory") or []
        if inventory:
            lines.append("  top-level: " + ", ".join(str(value) for value in inventory[:50]))
    lines.extend([
        "Workspace tool paths are ALWAYS relative to the selected workspace root.",
        "For list_workspace_files, begin with path='.' unless a listed relative directory is known to exist.",
        "Never pass the absolute root path as the tool path.",
        "Use the exact workspace id shown above.",
        "END APPROVED READABLE WORKSPACES",
    ])
    return "\n".join(lines)


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
    for workspace in readable:
        catalog.append({
            "id": str(workspace.id),
            "label": str(workspace.label),
            "root_path": str(workspace.root_path),
            "write_enabled": bool(getattr(workspace, "write_enabled", False)),
            "inventory": _safe_workspace_inventory(str(workspace.root_path)),
        })
    return _render_workspace_context(catalog), catalog


def _director_source_rules(workspace_context: str, task: AgentTask) -> str:
    mode = _director_work_mode(task)
    required = _director_required_source_reads(task)
    if mode == "create":
        execution_requested = _director_creation_execution(task)
        return (
            "DIRECTOR GREENFIELD PROJECT RULES\n"
            "This is a new-project/software task. Do not require source files that do not exist yet.\n"
            + (
                "- Actual artifact creation was requested. Use only explicitly authorised write/execute tools, and verify anything you create.\n"
                "- If write tools are unavailable, return a precise implementation/file plan and state that execution still needs authorised write capability.\n"
                if execution_requested
                else
                "- This is a design/planning deliverable. You may answer without a workspace when the user did not ask to integrate with an existing project.\n"
                "- Produce a coherent architecture, file structure, interfaces, data model, dependencies, testing approach, and implementation guidance.\n"
            )
            + "- Never claim a file was created, modified, tested, or executed without successful tool evidence.\n"
            + (f"{workspace_context}\n" if workspace_context else "")
            + "END DIRECTOR GREENFIELD PROJECT RULES"
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



_BOOTSTRAP_STOPWORDS = {
    "about", "after", "again", "agent", "agents", "available", "best", "code",
    "could", "current", "find", "free", "from", "have", "investigate", "jace", "keep", "need", "project",
    "system", "task", "that", "their", "them", "this", "through", "using", "whatever", "when",
    "where", "which", "while", "with", "work", "worked", "working", "would", "your",
}
_BOOTSTRAP_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".php", ".rs", ".go", ".java",
    ".kt", ".kts", ".swift", ".dart", ".rb", ".cs", ".fs", ".fsx", ".cpp", ".c", ".h", ".hpp",
    ".vue", ".svelte", ".sql", ".proto", ".graphql", ".gql", ".sh", ".bash", ".ps1", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".toml", ".yaml", ".yml", ".json", ".xml", ".ini", ".cfg",
    ".conf", ".properties", ".gradle", ".tf", ".hcl", ".md",
}
_BOOTSTRAP_PATH_PENALTIES = (
    "/node_modules/", "/vendor/", "/dist/", "/build/", "/target/", "/coverage/", "/.venv/", "/venv/",
    "/__pycache__/", "/.git/", "/out/", "/generated/",
)


def _source_bootstrap_terms(task: AgentTask, *, limit: int = 6) -> list[str]:
    """Extract project-agnostic search terms from the current objective.

    This deliberately avoids framework/repository assumptions. Exact quoted/backtick
    identifiers are preferred, followed by meaningful words from the user's current
    objective and task title.
    """
    text = f"{_director_original_request(task)}\n{task.title}".strip()
    candidates: list[str] = []
    for match in re.finditer(r"[`\"']([^`\"']{2,80})[`\"']", text):
        value = match.group(1).strip()
        if " " not in value and value.casefold() not in _BOOTSTRAP_STOPWORDS:
            candidates.append(value)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.:-]{2,}", text):
        folded = token.casefold().strip("._:-")
        if len(folded) < 4 or folded in _BOOTSTRAP_STOPWORDS:
            continue
        if folded.isdigit():
            continue
        candidates.append(token.strip(".,:;()[]{}"))

    output: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    return output


def _select_bootstrap_workspaces(task: AgentTask, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select only workspaces that are unambiguous for deterministic bootstrap.

    A sole approved workspace is unambiguous. With multiple workspaces, require the
    objective to identify one by id, root path, or a distinctive label phrase. This
    prevents Jace from silently searching unrelated projects.
    """
    if not catalog:
        return []
    if len(catalog) == 1:
        return [catalog[0]]

    text = _director_original_request(task).casefold().replace("\\", "/")
    generic_labels = {"project", "workspace", "repo", "repository", "code", "app", "application"}
    matched: list[dict[str, Any]] = []
    for item in catalog:
        workspace_id = str(item.get("id") or "").strip()
        root = str(item.get("root_path") or "").strip().replace("\\", "/")
        label = str(item.get("label") or "").strip()
        label_folded = label.casefold()
        if workspace_id and workspace_id.casefold() in text:
            matched.append(item)
            continue
        if root and root.casefold() in text:
            matched.append(item)
            continue
        if label and label_folded not in generic_labels and len(label_folded) >= 3:
            patterns = (
                f"{label_folded} project", f"project {label_folded}",
                f"{label_folded} repo", f"repo {label_folded}",
                f"{label_folded} repository", f"repository {label_folded}",
                f"{label_folded} workspace", f"workspace {label_folded}",
                f'"{label_folded}"', f"'{label_folded}'",
            )
            if any(pattern in text for pattern in patterns):
                matched.append(item)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in matched:
        key = str(item.get("id") or item.get("root_path") or "")
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped if len(deduped) == 1 else []


def _bootstrap_candidate_score(path: str, query: str, result: dict[str, Any]) -> float:
    normalized = "/" + str(path or "").replace("\\", "/").casefold().lstrip("/")
    if any(part in normalized for part in _BOOTSTRAP_PATH_PENALTIES):
        return -1000.0
    name = normalized.rsplit("/", 1)[-1]
    suffix = Path(name).suffix.casefold()
    score = 0.0
    if suffix in _BOOTSTRAP_SOURCE_EXTENSIONS or name in {"dockerfile", "makefile", "procfile", "gemfile", "rakefile"}:
        score += 3.0
    if bool(result.get("path_match")):
        score += 2.0
    if str(result.get("snippet") or "").strip():
        score += 2.0
    folded_query = str(query or "").casefold()
    if folded_query and folded_query in name:
        score += 3.0
    elif folded_query and folded_query in normalized:
        score += 1.0
    if name.endswith((".lock", ".map")) or name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
        score -= 4.0
    return score


def _rank_bootstrap_candidates(search_records: list[dict[str, Any]]) -> list[str]:
    scores: dict[str, float] = {}
    displays: dict[str, str] = {}
    for record in search_records:
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        query = str(evidence.get("query") or "")
        results = evidence.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            path = str(result.get("path") or "").strip()
            if not path:
                continue
            key = path.replace("\\", "/").casefold()
            score = _bootstrap_candidate_score(path, query, result)
            if score <= -900:
                continue
            scores[key] = scores.get(key, 0.0) + score
            displays.setdefault(key, path)
    ranked = sorted(scores, key=lambda key: (-scores[key], displays[key].casefold()))
    return [displays[key] for key in ranked]


async def _record_bootstrap_tool_execution(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    used_tools: list[str],
    progress: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run an audited tool call initiated by Jace's Director evidence bootstrap."""
    used_tools.append(tool_name)
    await _set_state(
        task_id,
        status="using_tool",
        progress=progress,
        message=f"Using {tool_name}",
        event_type="tool_started",
        event_message=f"{agent_name} is using {tool_name} for Director evidence bootstrap.",
        event_data={"tool_name": tool_name, "arguments": arguments, "director_bootstrap": True},
    )
    async with SessionLocal() as session:
        current_task = await get_task(session, task_id)
        if current_task is None:
            raise RuntimeError("Agent task disappeared during evidence bootstrap.")

    tool_message, execution = await _execute_tool(
        task=current_task,
        tool_name=tool_name,
        arguments=arguments,
    )

    async with SessionLocal() as session:
        current_task = await get_task(session, task_id)
        if current_task is not None:
            succeeded = bool(execution.get("success"))
            current_task = await update_task_state(
                session,
                current_task,
                status="thinking",
                progress=min(progress + 0.01, 0.18),
                progress_message="Reviewing bootstrap evidence" if succeeded else "Reviewing bootstrap failure",
                used_tools=used_tools,
                event_type="tool_completed",
                event_message=(
                    f"{tool_name} returned Director bootstrap evidence."
                    if succeeded else f"{tool_name} failed during Director bootstrap."
                ),
                event_data_value={**execution, "director_bootstrap": True},
            )
    if current_task is not None:
        await _publish_task(current_task)
    return tool_message, execution


async def _bootstrap_source_evidence(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    workspace_catalog: list[dict[str, Any]],
    available_tools: set[str],
    used_tools: list[str],
    required_reads: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Deterministically seed an existing-project investigation with real evidence.

    Small local models sometimes repeatedly answer without choosing a workspace tool.
    Jace can safely remove that failure mode by searching an unambiguous approved
    workspace itself, using terms derived from the user's objective, then reading the
    strongest matching files through the same audited tools the worker would use.
    """
    if required_reads <= 0 or "search_workspace_files" not in available_tools or "read_workspace_file" not in available_tools:
        return [], [], set()

    targets = _select_bootstrap_workspaces(task, workspace_catalog)
    if not targets:
        return [], [], set()

    terms = _source_bootstrap_terms(task)
    if not terms:
        return [], [], set()

    search_records: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []
    for workspace in targets:
        workspace_id = str(workspace.get("id") or "")
        if not workspace_id:
            continue
        for index, term in enumerate(terms[:4]):
            arguments = {
                "workspace_id": workspace_id,
                "query": term,
                "path": ".",
                "include_content": True,
                "max_results": 12,
            }
            tool_message, execution = await _record_bootstrap_tool_execution(
                task_id=task_id,
                task=task,
                agent_name=agent_name,
                tool_name="search_workspace_files",
                arguments=arguments,
                used_tools=used_tools,
                progress=min(0.105 + (index * 0.006), 0.14),
            )
            transcript.append(tool_message)
            if execution.get("success") is True:
                search_records.append(execution)

    candidates = _rank_bootstrap_candidates(search_records)
    if not candidates:
        return transcript, [], set()

    read_records: list[dict[str, Any]] = []
    paths: set[str] = set()
    # Read the minimum needed plus one extra candidate when available. The extra
    # evidence gives the worker choice without turning bootstrap into a broad crawl.
    read_budget = min(max(required_reads + 1, 2), 4)
    workspace_id = str(targets[0].get("id") or "")
    for index, path in enumerate(candidates[:read_budget]):
        arguments = {
            "workspace_id": workspace_id,
            "path": path,
            "start_line": 1,
            "max_lines": 400,
        }
        tool_message, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments=arguments,
            used_tools=used_tools,
            progress=min(0.145 + (index * 0.008), 0.18),
        )
        transcript.append(tool_message)
        if execution.get("success") is not True:
            continue
        evidence = execution.get("evidence")
        if not isinstance(evidence, dict):
            continue
        try:
            returned_lines = int(evidence.get("returned_lines") or 0)
        except (TypeError, ValueError):
            returned_lines = 0
        source_path = str(evidence.get("path") or "").strip()
        if returned_lines <= 0 or not source_path or not str(evidence.get("text") or "").strip():
            continue
        normalized = source_path.replace("\\", "/").casefold()
        if normalized in paths:
            continue
        paths.add(normalized)
        read_records.append(execution)

    return transcript, read_records, paths


async def _bootstrap_named_followup_evidence(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    workspace_catalog: list[dict[str, Any]],
    available_tools: set[str],
    used_tools: list[str],
    artifacts: list[str],
    already_read: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Resolve concrete missing-artifact references from a source-backed draft.

    The worker may correctly conclude that another file is needed but then fail to
    issue the next tool call. When the draft names a candidate artifact, Jace can
    safely attempt that read through the same approved/audited workspace boundary.
    """
    if not artifacts or "read_workspace_file" not in available_tools:
        return [], set()
    targets = _select_bootstrap_workspaces(task, workspace_catalog)
    if not targets:
        return [], set()
    workspace_id = str(targets[0].get("id") or "")
    if not workspace_id:
        return [], set()

    records: list[dict[str, Any]] = []
    new_paths: set[str] = set()
    for index, raw in enumerate(artifacts[:4]):
        candidate = str(raw or "").strip().strip("`'\"").replace("\\", "/")
        if not candidate:
            continue
        normalized = candidate.casefold().lstrip("./")
        if normalized in already_read or any(path.endswith("/" + normalized) for path in already_read):
            continue

        direct_args = {
            "workspace_id": workspace_id,
            "path": candidate,
            "start_line": 1,
            "max_lines": 500,
        }
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments=direct_args,
            used_tools=used_tools,
            progress=min(0.80 + index * 0.01, 0.86),
        )
        successful = execution.get("success") is True
        if not successful and "search_workspace_files" in available_tools:
            basename = Path(candidate).name
            if basename:
                _, search_execution = await _record_bootstrap_tool_execution(
                    task_id=task_id,
                    task=task,
                    agent_name=agent_name,
                    tool_name="search_workspace_files",
                    arguments={
                        "workspace_id": workspace_id,
                        "query": basename,
                        "path": ".",
                        "include_content": False,
                        "max_results": 10,
                    },
                    used_tools=used_tools,
                    progress=min(0.805 + index * 0.01, 0.87),
                )
                ranked = _rank_bootstrap_candidates([search_execution]) if search_execution.get("success") is True else []
                if ranked:
                    _, execution = await _record_bootstrap_tool_execution(
                        task_id=task_id,
                        task=task,
                        agent_name=agent_name,
                        tool_name="read_workspace_file",
                        arguments={
                            "workspace_id": workspace_id,
                            "path": ranked[0],
                            "start_line": 1,
                            "max_lines": 500,
                        },
                        used_tools=used_tools,
                        progress=min(0.81 + index * 0.01, 0.88),
                    )
                    successful = execution.get("success") is True
        if not successful:
            continue
        evidence = execution.get("evidence")
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        try:
            returned_lines = int(evidence.get("returned_lines") or 0)
        except (TypeError, ValueError):
            returned_lines = 0
        if not path or returned_lines <= 0 or not str(evidence.get("text") or "").strip():
            continue
        key = path.replace("\\", "/").casefold()
        if key in already_read or key in new_paths:
            continue
        new_paths.add(key)
        records.append(execution)
    return records, new_paths


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


def _repair_tool_arguments_to_schema(
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Apply only lossless/safe repairs implied by the registered tool schema.

    Small local models sometimes request a numeric limit outside the schema even
    when the schema states the bound. Clamping such values is safer and more
    general than hard-coding fixes for individual tools.
    """
    tool = registry.get(tool_name)
    if tool is None:
        return dict(arguments), []
    try:
        schema = tool.input_model.model_json_schema()
    except Exception:
        return dict(arguments), []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return dict(arguments), []

    fixed = dict(arguments)
    notes: list[str] = []
    for key, value in list(fixed.items()):
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        candidates = [spec]
        for branch_key in ("anyOf", "oneOf"):
            branches = spec.get(branch_key)
            if isinstance(branches, list):
                candidates.extend(branch for branch in branches if isinstance(branch, dict))

        numeric_spec = next(
            (candidate for candidate in candidates if candidate.get("type") in {"integer", "number"}),
            None,
        )
        if numeric_spec is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            repaired = value
            minimum = numeric_spec.get("minimum")
            maximum = numeric_spec.get("maximum")
            exclusive_min = numeric_spec.get("exclusiveMinimum")
            exclusive_max = numeric_spec.get("exclusiveMaximum")
            if isinstance(minimum, (int, float)) and repaired < minimum:
                repaired = minimum
            if isinstance(maximum, (int, float)) and repaired > maximum:
                repaired = maximum
            if isinstance(exclusive_min, (int, float)) and repaired <= exclusive_min:
                repaired = exclusive_min + (1 if numeric_spec.get("type") == "integer" else 1e-9)
            if isinstance(exclusive_max, (int, float)) and repaired >= exclusive_max:
                repaired = exclusive_max - (1 if numeric_spec.get("type") == "integer" else 1e-9)
            if numeric_spec.get("type") == "integer":
                repaired = int(repaired)
            if repaired != value:
                fixed[key] = repaired
                notes.append(f"clamped {key} from {value!r} to schema-valid {repaired!r}")
            continue

        array_spec = next((candidate for candidate in candidates if candidate.get("type") == "array"), None)
        if array_spec is not None and isinstance(value, list):
            max_items = array_spec.get("maxItems")
            if isinstance(max_items, int) and len(value) > max_items:
                fixed[key] = value[:max_items]
                notes.append(f"trimmed {key} to schema maxItems={max_items}")

    return fixed, notes


_MISSING_EVIDENCE_RE = re.compile(
    r"\b(?:missing evidence|need(?:s|ed)? to inspect|still need(?:s)? to inspect|requires? inspection|"
    r"cannot (?:confirm|verify|determine|conclude) without|additional (?:file|artifact|component|evidence).*?(?:inspect|read)|"
    r"evidence (?:is|remains) incomplete)\b",
    re.IGNORECASE | re.DOTALL,
)
_ARTIFACT_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z0-9_. -]+(?:[/\\][A-Za-z0-9_. -]+)+\.[A-Za-z0-9]{1,12}|"
    r"[A-Za-z0-9_.-]+\.(?:py|pyi|ts|tsx|js|jsx|php|rs|go|java|kt|kts|swift|dart|rb|vue|svelte|"
    r"json|toml|ya?ml|xml|sql|md|html?|css|scss|sass|less|sh|bash|ps1|cs|fs|fsx|cpp|c|h|hpp|"
    r"gradle|properties|ini|cfg|conf|tf|hcl|proto|graphql|gql))",
    re.IGNORECASE,
)


def _draft_declares_missing_evidence(text: str) -> bool:
    return bool(_MISSING_EVIDENCE_RE.search(text or ""))


def _unread_artifacts_named_in_draft(text: str, source_paths: set[str]) -> list[str]:
    read = {path.replace("\\", "/").casefold() for path in source_paths}
    basenames = {path.split("/")[-1] for path in read}
    candidates: list[str] = []
    for match in _ARTIFACT_PATH_RE.finditer(text or ""):
        raw = match.group(1).strip("`'\".,;:()[]{} ")
        normal = raw.replace("\\", "/").casefold()
        base = normal.split("/")[-1]
        if normal in read or base in basenames:
            continue
        if raw not in candidates:
            candidates.append(raw)
        if len(candidates) >= 8:
            break
    return candidates


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

    requires_workspace_context = _director_requires_workspace_context(task)
    requires_local_source = _director_requires_local_source(task)
    workspace_context = ""
    workspace_catalog: list[dict[str, Any]] = []
    readable_workspace_count = 0
    worker_system_prompt = definition.system_prompt
    mode = _director_work_mode(task)

    # Greenfield design is isolated from unrelated existing projects. An approved
    # workspace is not automatically relevant just because it exists. For actual
    # greenfield execution, only an explicitly targeted workspace is exposed.
    if task.agent_id == "code" and mode == "create":
        if not _director_creation_execution(task):
            tool_names = [name for name in tool_names if name not in WORKSPACE_TOOLS]
            worker_system_prompt = (
                definition.system_prompt
                + "\n\n"
                + _director_source_rules("", task)
                + "\nGREENFIELD ISOLATION: No existing local workspace is part of this design task. "
                  "Do not claim integration with, reuse from, or changes to an existing project unless the user explicitly requested that. "
                  "Describe all files/dependencies as proposed artifacts, not existing or verified files."
            )
            logger.info(
                "Director-managed Code Agent task %s is isolated greenfield design; local workspace tools hidden.",
                task_id,
            )
        else:
            all_context, all_catalog = await _readable_workspace_context()
            del all_context
            workspace_catalog = _workspace_target_matches(task, all_catalog)
            readable_workspace_count = len(workspace_catalog)
            if workspace_catalog:
                workspace_context = _render_workspace_context(workspace_catalog)
                worker_system_prompt = (
                    definition.system_prompt
                    + "\n\n"
                    + _director_source_rules(workspace_context, task)
                )
            else:
                tool_names = [name for name in tool_names if name not in WORKSPACE_TOOLS]
                worker_system_prompt = (
                    definition.system_prompt
                    + "\n\n"
                    + _director_source_rules("", task)
                    + "\nGREENFIELD TARGET REQUIRED: The user asked for actual creation, but did not explicitly identify an approved target workspace. "
                      "Prepare the complete implementation/file set, but do not inspect or modify an unrelated workspace. "
                      "State that execution requires an explicitly selected approved target workspace."
                )
            logger.info(
                "Director-managed Code Agent task %s greenfield execution matched %d explicit target workspace(s).",
                task_id,
                readable_workspace_count,
            )
    elif requires_workspace_context:
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
            mode,
        )

    tool_schemas = registry.schemas(set(tool_names)) if tool_names else []

    context_messages = await _conversation_context(task)
    if task.agent_id == "code" and mode == "create" and not _greenfield_needs_prior_context(task):
        context_messages = []
        logger.info(
            "Director-managed Code Agent task %s is greenfield-isolated from prior conversation project context.",
            task_id,
        )
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
    max_evidence_nudges = 6 if requires_local_source else 0
    source_finalized = False
    if requires_local_source:
        logger.info(
            "Director-managed %s task %s requires %d DISTINCT relevant source read(s) using project-discovered paths.",
            definition.name,
            task_id,
            required_source_reads,
        )

        _bootstrap_transcript, bootstrap_records, bootstrap_paths = await _bootstrap_source_evidence(
            task_id=task_id,
            task=task,
            agent_name=definition.name,
            workspace_catalog=workspace_catalog,
            available_tools=set(tool_names),
            used_tools=used_tools,
            required_reads=required_source_reads,
        )
        del _bootstrap_transcript
        if bootstrap_records:
            source_evidence_records.extend(bootstrap_records)
            successful_source_paths.update(bootstrap_paths)
            successful_source_reads = len(successful_source_paths)
            dossier = _source_evidence_dossier(bootstrap_records)
            messages.append({
                "role": "user",
                "content": (
                    "DIRECTOR EVIDENCE BOOTSTRAP\n"
                    "Jace has already performed an audited search of the unambiguous approved project workspace and read the following candidate evidence before your first reasoning turn. "
                    "Use it as a starting point, verify relevance, and continue with tools if the requested conclusion still needs other artifacts.\n\n"
                    f"{dossier}\n"
                    "END DIRECTOR EVIDENCE BOOTSTRAP"
                ),
            })
            logger.info(
                "Director-managed %s task %s deterministically bootstrapped %d distinct source read(s): %s",
                definition.name,
                task_id,
                successful_source_reads,
                ", ".join(sorted(successful_source_paths)),
            )
        elif readable_workspace_count > 0:
            logger.info(
                "Director-managed %s task %s deterministic source bootstrap found no readable candidate source; worker will continue with normal discovery tools.",
                definition.name,
                task_id,
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

            candidate_text = proposed_text
            if requires_local_source and coverage_ok and source_evidence_records:
                candidate_text = await _finalize_source_backed_handoff(
                    task_id=task_id,
                    cancel_event=cancel_event,
                    task=task,
                    model=model,
                    reasoning_mode=reasoning_mode,
                    temperature=temperature,
                    system_prompt=worker_system_prompt,
                    evidence_records=source_evidence_records,
                    draft=proposed_text,
                )

            if (
                requires_local_source
                and coverage_ok
                and _draft_declares_missing_evidence(candidate_text)
                and evidence_nudges < max_evidence_nudges
            ):
                # The source-backed finalisation pass may discover a gap that the
                # original draft missed. Put that conclusion back into the worker
                # transcript before asking for more tools so the next turn can
                # continue from its own evidence-backed diagnosis.
                if candidate_text and candidate_text != proposed_text:
                    messages.append({"role": "assistant", "content": candidate_text})
                evidence_nudges += 1
                unread = _unread_artifacts_named_in_draft(candidate_text, successful_source_paths)
                follow_records, follow_paths = await _bootstrap_named_followup_evidence(
                    task_id=task_id,
                    task=task,
                    agent_name=definition.name,
                    workspace_catalog=workspace_catalog,
                    available_tools=set(tool_names),
                    used_tools=used_tools,
                    artifacts=unread,
                    already_read=successful_source_paths,
                )
                if follow_records:
                    source_evidence_records.extend(follow_records)
                    successful_source_paths.update(follow_paths)
                    successful_source_reads = len(successful_source_paths)
                    messages.append({
                        "role": "user",
                        "content": (
                            "DIRECTOR FOLLOW-UP EVIDENCE\n"
                            "Your previous source-backed draft correctly identified missing evidence. Jace resolved the named approved-workspace artifact(s) through audited workspace tools. "
                            "Reassess the objective using this additional evidence before deciding whether anything else is needed.\n\n"
                            f"{_source_evidence_dossier(follow_records)}\n"
                            "END DIRECTOR FOLLOW-UP EVIDENCE"
                        ),
                    })
                    logger.info(
                        "Director-managed %s task %s deterministically followed missing evidence into %d additional source file(s): %s",
                        definition.name,
                        task_id,
                        len(follow_paths),
                        ", ".join(sorted(follow_paths)),
                    )
                    continue

                targeted = (
                    " The source-backed draft named these unread candidate artifacts: " + ", ".join(unread) + "."
                    if unread
                    else ""
                )
                messages.append({
                    "role": "user",
                    "content": (
                        "YOUR SOURCE-BACKED DRAFT SAYS THE EVIDENCE IS STILL INCOMPLETE. Do not finalize yet."
                        + targeted
                        + " Continue the investigation using the approved project workspace. Inspect the additional artifact/component needed to resolve the uncertainty. "
                        "If a named path is only a guess or inaccessible, search for the relevant symbol, caller/callee, configuration, test, log-producing code, or integration point. "
                        "Do not reread already-counted files merely to consume a turn. Only finalize once the requested conclusion is supported, "
                        "or once you have made a reasonable bounded attempt and can precisely explain what evidence is genuinely unavailable."
                    ),
                })
                logger.info(
                    "Director-managed %s task %s source-backed handoff still identified missing evidence; continuing investigation (%d/%d).",
                    definition.name,
                    task_id,
                    evidence_nudges,
                    max_evidence_nudges,
                )
                continue

            final_text = candidate_text
            source_finalized = bool(requires_local_source and coverage_ok and source_evidence_records)
            break

        for call in calls:
            if cancel_event.is_set():
                raise AgentTaskCancelled()
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            repair_notes: list[str] = []
            if requires_workspace_context:
                arguments, workspace_repair_notes = _repair_workspace_tool_arguments(
                    name, arguments, workspace_catalog
                )
                repair_notes.extend(workspace_repair_notes)
            arguments, schema_repair_notes = _repair_tool_arguments_to_schema(name, arguments)
            repair_notes.extend(schema_repair_notes)
            if repair_notes:
                logger.info(
                    "Agent task %s repaired %s arguments: %s",
                    task_id,
                    name,
                    "; ".join(repair_notes),
                )
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
        and not source_finalized
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
