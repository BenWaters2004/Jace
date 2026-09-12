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
from jace.tools.approvals import approval_manager
# Phase 1D background tool approval uses the same queue as foreground Jace.

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
    # Generic task/action verbs are not implementation evidence. Keeping them out
    # of the semantic term set prevents unrelated source from becoming "relevant"
    # merely because it contains words such as inspect/review/analyse.
    "inspect", "inspection", "review", "reviewing", "analyse", "analyze", "analysis",
    "determine", "establish", "recommend", "recommendation", "verify", "verification",
    "diagnose", "diagnosis", "resolve", "resolution", "understand", "identify",
    "explain", "explanation", "assess", "assessment",
}
_BOOTSTRAP_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".php", ".rs", ".go", ".java",
    ".kt", ".kts", ".swift", ".dart", ".rb", ".cs", ".fs", ".fsx", ".cpp", ".c", ".h", ".hpp",
    ".vue", ".svelte", ".sql", ".proto", ".graphql", ".gql", ".sh", ".bash", ".ps1", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".toml", ".yaml", ".yml", ".json", ".xml", ".ini", ".cfg",
    ".conf", ".properties", ".gradle", ".tf", ".hcl", ".md",
}
_BOOTSTRAP_LOGIC_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".php", ".rs", ".go", ".java",
    ".kt", ".kts", ".swift", ".dart", ".rb", ".cs", ".fs", ".fsx", ".cpp", ".c", ".h", ".hpp",
    ".vue", ".svelte", ".sh", ".bash", ".ps1", ".proto", ".graphql", ".gql",
}
_BOOTSTRAP_PRESENTATION_EXTENSIONS = {".css", ".scss", ".sass", ".less", ".html", ".htm"}
_BOOTSTRAP_CONFIG_EXTENSIONS = {
    ".toml", ".yaml", ".yml", ".json", ".xml", ".ini", ".cfg", ".conf", ".properties", ".gradle", ".tf", ".hcl",
}
_BOOTSTRAP_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
_BOOTSTRAP_DATA_EXTENSIONS = {".sql", ".csv", ".tsv", ".graphql", ".gql"}
_BOOTSTRAP_PATH_PENALTIES = (
    "/node_modules/", "/vendor/", "/dist/", "/build/", "/target/", "/coverage/", "/.venv/", "/venv/",
    "/__pycache__/", "/.git/", "/out/", "/generated/",
)
_BOOTSTRAP_LOW_SIGNAL_TERMS = {
    "background", "complete", "completed", "completion", "error", "errors", "fail", "failed", "failure",
    "fix", "issue", "issues", "miss", "missed", "missing", "problem", "problems", "result", "results",
    "return", "returned", "update", "updated",
}
_BOOTSTRAP_STYLE_TERMS = {
    "style", "styles", "css", "scss", "sass", "theme", "layout", "colour", "color", "font", "animation",
    "visual", "ui", "ux", "stylesheet", "responsive", "spacing", "pixel",
}
_BOOTSTRAP_CONFIG_TERMS = {
    "config", "configuration", "settings", "environment", "env", "dependency", "dependencies", "package",
    "requirements", "docker", "deploy", "deployment", "build", "pipeline", "ci", "version",
}
_BOOTSTRAP_DOC_TERMS = {"documentation", "docs", "readme", "manual", "guide", "instructions", "specification"}
_BOOTSTRAP_DATA_TERMS = {"database", "sql", "schema", "migration", "query", "table", "tables", "orm", "data"}
_BOOTSTRAP_CODE_SIGNAL_RE = re.compile(
    r"\b(?:async|await|class|def|function|return|if|else|elif|switch|match|try|catch|except|finally|"
    r"publish|emit|dispatch|subscribe|listener|handler|callback|queue|persist|save|insert|update|delete|"
    r"route|endpoint|request|response|status|message|event|result)\b|=>|::|\buseEffect\s*\(",
    re.IGNORECASE,
)


def _source_bootstrap_terms(task: AgentTask, *, limit: int = 10) -> list[str]:
    """Extract project-agnostic search terms from the current objective."""
    text = f"{_director_original_request(task)}\n{task.title}".strip()
    candidates: list[str] = []
    for match in re.finditer(r"[`\"']([^`\"']{2,80})[`\"']", text):
        value = match.group(1).strip()
        if " " not in value and value.casefold() not in _BOOTSTRAP_STOPWORDS:
            candidates.append(value)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.:-]{2,}", text):
        folded = token.casefold().strip("._:-")
        if len(folded) < 4 or folded in _BOOTSTRAP_STOPWORDS or folded.isdigit():
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


def _objective_evidence_affinities(task: AgentTask) -> set[str]:
    text = _director_original_request(task).casefold()
    words = set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))
    affinities: set[str] = set()
    if words & _BOOTSTRAP_STYLE_TERMS:
        affinities.add("presentation")
    if words & _BOOTSTRAP_CONFIG_TERMS:
        affinities.add("config")
    if words & _BOOTSTRAP_DOC_TERMS:
        affinities.add("docs")
    if words & _BOOTSTRAP_DATA_TERMS:
        affinities.add("data")
    if words & {"test", "tests", "testing", "regression", "pytest", "jest", "vitest", "spec", "specs"}:
        affinities.add("test")
    if words & {"script", "scripts", "installer", "install", "migration", "migrate", "smoke", "bootstrap"}:
        affinities.add("script")
    return affinities


def _bootstrap_path_kind(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    suffix = Path(name).suffix.casefold()
    padded = f"/{normalized}/"
    if (
        "/test/" in padded
        or "/tests/" in padded
        or name.startswith("test_")
        or name.startswith("test-")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if "/scripts/" in padded or "/script/" in padded:
        return "script"
    if suffix in _BOOTSTRAP_PRESENTATION_EXTENSIONS:
        return "presentation"
    if suffix in _BOOTSTRAP_CONFIG_EXTENSIONS or name in {
        "dockerfile", "makefile", "procfile", "gemfile", "rakefile", "requirements.txt", "package.json", "pyproject.toml",
    }:
        return "config"
    if suffix in _BOOTSTRAP_DOC_EXTENSIONS or name.startswith("readme"):
        return "docs"
    if suffix in _BOOTSTRAP_DATA_EXTENSIONS:
        return "data"
    if suffix in _BOOTSTRAP_LOGIC_EXTENSIONS:
        return "logic"
    return "other"


def _objective_term_hits(task: AgentTask, path: str, text: str) -> tuple[set[str], set[str]]:
    haystack = f"{path}\n{text}".casefold()
    hits: set[str] = set()
    high_signal: set[str] = set()
    for raw in _source_bootstrap_terms(task, limit=12):
        term = raw.casefold().strip("._:-")
        if len(term) < 3 or term not in haystack:
            continue
        hits.add(term)
        if term not in _BOOTSTRAP_LOW_SIGNAL_TERMS:
            high_signal.add(term)
    return hits, high_signal


def _discovery_signal(execution: dict[str, Any]) -> tuple[set[str], list[int], list[str], float, bool, bool]:
    """Return objective-derived discovery evidence attached to a source read.

    Search results are evidence too: a source file may contain the matching symbol
    hundreds of lines below its first page.  Preserve the queries/line anchors that
    caused Jace to choose the file so relevance is not judged only from line 1.
    """
    raw = execution.get("discovery_evidence")
    if not isinstance(raw, dict):
        return set(), [], [], 0.0, False, False
    queries = {
        str(value).casefold().strip("._:-")
        for value in (raw.get("queries") or [])
        if str(value or "").strip()
    }
    lines: list[int] = []
    for value in raw.get("lines") or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            lines.append(number)
    snippets = [str(value)[:500] for value in (raw.get("snippets") or []) if str(value or "").strip()]
    try:
        candidate_score = float(raw.get("candidate_score") or 0.0)
    except (TypeError, ValueError):
        candidate_score = 0.0
    return queries, lines, snippets, candidate_score, bool(raw.get("named_followup")), bool(raw.get("structural_followup"))


def _source_read_relevance(task: AgentTask, execution: dict[str, Any]) -> tuple[bool, float, str]:
    """Return whether a real source read is relevant enough to satisfy coverage.

    Relevance is structural rather than filename-specific.  A read may qualify when
    the excerpt itself contains objective concepts *or* when an audited workspace
    search found the file for those concepts and the anchored excerpt contains real
    implementation structure.  This avoids both false positives from cosmetic files
    and false negatives when the matching symbol lives deep in a large source file.
    """
    evidence = execution.get("evidence")
    if execution.get("success") is not True or not isinstance(evidence, dict):
        return False, 0.0, "read did not succeed"
    path = str(evidence.get("path") or "").strip()
    text = str(evidence.get("text") or "")
    try:
        returned_lines = int(evidence.get("returned_lines") or 0)
    except (TypeError, ValueError):
        returned_lines = 0
    if not path or returned_lines <= 0 or not text.strip():
        return False, 0.0, "read returned no usable text"

    original = _director_original_request(task).replace("\\", "/").casefold()
    normalized_path = path.replace("\\", "/").casefold()
    basename = normalized_path.rsplit("/", 1)[-1]
    if normalized_path in original or basename in original:
        return True, 100.0, "the user explicitly named this artifact"

    kind = _bootstrap_path_kind(path)
    affinities = _objective_evidence_affinities(task)
    hits, high_signal_hits = _objective_term_hits(task, path, text)
    discovery_queries, discovery_lines, discovery_snippets, discovery_score, named_followup, structural_followup = _discovery_signal(execution)
    objective_terms = {
        term.casefold().strip("._:-")
        for term in _source_bootstrap_terms(task, limit=12)
        if term.casefold().strip("._:-")
    }
    distinctive_objective_terms = {term for term in objective_terms if term not in _BOOTSTRAP_LOW_SIGNAL_TERMS}
    discovery_objective_hits = discovery_queries & objective_terms
    discovery_distinctive_hits = discovery_queries & distinctive_objective_terms
    discovery_low_signal_hits = discovery_queries & _BOOTSTRAP_LOW_SIGNAL_TERMS

    score = 0.0
    if kind == "logic":
        score += 4.0
    elif kind == "test":
        score += 4.0 if "test" in affinities else -4.0
    elif kind == "script":
        score += 4.0 if "script" in affinities else -3.0
    elif kind == "presentation":
        score += 4.0 if "presentation" in affinities else -1.5
    elif kind == "config":
        score += 4.0 if "config" in affinities else 0.5
    elif kind == "docs":
        score += 4.0 if "docs" in affinities else -1.0
    elif kind == "data":
        score += 4.0 if "data" in affinities else 1.0

    for term in hits:
        score += 0.75 if term in _BOOTSTRAP_LOW_SIGNAL_TERMS else 1.75
        if term in basename:
            score += 0.5

    has_code_structure = bool(_BOOTSTRAP_CODE_SIGNAL_RE.search(text))
    if has_code_structure and kind in {"logic", "other"}:
        score += 2.0
    elif has_code_structure and kind == "test" and "test" in affinities:
        score += 2.0
    elif has_code_structure and kind == "script" and "script" in affinities:
        score += 1.5

    # An audited search hit is structural evidence about why the file was selected.
    # High-signal objective queries are strongest, but several lifecycle/error terms
    # plus actual code structure can also justify a file that uses different naming.
    if discovery_distinctive_hits:
        score += 3.25 + min(2.0, 0.75 * (len(discovery_distinctive_hits) - 1))
    if discovery_low_signal_hits:
        score += min(2.25, 0.75 * len(discovery_low_signal_hits))
    if discovery_snippets and any(_BOOTSTRAP_CODE_SIGNAL_RE.search(snippet) for snippet in discovery_snippets):
        score += 1.5
    if discovery_lines:
        score += 0.5
    if named_followup:
        score += 2.0
    if structural_followup:
        score += 2.5
    if discovery_score > 0:
        score += min(1.5, discovery_score / 12.0)

    if kind in {"logic", "test", "script"}:
        if kind == "test" and "test" not in affinities:
            return False, score, f"test evidence is supporting-only for this non-test objective; score={score:.2f}"
        if kind == "script" and "script" not in affinities:
            return False, score, f"script/tooling evidence is supporting-only for this runtime objective; score={score:.2f}"
        direct_semantic_match = bool(high_signal_hits)
        anchored_semantic_match = bool(discovery_distinctive_hits) or (
            len(discovery_low_signal_hits) >= 2 and has_code_structure
        )
        followup_structural_match = (named_followup or structural_followup) and has_code_structure
        relevant = score >= 6.0 and (direct_semantic_match or anchored_semantic_match or followup_structural_match)
        reason_bits: list[str] = []
        if high_signal_hits:
            reason_bits.append(f"direct={sorted(high_signal_hits)}")
        if discovery_objective_hits:
            reason_bits.append(f"search={sorted(discovery_objective_hits)}")
        if discovery_lines:
            reason_bits.append(f"anchors={discovery_lines[:4]}")
        if named_followup:
            reason_bits.append("named-followup")
        if structural_followup:
            reason_bits.append("structural-followup")
        if not reason_bits:
            reason_bits.append("no objective/search anchor")
        return relevant, score, f"{kind} structural relevance score={score:.2f}; " + "; ".join(reason_bits)

    if kind in affinities:
        return score >= 4.0, score, f"objective-targeted {kind} evidence score={score:.2f}"
    return score >= 6.5 and bool(high_signal_hits or discovery_distinctive_hits), score, (
        f"supporting {kind} evidence score={score:.2f}; direct={sorted(high_signal_hits)}; "
        f"search={sorted(discovery_objective_hits)}"
    )


def _source_record_path(record: dict[str, Any]) -> str:
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get("path") or "").strip()


def _source_record_focus_score(
    record: dict[str, Any],
    *,
    task: AgentTask | None,
    draft: str,
    index: int,
) -> tuple[float, str]:
    """Rank source evidence by semantic/provenance strength rather than recency."""
    path = _source_record_path(record)
    if not path:
        return -999.0, "missing-path"
    relevance = record.get("source_relevance")
    relevance_score = 0.0
    reason = ""
    if isinstance(relevance, dict):
        try:
            relevance_score = float(relevance.get("score") or 0.0)
        except (TypeError, ValueError):
            relevance_score = 0.0
        reason = str(relevance.get("reason") or "")
    raw_discovery = record.get("discovery_evidence")
    discovery = raw_discovery if isinstance(raw_discovery, dict) else {}
    named = bool(discovery.get("named_followup"))
    cross = bool(discovery.get("cross_reference_followup"))
    gap = bool(discovery.get("gap_followup"))
    structural = bool(discovery.get("structural_followup"))
    queries = {
        str(v).casefold().strip("._:-")
        for v in (discovery.get("queries") or [])
        if str(v or "").strip()
    }
    score = relevance_score
    folded_reason = reason.casefold()
    if "direct=" in folded_reason:
        score += 14.0
    if "search=" in folded_reason:
        score += 7.0
    if named:
        score += 15.0
    if cross:
        score += 7.0
    elif structural:
        score += 3.0
    if gap:
        score -= 2.5
    kind = _bootstrap_path_kind(path)
    affinities = _objective_evidence_affinities(task) if task is not None else set()
    if kind == "logic":
        score += 3.0
    elif kind == "test" and "test" not in affinities:
        score -= 18.0
    elif kind == "script" and "script" not in affinities:
        score -= 14.0
    if task is not None:
        objective_terms = {
            term.casefold().strip("._:-")
            for term in _source_bootstrap_terms(task, limit=12)
            if term.casefold().strip("._:-")
        }
        distinctive = objective_terms - _BOOTSTRAP_LOW_SIGNAL_TERMS
        if queries & distinctive:
            score += 9.0
        elif queries & objective_terms:
            score += 3.0
    if draft:
        normalized = path.replace("\\", "/").casefold().lstrip("./")
        concrete, _ = _artifact_references_in_draft(draft, set(), include_already_read=True)
        draft_paths = {v.replace("\\", "/").casefold().lstrip("./") for v in concrete}
        draft_bases = {v.split("/")[-1] for v in draft_paths}
        if normalized in draft_paths or normalized.split("/")[-1] in draft_bases:
            score += 8.0

        gap_text = _missing_evidence_excerpt(draft)
        if gap_text:
            gap_concrete, _ = _artifact_references_in_draft(
                gap_text, set(), include_already_read=True
            )
            gap_paths = {v.replace("\\", "/").casefold().lstrip("./") for v in gap_concrete}
            gap_bases = {v.split("/")[-1] for v in gap_paths}
            if normalized in gap_paths or normalized.split("/")[-1] in gap_bases:
                # A source-backed draft asking for a file Jace already read is a
                # contradiction to reconcile, not a reason to expand elsewhere.
                score += 28.0
    score += min(index, 1000) * 0.001
    return score, reason or "no-relevance-reason"


def _focused_source_records(
    records: list[dict[str, Any]],
    *,
    task: AgentTask | None,
    draft: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Choose a compact, provenance-diverse set of the strongest source records."""
    unique: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        path = _source_record_path(record)
        evidence = record.get("evidence")
        text = str(evidence.get("text") or "").strip() if isinstance(evidence, dict) else ""
        if not path or not text:
            continue
        key = path.replace("\\", "/").casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append((index, record))
    ranked = sorted(
        unique,
        key=lambda item: (-_source_record_focus_score(item[1], task=task, draft=draft, index=item[0])[0], item[0]),
    )
    selected: list[dict[str, Any]] = []
    keys: set[str] = set()
    def add(record: dict[str, Any]) -> None:
        if len(selected) >= limit:
            return
        path = _source_record_path(record)
        key = path.replace("\\", "/").casefold()
        if path and key not in keys:
            keys.add(key); selected.append(record)
    buckets: list[list[dict[str, Any]]] = [[], [], [], []]
    for _, record in ranked:
        discovery = record.get("discovery_evidence")
        d = discovery if isinstance(discovery, dict) else {}
        relevance = record.get("source_relevance")
        reason = str(relevance.get("reason") or "").casefold() if isinstance(relevance, dict) else ""
        if bool(d.get("named_followup")):
            buckets[1].append(record)
        elif "direct=" in reason or (not d.get("structural_followup") and not d.get("gap_followup")):
            buckets[0].append(record)
        elif bool(d.get("cross_reference_followup")) or bool(d.get("structural_followup")):
            buckets[2].append(record)
        else:
            buckets[3].append(record)

    # Reconciliation comes first. If the unresolved handoff explicitly asks for
    # runner.py/director.py/etc. and those artifacts are already in the successful
    # read ledger, force up to two of them into the focused dossier. This prevents
    # later cross-reference noise from evicting the exact evidence the model says
    # it still needs.
    gap_text = _missing_evidence_excerpt(draft) if draft else ""
    if gap_text:
        gap_refs, _ = _artifact_references_in_draft(
            gap_text, set(), include_already_read=True
        )
        gap_norm = {v.replace("\\", "/").casefold().lstrip("./") for v in gap_refs}
        gap_bases = {v.split("/")[-1] for v in gap_norm}
        reconciled = 0
        for _, record in ranked:
            path = _source_record_path(record)
            normal = path.replace("\\", "/").casefold().lstrip("./")
            if normal in gap_norm or normal.split("/")[-1] in gap_bases:
                add(record)
                reconciled += 1
                if reconciled >= 2 or len(selected) >= limit:
                    break

    # Keep one strongest objective-anchored seed, then prefer the connected
    # implementation graph. This prevents three near-duplicate UI/bootstrap
    # files from crowding execution/persistence/consumer evidence out of a
    # five-file dossier. A second direct seed is added afterwards if space
    # remains.
    for record in buckets[0][:1]: add(record)
    for record in buckets[1][:1]: add(record)
    for record in buckets[2][:3]: add(record)
    for record in buckets[0][1:2]: add(record)
    for _, record in ranked:
        add(record)
        if len(selected) >= limit: break
    return selected



def _targeted_source_excerpt(
    record: dict[str, Any],
    *,
    task: AgentTask | None,
    draft: str,
    max_chars: int = 2800,
) -> str:
    """Render line-numbered windows around the evidence that matters.

    A successful workspace read can contain hundreds of lines. Older finalisers
    kept only ``text[:2250]``, which meant the model often saw imports and type
    guards but not a later handler in the *same already-read file*. Select up to
    three separated windows using audited search anchors, objective terms and
    exact symbols/event keys mentioned by the specialist draft. When the draft
    explicitly says an excerpt was cut/truncated, bias one window to the tail of
    the captured read as well.
    """
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    text = str(evidence.get("text") or "")
    if not text.strip():
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    try:
        start_line = max(1, int(evidence.get("start_line") or 1))
    except (TypeError, ValueError):
        start_line = 1
    discovery_raw = record.get("discovery_evidence")
    discovery = discovery_raw if isinstance(discovery_raw, dict) else {}

    weighted_terms: list[tuple[int, str]] = []
    seen_terms: set[str] = set()

    def add_term(value: str, weight: int) -> None:
        cleaned = str(value or "").strip().strip("`'\"")
        if len(cleaned) < 4 or len(cleaned) > 120:
            return
        folded = cleaned.casefold()
        if folded in seen_terms or folded in _BOOTSTRAP_STOPWORDS:
            return
        if re.fullmatch(r"[0-9._:/-]+", cleaned):
            return
        seen_terms.add(folded)
        weighted_terms.append((weight, cleaned))

    for query in discovery.get("queries") or []:
        add_term(str(query), 14)
    if task is not None:
        for term in _source_bootstrap_terms(task, limit=16):
            folded = term.casefold().strip("._:-")
            add_term(term, 4 if folded in _BOOTSTRAP_LOW_SIGNAL_TERMS else 10)

    # Exact code/event/route tokens from the source-backed draft are especially
    # useful: they let a later finalisation pass jump straight to the handler it
    # just said was missing instead of showing the beginning of the file again.
    for match in re.finditer(r"`([^`\n]{3,140})`", draft or ""):
        token = match.group(1).strip()
        if re.search(r"[A-Za-z]", token):
            add_term(token, 18)
    gap = _missing_evidence_excerpt(draft or "") if draft else ""
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_.:-]{3,90}\b", gap):
        folded = token.casefold().strip("._:-")
        if folded not in _GAP_TERM_STOPWORDS and folded not in _BOOTSTRAP_LOW_SIGNAL_TERMS:
            add_term(token, 7)

    absolute_anchors: set[int] = set()
    for value in discovery.get("lines") or []:
        try:
            line_no = int(value)
        except (TypeError, ValueError):
            continue
        if line_no >= start_line and line_no < start_line + len(lines):
            absolute_anchors.add(line_no)

    candidates: list[tuple[float, int]] = []
    for index, line in enumerate(lines):
        absolute = start_line + index
        folded_line = line.casefold()
        score = 30.0 if absolute in absolute_anchors else 0.0
        matched = False
        for weight, term in weighted_terms:
            if term.casefold() in folded_line:
                score += float(weight)
                matched = True
        if matched and re.search(
            r"\b(?:async\s+def|def|class|function|const|let|var|if|elif|switch|case|return|await)\b",
            line,
            re.IGNORECASE,
        ):
            score += 3.0
        if score > 0:
            candidates.append((score, index))

    # If the previous handoff explicitly complained that its excerpt ended
    # before the interesting logic, ensure the tail of the already-captured
    # read is considered. This is not a new filesystem claim; it exposes source
    # Jace already read successfully.
    if re.search(
        r"(?:excerpt|source|output).{0,60}(?:cut|cuts|end|ends|truncat|mid-function)|not visible in (?:the )?(?:provided|available) (?:source|excerpt)",
        draft or "",
        re.IGNORECASE | re.DOTALL,
    ):
        candidates.append((28.0, len(lines) - 1))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    centers: list[int] = []
    for _score, index in candidates:
        if all(abs(index - existing) >= 24 for existing in centers):
            centers.append(index)
        if len(centers) >= 3:
            break
    if not centers:
        centers = [0]
        if len(lines) > 55:
            centers.append(len(lines) - 1)

    windows: list[tuple[int, int]] = []
    radius = 11
    for center in sorted(centers):
        lo = max(0, center - radius)
        hi = min(len(lines), center + radius + 1)
        if windows and lo <= windows[-1][1] + 3:
            windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
        else:
            windows.append((lo, hi))

    per_window = max(650, max_chars // max(1, len(windows)))
    rendered: list[str] = []
    for lo, hi in windows:
        header = f"LINES {start_line + lo}-{start_line + hi - 1}"
        body_lines: list[str] = []
        used = len(header) + 1
        for index in range(lo, hi):
            row = f"L{start_line + index}: {lines[index]}"
            if used + len(row) + 1 > per_window and body_lines:
                break
            body_lines.append(row)
            used += len(row) + 1
        rendered.append(header + "\n" + "\n".join(body_lines))
    return "\n...\n".join(rendered)[:max_chars]

def _focused_source_paths(
    records: list[dict[str, Any]],
    *,
    task: AgentTask | None,
    draft: str,
    limit: int = 5,
) -> list[str]:
    return [
        _source_record_path(record).replace("\\", "/").casefold()
        for record in _focused_source_records(records, task=task, draft=draft, limit=limit)
        if _source_record_path(record)
    ]


def _structural_expansion_terms(records: list[dict[str, Any]], *, task: AgentTask | None = None, limit: int = 8) -> list[str]:
    """Extract graph anchors only from the strongest verified evidence."""
    weighted: list[tuple[int, str]] = []
    seen: set[str] = set()
    def add(value: str, weight: int) -> None:
        cleaned = str(value or "").strip().strip("`'\"")
        if len(cleaned) < 4 or len(cleaned) > 100:
            return
        folded = cleaned.casefold()
        if folded in seen or folded in _BOOTSTRAP_STOPWORDS or folded in _BOOTSTRAP_LOW_SIGNAL_TERMS:
            return
        if re.fullmatch(r"[0-9._:/-]+", cleaned):
            return
        seen.add(folded); weighted.append((weight, cleaned))
    affinities = _objective_evidence_affinities(task) if task is not None else set()
    for record in _focused_source_records(records, task=task, draft="", limit=6):
        evidence = record.get("evidence")
        if not isinstance(evidence, dict): continue
        source_path = str(evidence.get("path") or "")
        kind = _bootstrap_path_kind(source_path)
        if kind == "test" and "test" not in affinities: continue
        if kind == "script" and "script" not in affinities: continue
        text = str(evidence.get("text") or "")
        raw_discovery = record.get("discovery_evidence")
        discovery = raw_discovery if isinstance(raw_discovery, dict) else {}
        snippets = [str(v) for v in (discovery.get("snippets") or []) if str(v).strip()]
        extraction_text = ("\n".join(snippets[:8]) + "\n" + text[:7000]).strip()
        for match in re.finditer(r"[\"'`]([^\"'`\n]{4,140})[\"'`]", extraction_text):
            value = match.group(1).strip()
            if value.startswith("/"):
                route = re.split(r"[?$]", value, maxsplit=1)[0].strip()
                if route and re.search(r"[A-Za-z]", route): add(route, 12)
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:/-]{3,119}", value):
                add(value, 9 if any(ch in value for ch in ".:/") else 5)
        for pattern in (
            r"\b(?:async\s+def|def|class|function)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
            r"\b(?:interface|type|enum|struct|trait|impl)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\b(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?[A-Za-z_<>,.?\[\]]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        ):
            for match in re.finditer(pattern, extraction_text): add(match.group(1), 6)
        for match in re.finditer(r"\b(?:import|from|use)\s+([A-Za-z_][A-Za-z0-9_:.\\/-]{2,99})", extraction_text):
            value = match.group(1).split(".")[-1].split("::")[-1].split("/")[-1].split("\\")[-1]
            add(value, 4)
    weighted.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [value for _, value in weighted[:limit]]


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


def _bootstrap_candidate_score(
    path: str,
    query: str,
    result: dict[str, Any],
    *,
    task: AgentTask,
) -> float:
    normalized = "/" + str(path or "").replace("\\", "/").casefold().lstrip("/")
    if any(part in normalized for part in _BOOTSTRAP_PATH_PENALTIES):
        return -1000.0
    name = normalized.rsplit("/", 1)[-1]
    kind = _bootstrap_path_kind(path)
    affinities = _objective_evidence_affinities(task)
    snippet = str(result.get("snippet") or "").strip()
    folded_query = str(query or "").casefold().strip()
    score = 0.0
    if kind == "logic":
        score += 7.0
    elif kind == "test":
        score += 6.0 if "test" in affinities else -5.0
    elif kind == "script":
        score += 5.0 if "script" in affinities else -4.0
    elif kind == "presentation": score += 5.0 if "presentation" in affinities else -4.0
    elif kind == "config": score += 5.0 if "config" in affinities else 0.0
    elif kind == "docs": score += 5.0 if "docs" in affinities else -3.0
    elif kind == "data": score += 5.0 if "data" in affinities else 1.0
    elif Path(name).suffix.casefold() in _BOOTSTRAP_SOURCE_EXTENSIONS: score += 1.0
    if bool(result.get("path_match")): score += 1.5
    if snippet:
        score += 2.0
        if _BOOTSTRAP_CODE_SIGNAL_RE.search(snippet) and kind in {"logic", "other"}:
            score += 2.5
        elif _BOOTSTRAP_CODE_SIGNAL_RE.search(snippet) and kind == "test" and "test" in affinities:
            score += 2.0
        elif _BOOTSTRAP_CODE_SIGNAL_RE.search(snippet) and kind == "script" and "script" in affinities:
            score += 1.5
    if folded_query:
        query_weight = 0.8 if folded_query in _BOOTSTRAP_LOW_SIGNAL_TERMS else 2.0
        if folded_query in name: score += 2.5 * query_weight
        elif folded_query in normalized: score += 1.0 * query_weight
        if folded_query in snippet.casefold(): score += 1.5 * query_weight
    if name.endswith((".lock", ".map")) or name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}: score -= 6.0
    return score


def _rank_bootstrap_candidate_records(
    search_records: list[dict[str, Any]],
    *,
    task: AgentTask,
) -> list[dict[str, Any]]:
    """Rank source candidates while preserving the search anchors that found them."""
    scores: dict[str, float] = {}
    displays: dict[str, str] = {}
    query_hits: dict[str, set[str]] = {}
    lines: dict[str, list[int]] = {}
    snippets: dict[str, list[str]] = {}

    for record in search_records:
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        query = str(evidence.get("query") or "").strip()
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
            score = _bootstrap_candidate_score(path, query, result, task=task)
            if score <= -900:
                continue
            scores[key] = scores.get(key, 0.0) + score
            displays.setdefault(key, path)
            if query:
                query_hits.setdefault(key, set()).add(query.casefold().strip("._:-"))
            try:
                line = int(result.get("line") or result.get("line_number") or 0)
            except (TypeError, ValueError):
                line = 0
            if line > 0 and line not in lines.setdefault(key, []):
                lines[key].append(line)
            snippet = str(result.get("snippet") or "").strip()
            if snippet and snippet not in snippets.setdefault(key, []):
                snippets[key].append(snippet[:500])

    for key, hits in query_hits.items():
        scores[key] = scores.get(key, 0.0) + max(0, len(hits) - 1) * 3.0

    ranked_keys = sorted(scores, key=lambda key: (-scores[key], displays[key].casefold()))
    return [
        {
            "path": displays[key],
            "score": scores[key],
            "queries": sorted(query_hits.get(key, set())),
            "lines": sorted(lines.get(key, [])),
            "snippets": snippets.get(key, [])[:6],
        }
        for key in ranked_keys
    ]


def _rank_bootstrap_candidates(search_records: list[dict[str, Any]], *, task: AgentTask) -> list[str]:
    """Compatibility wrapper returning only paths for callers that do not need anchors."""
    return [item["path"] for item in _rank_bootstrap_candidate_records(search_records, task=task)]


def _anchored_read_window(lines: list[int], *, max_lines: int = 360) -> tuple[int, int]:
    """Choose a bounded source window around the strongest search hit."""
    usable = sorted({int(line) for line in lines if isinstance(line, int) and line > 0})
    if not usable:
        return 1, max_lines
    anchor = usable[0]
    before = min(100, max_lines // 3)
    return max(1, anchor - before), max_lines

async def _record_bootstrap_tool_execution(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    used_tools: list[str],
    progress: float,
    discovery_evidence: dict[str, Any] | None = None,
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
    if discovery_evidence:
        execution["discovery_evidence"] = dict(discovery_evidence)
    if tool_name == "read_workspace_file" and execution.get("success") is True:
        relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
        execution["source_relevance"] = {
            "relevant": bool(relevant),
            "score": relevance_score,
            "reason": relevance_reason,
        }

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
        for index, term in enumerate(terms[:6]):
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

    candidate_records = _rank_bootstrap_candidate_records(search_records, task=task)
    if not candidate_records:
        return transcript, [], set()

    read_records: list[dict[str, Any]] = []
    paths: set[str] = set()
    # Read a small ranked set, but anchor each read around the search hit rather
    # than blindly reading line 1 of a large file.
    # Seed only slightly beyond the minimum; verified graph traversal can expand later.
    read_budget = min(max(required_reads + 1, 3), 4)
    workspace_id = str(targets[0].get("id") or "")
    for index, candidate in enumerate(candidate_records[:read_budget]):
        path = str(candidate.get("path") or "")
        start_line, max_lines = _anchored_read_window(candidate.get("lines") or [], max_lines=360)
        arguments = {
            "workspace_id": workspace_id,
            "path": path,
            "start_line": start_line,
            "max_lines": max_lines,
        }
        discovery = {
            "queries": candidate.get("queries") or [],
            "lines": candidate.get("lines") or [],
            "snippets": candidate.get("snippets") or [],
            "candidate_score": candidate.get("score") or 0.0,
            "anchored_start_line": start_line,
        }
        tool_message, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments=arguments,
            used_tools=used_tools,
            progress=min(0.145 + (index * 0.008), 0.19),
            discovery_evidence=discovery,
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
        relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
        execution["source_relevance"] = {
            "relevant": bool(relevant), "score": relevance_score, "reason": relevance_reason,
        }
        if not relevant:
            logger.info(
                "Director-managed %s task %s bootstrap read %s but did not count it as core evidence: %s",
                agent_name, task_id, source_path, relevance_reason,
            )
            continue
        normalized = source_path.replace("\\", "/").casefold()
        if normalized in paths:
            continue
        paths.add(normalized)
        read_records.append(execution)

    # If the initial objective-term search did not produce enough relevant evidence,
    # follow concrete symbols/keys discovered inside the relevant source already read.
    # This approximates a lightweight call/reference graph without assuming any
    # project framework or directory structure.
    if len(paths) < required_reads and read_records and "search_workspace_files" in available_tools:
        expansion_terms = _structural_expansion_terms(read_records, task=task, limit=8)
        expansion_search_records: list[dict[str, Any]] = []
        for index, term in enumerate(expansion_terms):
            _, execution = await _record_bootstrap_tool_execution(
                task_id=task_id,
                task=task,
                agent_name=agent_name,
                tool_name="search_workspace_files",
                arguments={
                    "workspace_id": workspace_id,
                    "query": term,
                    "path": ".",
                    "include_content": True,
                    "max_results": 12,
                },
                used_tools=used_tools,
                progress=min(0.19 + index * 0.005, 0.225),
            )
            if execution.get("success") is True:
                expansion_search_records.append(execution)

        if expansion_search_records:
            expansion_candidates = _rank_bootstrap_candidate_records(expansion_search_records, task=task)
            expansion_budget = min(max(required_reads - len(paths) + 3, 3), 6)
            expansion_index = 0
            for candidate in expansion_candidates:
                if expansion_index >= expansion_budget or len(paths) >= required_reads:
                    break
                candidate_path = str(candidate.get("path") or "")
                candidate_key = candidate_path.replace("\\", "/").casefold()
                if not candidate_path or candidate_key in paths:
                    continue
                expansion_index += 1
                start_line, max_lines = _anchored_read_window(candidate.get("lines") or [], max_lines=360)
                discovery = {
                    "queries": candidate.get("queries") or [],
                    "lines": candidate.get("lines") or [],
                    "snippets": candidate.get("snippets") or [],
                    "candidate_score": candidate.get("score") or 0.0,
                    "anchored_start_line": start_line,
                    "structural_followup": True,
                }
                tool_message, execution = await _record_bootstrap_tool_execution(
                    task_id=task_id,
                    task=task,
                    agent_name=agent_name,
                    tool_name="read_workspace_file",
                    arguments={
                        "workspace_id": workspace_id,
                        "path": candidate_path,
                        "start_line": start_line,
                        "max_lines": max_lines,
                    },
                    used_tools=used_tools,
                    progress=min(0.225 + expansion_index * 0.006, 0.26),
                    discovery_evidence=discovery,
                )
                transcript.append(tool_message)
                if execution.get("success") is not True:
                    continue
                evidence = execution.get("evidence")
                if not isinstance(evidence, dict):
                    continue
                source_path = str(evidence.get("path") or "").strip()
                try:
                    returned_lines = int(evidence.get("returned_lines") or 0)
                except (TypeError, ValueError):
                    returned_lines = 0
                if not source_path or returned_lines <= 0 or not str(evidence.get("text") or "").strip():
                    continue
                relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
                execution["source_relevance"] = {
                    "relevant": bool(relevant), "score": relevance_score, "reason": relevance_reason,
                }
                if not relevant:
                    continue
                normalized = source_path.replace("\\", "/").casefold()
                if normalized in paths:
                    continue
                paths.add(normalized)
                read_records.append(execution)
                logger.info(
                    "Director-managed %s task %s followed structural evidence into %s (%d/%d relevant reads).",
                    agent_name, task_id, source_path, len(paths), required_reads,
                )

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
            "max_lines": 360,
        }
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments=direct_args,
            used_tools=used_tools,
            progress=min(0.80 + index * 0.01, 0.86),
            discovery_evidence={
                "queries": [Path(candidate).name],
                "lines": [],
                "snippets": [],
                "candidate_score": 0.0,
                "named_followup": True,
            },
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
                ranked_records = _rank_bootstrap_candidate_records([search_execution], task=task) if search_execution.get("success") is True else []
                if ranked_records:
                    chosen = ranked_records[0]
                    start_line, max_lines = _anchored_read_window(chosen.get("lines") or [], max_lines=420)
                    _, execution = await _record_bootstrap_tool_execution(
                        task_id=task_id,
                        task=task,
                        agent_name=agent_name,
                        tool_name="read_workspace_file",
                        arguments={
                            "workspace_id": workspace_id,
                            "path": chosen.get("path"),
                            "start_line": start_line,
                            "max_lines": max_lines,
                        },
                        used_tools=used_tools,
                        progress=min(0.81 + index * 0.01, 0.88),
                        discovery_evidence={
                            "queries": chosen.get("queries") or [basename],
                            "lines": chosen.get("lines") or [],
                            "snippets": chosen.get("snippets") or [],
                            "candidate_score": chosen.get("score") or 0.0,
                            "anchored_start_line": start_line,
                            "named_followup": True,
                        },
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
        relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
        if not relevant:
            logger.info(
                "Director-managed %s task %s followed named evidence to %s but it did not count as core evidence: %s",
                agent_name, task_id, path, relevance_reason,
            )
            continue
        execution["source_relevance"] = {
            "relevant": True, "score": relevance_score, "reason": relevance_reason,
        }
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
    if tool_name == "search_workspace_files":
        raw_search_path = str(fixed.get("path") or "").strip().replace("\\", "/")
        if not raw_search_path:
            fixed["path"] = "."
            notes.append("defaulted search_workspace_files path to '.'")
        else:
            leaf = raw_search_path.rstrip("/").rsplit("/", 1)[-1]
            suffix = Path(leaf).suffix.casefold()
            if suffix in _BOOTSTRAP_SOURCE_EXTENSIONS or suffix in _BOOTSTRAP_DOC_EXTENSIONS:
                parent = raw_search_path.rstrip("/").rsplit("/", 1)[0] if "/" in raw_search_path.rstrip("/") else "."
                fixed["path"] = parent or "."
                notes.append("changed file-like search_workspace_files path to its containing directory")
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
    if tool_name == "search_workspace_files" and (
        "must be a directory" in lowered or "not a directory" in lowered or "does not exist" in lowered
    ):
        return (
            "WORKSPACE SEARCH PATH CORRECTION: search_workspace_files.path must be a directory, not a file. "
            "Use path='.' for a project-wide search or the containing directory of the file you were examining."
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
    r"cannot (?:confirm|verify|determine|conclude)(?:\s+the\s+root\s+cause)?(?:\s+without)?|"
    r"additional (?:file|artifact|component|evidence).*?(?:inspect|read)|"
    r"evidence (?:is|remains) incomplete|root cause cannot be determined|required additional inspection|"
    r"unresolved (?:issues?|questions?|evidence|limitations?))\b",
    re.IGNORECASE | re.DOTALL,
)

_UNRESOLVED_FRONTIER_RE = re.compile(
    r"(?:"
    r"\bmissing evidence\b|"
    r"\bunresolved (?:issues?|questions?|evidence|limitations?)\b|"
    r"\bidentified gap in evidence\b|"
    r"\bmissing component(?:s)? to inspect\b|"
    r"\broot cause cannot be determined\b|"
    r"\brequired additional inspection\b|"
    r"\b(?:still )?need(?:s|ed)? to inspect\b|"
    r"\brequires? inspection\b|"
    r"\bcannot (?:confirm|verify|determine|conclude)(?:\s+the\s+root\s+cause)?\b|"
    r"\bevidence (?:is|remains) incomplete\b|"
    r"\bdo not (?:contain|show|establish|prove)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_ARTIFACT_SOURCE_EXTENSIONS = (
    "properties", "graphql", "gradle", "svelte", "proto", "html", "tsx", "jsx", "php", "swift",
    "toml", "yaml", "yml", "scss", "sass", "less", "bash", "ps1", "java", "kts", "dart",
    "vue", "json", "xml", "sql", "css", "cpp", "hpp", "pyi", "conf", "hcl", "gql", "ini",
    "cfg", "html", "htm", "py", "ts", "js", "rs", "go", "kt", "rb", "sh", "cs", "fsx", "fs",
    "tf", "md", "c", "h",
)
_ARTIFACT_EXT_RE = "|".join(sorted({re.escape(ext) for ext in _ARTIFACT_SOURCE_EXTENSIONS}, key=len, reverse=True))
_ARTIFACT_PATH_RE = re.compile(
    rf"(?<![A-Za-z0-9_])("
    rf"(?:[A-Za-z0-9_. -]+(?:[/\\][A-Za-z0-9_. -]+)+\.(?:{_ARTIFACT_EXT_RE}))|"
    rf"(?:[A-Za-z0-9_.-]+\.(?:{_ARTIFACT_EXT_RE}))"
    rf")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def _draft_declares_missing_evidence(text: str) -> bool:
    return bool(_MISSING_EVIDENCE_RE.search(text or ""))


def _draft_has_unresolved_frontier(text: str) -> bool:
    """Return True when a specialist is explicitly saying the investigation is incomplete.

    This is intentionally broader than the original missing-evidence phrase matcher.
    Small local models often use headings such as "Unresolved Issues / Limitations",
    "Root Cause Cannot Be Determined", or "Required Additional Inspection" instead
    of the exact phrase "missing evidence".
    """
    return bool(_UNRESOLVED_FRONTIER_RE.search(text or ""))


def _artifact_references_in_draft(
    text: str,
    source_paths: set[str],
    *,
    include_already_read: bool = False,
) -> tuple[list[str], list[str]]:
    """Extract source artifact references and separate concrete paths from guesses.

    ``include_already_read=False`` is the frontier-discovery mode: paths Jace has
    already inspected are omitted so they cannot trigger redundant filesystem
    reads. ``include_already_read=True`` is the reconciliation mode used by the
    evidence dossier: a draft that says ``runner.py is still missing`` after
    runner.py was already read must pull that existing evidence *into* the next
    finalisation pass rather than search elsewhere.

    The artifact regex is extension-boundary-aware. Event keys such as
    ``agent.task.completed`` therefore cannot be truncated to the fake source
    path ``agent.task.c``, and ``ChatView.tsx`` cannot be shortened to
    ``ChatView.ts``.
    """
    read = {path.replace("\\", "/").casefold().lstrip("./") for path in source_paths}
    basenames = {path.split("/")[-1] for path in read}
    concrete: list[str] = []
    speculative: list[str] = []
    seen: set[str] = set()

    speculative_re = re.compile(
        r"(?:\blikely\b|\bprobably\b|\bpossibly\b|\bperhaps\b|\bmaybe\b|"
        r"\bmay\s+be\b|\bmight\s+be\b|\bcould\s+be\b|\bsuch\s+as\b|"
        r"\bfor\s+example\b|\be\.?g\.?\b|\bor\s+similar\b)",
        re.IGNORECASE,
    )

    def add(raw_value: str, start_pos: int, end_pos: int) -> None:
        raw = str(raw_value or "").strip("`'\".,;:()[]{} *-_")
        raw = raw.replace("\\/", "/")
        if not raw:
            return
        normal = raw.replace("\\", "/").casefold().lstrip("./")
        base = normal.split("/")[-1]
        if (not include_already_read) and (normal in read or base in basenames):
            return
        if normal in seen:
            return
        seen.add(normal)

        context_start = max(0, start_pos - 180)
        context_end = min(len(text or ""), end_pos + 100)
        context = str(text or "")[context_start:context_end]
        bucket = speculative if speculative_re.search(context) else concrete
        bucket.append(raw)

    for match in re.finditer(r"`([^`\n]{2,220})`", text or ""):
        token = match.group(1).strip()
        artifact = _ARTIFACT_PATH_RE.search(token)
        if artifact:
            add(artifact.group(1), match.start(1), match.end(1))
        if len(concrete) + len(speculative) >= 12:
            break

    if len(concrete) + len(speculative) < 12:
        for match in _ARTIFACT_PATH_RE.finditer(text or ""):
            add(match.group(1), match.start(1), match.end(1))
            if len(concrete) + len(speculative) >= 12:
                break

    def ordered(values: list[str]) -> list[str]:
        indexed = list(enumerate(values))
        indexed.sort(key=lambda item: (0 if "/" in item[1].replace("\\", "/") else 1, item[0]))
        return [value for _, value in indexed]

    return ordered(concrete), ordered(speculative)


def _already_read_artifacts_named_in_draft(text: str, source_paths: set[str]) -> list[str]:
    """Return canonical already-read paths that the unresolved draft asks for again."""
    if not text or not source_paths:
        return []
    concrete, _ = _artifact_references_in_draft(
        _missing_evidence_excerpt(text) or text,
        source_paths,
        include_already_read=True,
    )
    if not concrete:
        return []
    referenced = {value.replace("\\", "/").casefold().lstrip("./") for value in concrete}
    referenced_bases = {value.split("/")[-1] for value in referenced}
    matched: list[str] = []
    for source_path in source_paths:
        normal = str(source_path or "").replace("\\", "/").casefold().lstrip("./")
        if not normal:
            continue
        if normal in referenced or normal.split("/")[-1] in referenced_bases:
            matched.append(str(source_path))
    return sorted(set(matched), key=lambda value: value.replace("\\", "/").casefold())

def _unread_artifacts_named_in_draft(text: str, source_paths: set[str]) -> list[str]:
    concrete, _ = _artifact_references_in_draft(text, source_paths)
    return concrete



_GAP_CODE_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:]*$")

_GAP_TERM_STOPWORDS = {
    "additional", "actual", "available", "cannot", "code", "complete", "completed", "conclusion",
    "current", "determine", "evidence", "existing", "file", "files", "implementation", "incomplete",
    "inspect", "inspection", "issue", "missing", "need", "needed", "needs", "project", "relevant",
    "required", "requires", "result", "results", "root", "source", "system", "task", "verify", "verified",
    "without", "would", "could", "should", "logic", "mechanism",
}


def _missing_evidence_excerpt(text: str) -> str:
    """Extract the part of a draft that explains what remains unresolved."""
    value = str(text or "").strip()
    if not value:
        return ""
    lines = value.splitlines()
    selected: list[str] = []
    active = False
    for line in lines:
        folded = line.casefold()
        if (
            "missing evidence" in folded
            or "unresolved" in folded
            or "need to inspect" in folded
            or "needs inspection" in folded
            or "still need" in folded
            or "cannot confirm" in folded
            or "cannot verify" in folded
            or "cannot determine" in folded
            or "evidence is incomplete" in folded
            or "evidence remains incomplete" in folded
            or "root cause cannot be determined" in folded
            or "required additional inspection" in folded
            or "unresolved issues" in folded
            or "unresolved limitations" in folded
        ):
            active = True
        if active:
            selected.append(line)
            if len(selected) >= 28:
                break
    if selected:
        return "\n".join(selected)[-6000:]
    match = _MISSING_EVIDENCE_RE.search(value)
    if not match:
        return ""
    start = max(0, match.start() - 500)
    return value[start:start + 6000]


def _gap_search_terms(
    task: AgentTask,
    draft: str,
    evidence_records: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[str]:
    """Build project-agnostic search terms for the unresolved evidence frontier."""
    excerpt = _missing_evidence_excerpt(draft)
    # Concrete paths are handled by the named-artifact resolver. Speculative paths
    # must not leak basenames such as ``workers.py`` into free-text search, where
    # they can pull the frontier toward unrelated files.
    excerpt = _ARTIFACT_PATH_RE.sub(" ", excerpt)
    weighted: list[tuple[float, str]] = []
    seen: set[str] = set()

    def add(value: str, weight: float) -> None:
        raw = str(value or "").strip("`'\".,;:()[]{} ")
        if not raw or len(raw) < 3 or len(raw) > 96:
            return
        folded = raw.casefold()
        if folded in seen or folded in _GAP_TERM_STOPWORDS:
            return
        if raw.isdigit():
            return
        seen.add(folded)
        weighted.append((weight, raw))

    for match in re.finditer(r"`([^`\n]{2,120})`", excerpt):
        token = match.group(1).strip()
        if _ARTIFACT_PATH_RE.search(token):
            continue
        if _GAP_CODE_REF_RE.fullmatch(token):
            add(token, 10.0)
        elif len(token.split()) <= 4:
            add(token, 8.0)

    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.:-]{2,95}", excerpt):
        folded = token.casefold().strip("._:-")
        if folded in _GAP_TERM_STOPWORDS or folded in _BOOTSTRAP_STOPWORDS:
            continue
        weight = 7.0 if any(ch in token for ch in "_.:") or re.search(r"[A-Z].*[A-Z]", token) else 4.5
        add(token, weight)

    words = [
        word for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", excerpt)
        if word.casefold() not in _GAP_TERM_STOPWORDS
        and word.casefold() not in _BOOTSTRAP_STOPWORDS
    ]
    for width, weight in ((3, 5.5), (2, 5.0)):
        for index in range(0, max(0, len(words) - width + 1)):
            phrase = " ".join(words[index:index + width])
            if len(phrase) <= 72:
                add(phrase, weight)

    for term in _source_bootstrap_terms(task, limit=10):
        add(term, 2.0)

    weighted.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [value for _, value in weighted[:limit]]


async def _bootstrap_cross_reference_followup_evidence(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    workspace_catalog: list[dict[str, Any]],
    available_tools: set[str],
    used_tools: list[str],
    evidence_records: list[dict[str, Any]],
    already_read: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Follow verified symbols/routes from existing evidence into connected source.

    This is intentionally preferred over natural-language gap search. It traverses
    actual implementation anchors discovered in source (route strings, event keys,
    type/function names, imports) and therefore behaves like a lightweight
    cross-reference graph without assuming a framework or directory layout.
    """
    if "search_workspace_files" not in available_tools or "read_workspace_file" not in available_tools:
        return [], set()
    targets = _select_bootstrap_workspaces(task, workspace_catalog)
    if not targets:
        return [], set()
    workspace_id = str(targets[0].get("id") or "")
    if not workspace_id:
        return [], set()

    terms = _structural_expansion_terms(evidence_records, task=task, limit=12)
    if not terms:
        return [], set()

    search_records: list[dict[str, Any]] = []
    for index, term in enumerate(terms[:10]):
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="search_workspace_files",
            arguments={
                "workspace_id": workspace_id,
                "query": term,
                "path": ".",
                "include_content": True,
                "max_results": 16,
            },
            used_tools=used_tools,
            progress=min(0.835 + index * 0.005, 0.89),
        )
        if execution.get("success") is True:
            search_records.append(execution)

    candidates = _rank_bootstrap_candidate_records(search_records, task=task)
    records: list[dict[str, Any]] = []
    new_paths: set[str] = set()
    for candidate in candidates:
        if len(records) >= 3:
            break
        candidate_path = str(candidate.get("path") or "").strip()
        if not candidate_path:
            continue
        normalized = candidate_path.replace("\\", "/").casefold()
        if normalized in already_read or normalized in new_paths:
            continue
        queries = [str(v) for v in (candidate.get("queries") or []) if str(v).strip()]
        if not queries:
            continue

        start_line, max_lines = _anchored_read_window(candidate.get("lines") or [], max_lines=440)
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments={
                "workspace_id": workspace_id,
                "path": candidate_path,
                "start_line": start_line,
                "max_lines": max_lines,
            },
            used_tools=used_tools,
            progress=min(0.89 + len(records) * 0.008, 0.925),
            discovery_evidence={
                "queries": queries,
                "lines": candidate.get("lines") or [],
                "snippets": candidate.get("snippets") or [],
                "candidate_score": candidate.get("score") or 0.0,
                "anchored_start_line": start_line,
                "structural_followup": True,
                "cross_reference_followup": True,
            },
        )
        if execution.get("success") is not True:
            continue
        evidence = execution.get("evidence")
        if not isinstance(evidence, dict):
            continue
        source_path = str(evidence.get("path") or "").strip()
        try:
            returned_lines = int(evidence.get("returned_lines") or 0)
        except (TypeError, ValueError):
            returned_lines = 0
        if not source_path or returned_lines <= 0 or not str(evidence.get("text") or "").strip():
            continue
        relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
        execution["source_relevance"] = {
            "relevant": bool(relevant), "score": relevance_score, "reason": relevance_reason,
        }
        if not relevant:
            continue
        key = source_path.replace("\\", "/").casefold()
        if key in already_read or key in new_paths:
            continue
        new_paths.add(key)
        records.append(execution)

    return records, new_paths


async def _bootstrap_gap_followup_evidence(
    *,
    task_id: str,
    task: AgentTask,
    agent_name: str,
    workspace_catalog: list[dict[str, Any]],
    available_tools: set[str],
    used_tools: list[str],
    draft: str,
    evidence_records: list[dict[str, Any]],
    already_read: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Deterministically continue an investigation from its unresolved frontier."""
    if "search_workspace_files" not in available_tools or "read_workspace_file" not in available_tools:
        return [], set()
    targets = _select_bootstrap_workspaces(task, workspace_catalog)
    if not targets:
        return [], set()
    workspace_id = str(targets[0].get("id") or "")
    if not workspace_id:
        return [], set()

    terms = _gap_search_terms(task, draft, evidence_records, limit=12)
    if not terms:
        return [], set()

    search_records: list[dict[str, Any]] = []
    for index, term in enumerate(terms[:8]):
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="search_workspace_files",
            arguments={
                "workspace_id": workspace_id,
                "query": term,
                "path": ".",
                "include_content": True,
                "max_results": 16,
            },
            used_tools=used_tools,
            progress=min(0.82 + index * 0.006, 0.875),
        )
        if execution.get("success") is True:
            search_records.append(execution)

    candidates = _rank_bootstrap_candidate_records(search_records, task=task)
    if not candidates:
        return [], set()

    records: list[dict[str, Any]] = []
    new_paths: set[str] = set()
    for candidate in candidates:
        if len(records) >= 2:
            break
        candidate_path = str(candidate.get("path") or "").strip()
        if not candidate_path:
            continue
        normalized = candidate_path.replace("\\", "/").casefold()
        if normalized in already_read or normalized in new_paths:
            continue

        start_line, max_lines = _anchored_read_window(candidate.get("lines") or [], max_lines=420)
        discovery = {
            "queries": candidate.get("queries") or [],
            "lines": candidate.get("lines") or [],
            "snippets": candidate.get("snippets") or [],
            "candidate_score": candidate.get("score") or 0.0,
            "anchored_start_line": start_line,
            "structural_followup": True,
            "gap_followup": True,
        }
        _, execution = await _record_bootstrap_tool_execution(
            task_id=task_id,
            task=task,
            agent_name=agent_name,
            tool_name="read_workspace_file",
            arguments={
                "workspace_id": workspace_id,
                "path": candidate_path,
                "start_line": start_line,
                "max_lines": max_lines,
            },
            used_tools=used_tools,
            progress=min(0.88 + len(records) * 0.008, 0.92),
            discovery_evidence=discovery,
        )
        if execution.get("success") is not True:
            continue
        evidence = execution.get("evidence")
        if not isinstance(evidence, dict):
            continue
        source_path = str(evidence.get("path") or "").strip()
        try:
            returned_lines = int(evidence.get("returned_lines") or 0)
        except (TypeError, ValueError):
            returned_lines = 0
        if not source_path or returned_lines <= 0 or not str(evidence.get("text") or "").strip():
            continue

        relevant, relevance_score, relevance_reason = _source_read_relevance(task, execution)
        execution["source_relevance"] = {
            "relevant": bool(relevant),
            "score": relevance_score,
            "reason": relevance_reason,
        }
        if not relevant:
            continue
        key = source_path.replace("\\", "/").casefold()
        if key in already_read or key in new_paths:
            continue
        new_paths.add(key)
        records.append(execution)

    return records, new_paths


def _source_evidence_dossier(
    records: list[dict[str, Any]],
    *,
    task: AgentTask | None = None,
    draft: str = "",
) -> str:
    """Distil the strongest source evidence for the local reasoning model."""
    selected = _focused_source_records(records, task=task, draft=draft, limit=5)
    chunks: list[str] = []
    for record in selected:
        evidence = record.get("evidence")
        if not isinstance(evidence, dict): continue
        path = str(evidence.get("path") or "").strip()
        text = str(evidence.get("text") or "").strip()
        if not path or not text: continue
        score, why = _source_record_focus_score(record, task=task, draft=draft, index=0)
        excerpt = _targeted_source_excerpt(record, task=task, draft=draft, max_chars=2700)
        if not excerpt:
            continue
        chunks.append(f"SOURCE FILE: {path}\nEVIDENCE FOCUS: score={score:.2f}; {why}\n{excerpt}\nEND SOURCE FILE: {path}")
    return "\n\n".join(chunks)[:13_500]




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
    dossier = _source_evidence_dossier(evidence_records, task=task, draft=draft)
    if not dossier:
        return draft

    prompt = (
        "SOURCE-BACKED FINAL HANDOFF\n"
        f"Task: {task.title}\n"
        f"Instruction: {task.instruction}\n\n"
        f"Previous draft (may be empty or unreliable):\n{draft or '[none]'}\n\n"
        "The following line-numbered source windows were selected from files Jace successfully read and are the ONLY authority "
        "for local implementation claims in this handoff. Windows may come from later parts of a file; do not assume omitted middle lines are absent from the source.\n\n"
        f"{dossier}\n\n"
        "Write a concise specialist handoff to Jace. Requirements:\n"
        "- Cite every source file you rely on using its exact relative path.\n"
        "- Cite at least one exact function/class/symbol from the excerpts in backticks.\n"
        "- Separate verified source facts from hypotheses or missing evidence.\n"
        "- Do not invent any file, symbol, handler, registry, state, or architecture term.\n"
        "- RECONCILE THE PREVIOUS DRAFT WITH THE SOURCE FILE HEADERS BELOW. If the previous draft says a file still needs inspection but that same file is supplied below, it has already been inspected. Analyze the supplied windows and do not request that file again.\n"
        "- NEVER fabricate a plausible path for missing evidence. If an exact path is not present in a supplied "
        "SOURCE FILE header, describe the missing responsibility semantically (for example, 'task execution loop' "
        "or 'completion event consumer') rather than guessing worker.py/handler.ts/etc.\n"
        "- If these excerpts are insufficient to establish the root cause, say exactly what additional "
        "responsibility/flow needs inspection rather than guessing a filename.\n"
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

    # Keep this explicitly unverified, but preserve the strongest evidence paths
    # and observed symbols so downstream Analyst has a useful handoff even if the
    # small model emits an empty response twice.
    focused = _focused_source_records(evidence_records, task=task, draft=draft, limit=5)
    evidence_lines: list[str] = []
    for record in focused:
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        text = str(evidence.get("text") or "")
        if not path:
            continue
        symbols: list[str] = []
        for pattern in (
            r"\b(?:async\s+def|def|class|function)\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
            r"\b(?:interface|type|enum|struct|trait)\s+([A-Za-z_][A-Za-z0-9_]*)",
        ):
            for match in re.finditer(pattern, text):
                symbol = match.group(1)
                if symbol not in symbols:
                    symbols.append(symbol)
                if len(symbols) >= 4:
                    break
            if len(symbols) >= 4:
                break
        suffix = f" — observed symbols: {', '.join(f'`{symbol}`' for symbol in symbols)}" if symbols else ""
        evidence_lines.append(f"- {path}{suffix}")
    return (
        "UNVERIFIED ANALYSIS: source inspection succeeded, but the Code/File specialist did not produce a textual source analysis after finalisation retries. "
        "Strongest captured evidence:\n"
        + ("\n".join(evidence_lines) if evidence_lines else "- no focused source excerpt was available")
        + "\nThe requested conclusion remains unverified; Analyst must reason only from the captured source evidence."
    )

async def _close_source_evidence_frontier(
    *,
    task_id: str,
    cancel_event: asyncio.Event,
    task: AgentTask,
    agent_name: str,
    model: str,
    reasoning_mode: str,
    temperature: float,
    system_prompt: str,
    workspace_catalog: list[dict[str, Any]],
    available_tools: set[str],
    used_tools: list[str],
    final_text: str,
    evidence_records: list[dict[str, Any]],
    successful_source_paths: set[str],
    max_rounds: int = 4,
) -> tuple[str, list[dict[str, Any]], set[str]]:
    """Close an unresolved evidence frontier after the model tool budget is exhausted.

    The normal worker loop is intentionally bounded. A source-backed finalisation
    pass can, however, discover the most useful missing artifact only *after* that
    loop has consumed its model/tool steps. Deterministic workspace search/read
    operations are not model tool-choice turns, so use a second bounded closure
    stage to resolve exact named artifacts or search the worker's missing-evidence
    description before the task is allowed to finish.

    This keeps the investigation project-agnostic: every follow-up is derived from
    the worker's own evidence-backed gap statement and symbols already captured.
    """
    text = str(final_text or "").strip()
    if not text or not evidence_records or not _draft_has_unresolved_frontier(text):
        return text, evidence_records, successful_source_paths

    # 11B.4.21: reconcile claims against the successful-read ledger before
    # expanding the frontier. A model can correctly identify runner.py as the
    # missing responsibility while overlooking that Jace has already read it.
    # That contradiction is solved by re-finalising with runner.py forced into
    # the focused dossier, not by searching for unrelated new files.
    already_read_claims = _already_read_artifacts_named_in_draft(text, successful_source_paths)
    if already_read_claims:
        logger.info(
            "Director-managed %s task %s reconciling unresolved draft against %d already-read artifact(s): %s",
            agent_name,
            task_id,
            len(already_read_claims),
            ", ".join(already_read_claims),
        )
        text = await _finalize_source_backed_handoff(
            task_id=task_id,
            cancel_event=cancel_event,
            task=task,
            model=model,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            system_prompt=system_prompt,
            evidence_records=evidence_records,
            draft=text,
        )
        if not _draft_has_unresolved_frontier(text):
            logger.info(
                "Director-managed %s task %s closed the evidence contradiction using already-read source evidence before frontier expansion.",
                agent_name,
                task_id,
            )
            return text, evidence_records, successful_source_paths
        repeated_claims = _already_read_artifacts_named_in_draft(text, successful_source_paths)
        if repeated_claims:
            logger.info(
                "Director-managed %s task %s still requested already-read artifact(s) after reconciliation (%s); refusing to broaden the frontier from a contradictory missing-file claim.",
                agent_name,
                task_id,
                ", ".join(repeated_claims),
            )
            return text, evidence_records, successful_source_paths

    initial_named, initial_speculative = _artifact_references_in_draft(text, successful_source_paths)
    logger.info(
        "Director-managed %s task %s entering post-budget evidence-frontier closure with %d concrete named unread artifact(s): %s%s",
        agent_name,
        task_id,
        len(initial_named),
        ", ".join(initial_named) or "[none]",
        (f"; ignored {len(initial_speculative)} speculative guessed artifact(s): {', '.join(initial_speculative)}" if initial_speculative else ""),
    )

    for round_index in range(max(0, int(max_rounds))):
        if cancel_event.is_set():
            raise AgentTaskCancelled()

        before = set(successful_source_paths)
        unread = _unread_artifacts_named_in_draft(text, successful_source_paths)
        added_records: list[dict[str, Any]] = []
        added_paths: set[str] = set()
        route = ""

        if unread:
            named_records, named_paths = await _bootstrap_named_followup_evidence(
                task_id=task_id,
                task=task,
                agent_name=agent_name,
                workspace_catalog=workspace_catalog,
                available_tools=available_tools,
                used_tools=used_tools,
                artifacts=unread,
                already_read=successful_source_paths,
            )
            if named_records:
                added_records.extend(named_records)
                added_paths.update(named_paths)
                route = "named artifact"

        if not added_records:
            cross_records, cross_paths = await _bootstrap_cross_reference_followup_evidence(
                task_id=task_id,
                task=task,
                agent_name=agent_name,
                workspace_catalog=workspace_catalog,
                available_tools=available_tools,
                used_tools=used_tools,
                evidence_records=evidence_records,
                already_read=successful_source_paths,
            )
            if cross_records:
                added_records.extend(cross_records)
                added_paths.update(cross_paths)
                route = "verified cross-reference"

        if not added_records:
            gap_records, gap_paths = await _bootstrap_gap_followup_evidence(
                task_id=task_id,
                task=task,
                agent_name=agent_name,
                workspace_catalog=workspace_catalog,
                available_tools=available_tools,
                used_tools=used_tools,
                draft=text,
                evidence_records=evidence_records,
                already_read=successful_source_paths,
            )
            if gap_records:
                added_records.extend(gap_records)
                added_paths.update(gap_paths)
                route = "semantic gap search"

        if not added_records:
            logger.info(
                "Director-managed %s task %s post-budget evidence frontier remained unresolved after deterministic closure round %d/%d; no new approved-workspace evidence was found.",
                agent_name,
                task_id,
                round_index + 1,
                max_rounds,
            )
            break

        before_focus = set(_focused_source_paths(evidence_records, task=task, draft=text, limit=5))
        evidence_records.extend(added_records)
        successful_source_paths.update(added_paths)
        after_focus = set(_focused_source_paths(evidence_records, task=task, draft=text, limit=5))
        focus_improved = bool(after_focus - before_focus)
        actual_new = sorted(successful_source_paths - before)
        logger.info(
            "Director-managed %s task %s post-budget evidence-frontier closure round %d/%d followed %s evidence into %d additional relevant source file(s): %s",
            agent_name,
            task_id,
            round_index + 1,
            max_rounds,
            route or "deterministic",
            len(actual_new),
            ", ".join(actual_new) or "[none]",
        )

        if not focus_improved:
            logger.info(
                "Director-managed %s task %s stopped post-budget frontier expansion after round %d/%d because new evidence did not improve the focused finalisation dossier.",
                agent_name, task_id, round_index + 1, max_rounds,
            )
            break

        text = await _finalize_source_backed_handoff(
            task_id=task_id,
            cancel_event=cancel_event,
            task=task,
            model=model,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            system_prompt=system_prompt,
            evidence_records=evidence_records,
            draft=text,
        )
        if not _draft_has_unresolved_frontier(text):
            logger.info(
                "Director-managed %s task %s closed the post-budget evidence frontier after %d round(s).",
                agent_name,
                task_id,
                round_index + 1,
            )
            break

    return text, evidence_records, successful_source_paths


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
            "text": str(parsed.get("text") or "")[:18_000],
            "total_lines": parsed.get("total_lines"),
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


async def _background_task_cancel_requested(task_id: str) -> bool:
    """Read the persistent cancellation flag while a background tool approval waits."""
    async with SessionLocal() as session:
        current = await get_task(session, task_id)
        return (
            current is None
            or bool(current.cancel_requested)
            or current.status == "cancelled"
        )


async def _wait_for_background_approval(task_id: str, approval_id: str) -> bool:
    """Wait for the shared tool approval queue without making agent cancellation wait for the timeout."""
    wait_task = asyncio.create_task(approval_manager.wait(approval_id))
    try:
        while True:
            done, _pending = await asyncio.wait({wait_task}, timeout=0.25)
            if wait_task in done:
                approved = wait_task.result()
                if await _background_task_cancel_requested(task_id):
                    raise AgentTaskCancelled()
                return approved

            if await _background_task_cancel_requested(task_id):
                approval_manager.cancel(approval_id)
                wait_task.cancel()
                try:
                    await wait_task
                except (asyncio.CancelledError, asyncio.TimeoutError, LookupError):
                    pass
                raise AgentTaskCancelled()
    except asyncio.CancelledError:
        approval_manager.cancel(approval_id)
        wait_task.cancel()
        try:
            await wait_task
        except (asyncio.CancelledError, asyncio.TimeoutError, LookupError):
            pass
        raise


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
        initial_status = (
            "denied"
            if global_permission == "deny"
            else "awaiting_approval"
            if global_permission == "ask"
            else "approved"
        )
        audit = await create_tool_audit(
            session,
            conversation_id=task.conversation_id,
            tool_name=tool_name,
            permission_mode=f"agent:{task.id}",
            arguments=arguments,
            status=initial_status,
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

    approval_id: str | None = None
    if global_permission == "ask":
        approval = approval_manager.create(
            conversation_id=task.conversation_id,
            tool_name=tool_name,
            label=definition.label,
            description=definition.description,
            risk=definition.risk,
            arguments=arguments,
            source="agent",
            task_id=task.id,
            agent_id=task.agent_id,
        )
        approval_id = approval.approval_id

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="awaiting_approval",
                approval_id=approval_id,
            )

        await _set_state(
            task.id,
            status="waiting_permission",
            progress=task.progress,
            message=f"Waiting for permission: {definition.label}",
            event_type="approval_required",
            event_message=f"{task.agent_id.title()} Agent is waiting for permission to use {tool_name}.",
            event_data={
                "tool_name": tool_name,
                "arguments": arguments,
                "approval_id": approval_id,
                "risk": definition.risk,
            },
        )

        try:
            approved = await _wait_for_background_approval(task.id, approval_id)
        except asyncio.TimeoutError:
            async with SessionLocal() as session:
                await update_tool_audit(
                    session,
                    audit.id,
                    status="timed_out",
                    error="User approval timed out.",
                    completed=True,
                )
            await _set_state(
                task.id,
                status="using_tool",
                progress=task.progress,
                message=f"Permission timed out: {definition.label}",
                event_type="approval_timed_out",
                event_message=f"Permission timed out for {tool_name}.",
                event_data={"tool_name": tool_name, "approval_id": approval_id},
            )
            error = "Tool execution was not approved before the approval timeout."
            evidence = _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=error,
            )
            evidence.update({"approval_id": approval_id, "permission": "timed_out"})
            return {
                "role": "tool",
                "tool_name": tool_name,
                "content": error,
            }, evidence
        except AgentTaskCancelled:
            async with SessionLocal() as session:
                await update_tool_audit(
                    session,
                    audit.id,
                    status="cancelled",
                    error="Background task was cancelled while awaiting approval.",
                    completed=True,
                )
            raise
        except asyncio.CancelledError:
            approval_manager.cancel(approval_id)
            raise

        if not approved:
            async with SessionLocal() as session:
                await update_tool_audit(
                    session,
                    audit.id,
                    status="denied",
                    error="User denied background-agent tool execution.",
                    completed=True,
                )
            await _set_state(
                task.id,
                status="using_tool",
                progress=task.progress,
                message=f"Permission denied: {definition.label}",
                event_type="approval_denied",
                event_message=f"The user denied {tool_name} for {task.agent_id.title()} Agent.",
                event_data={"tool_name": tool_name, "approval_id": approval_id},
            )
            error = "The user denied this background-agent tool call."
            evidence = _tool_evidence_payload(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=error,
            )
            evidence.update({"approval_id": approval_id, "permission": "denied"})
            return {
                "role": "tool",
                "tool_name": tool_name,
                "content": error,
            }, evidence

        async with SessionLocal() as session:
            await update_tool_audit(
                session,
                audit.id,
                status="approved",
            )
        await _set_state(
            task.id,
            status="using_tool",
            progress=task.progress,
            message=f"Permission granted: using {tool_name}",
            event_type="approval_granted",
            event_message=f"The user approved {tool_name} for {task.agent_id.title()} Agent.",
            event_data={"tool_name": tool_name, "approval_id": approval_id},
        )

    try:
        async with SessionLocal() as session:
            result = await definition.execute(
                arguments,
                ToolContext(
                    session=session,
                    conversation_id=task.conversation_id,
                    user_message=task.instruction,
                ),
            )
            full_content = result.content
            content = full_content[:8_000]
            display = (result.display or full_content)[:1_500]
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

        evidence = _tool_evidence_payload(
            tool_name=tool_name,
            arguments=arguments,
            success=True,
            # Evidence extraction must see the complete JSON payload. Only the
            # model-visible message above is bounded to 8k.
            content=full_content,
            display=display,
        )
        if approval_id:
            evidence.update({"approval_id": approval_id, "permission": "approved"})
        return message, evidence
    except (ToolError, ValueError) as exc:
        error = str(exc)
        async with SessionLocal() as session:
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
        evidence = _tool_evidence_payload(
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            error=error,
        )
        if approval_id:
            evidence.update({"approval_id": approval_id, "permission": "approved"})
        return message, evidence
    except Exception as exc:
        error = f"Unexpected tool failure: {exc}"
        logger.exception("Background agent tool %s failed unexpectedly", tool_name)
        async with SessionLocal() as session:
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
        evidence = _tool_evidence_payload(
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            error=error,
        )
        if approval_id:
            evidence.update({"approval_id": approval_id, "permission": "approved"})
        return message, evidence

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
    reconciled_missing_paths: set[str] = set()
    if requires_local_source:
        logger.info(
            "Director-managed %s task %s requires %d DISTINCT relevant source read(s) as a minimum investigation seed using project-discovered paths.",
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
                "Director-managed %s task %s deterministically bootstrapped %d relevant source read(s) as the initial evidence seed: %s",
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

            if requires_local_source and coverage_ok and _draft_has_unresolved_frontier(candidate_text):
                read_claims = _already_read_artifacts_named_in_draft(
                    candidate_text, successful_source_paths
                )
                new_read_claims = [
                    path for path in read_claims
                    if path.replace("\\", "/").casefold() not in reconciled_missing_paths
                ]
                if new_read_claims:
                    reconciled_missing_paths.update(
                        path.replace("\\", "/").casefold() for path in new_read_claims
                    )
                    logger.info(
                        "Director-managed %s task %s reconciling source-backed draft against already-read artifact(s) before frontier expansion: %s",
                        definition.name, task_id, ", ".join(new_read_claims),
                    )
                    candidate_text = await _finalize_source_backed_handoff(
                        task_id=task_id,
                        cancel_event=cancel_event,
                        task=task,
                        model=model,
                        reasoning_mode=reasoning_mode,
                        temperature=temperature,
                        system_prompt=worker_system_prompt,
                        evidence_records=source_evidence_records,
                        draft=candidate_text,
                    )
                    if not _draft_has_unresolved_frontier(candidate_text):
                        final_text = candidate_text
                        source_finalized = True
                        break
                    repeated = _already_read_artifacts_named_in_draft(
                        candidate_text, successful_source_paths
                    )
                    if repeated and evidence_nudges < max_evidence_nudges:
                        evidence_nudges += 1
                        messages.append({"role": "assistant", "content": candidate_text})
                        messages.append({
                            "role": "user",
                            "content": (
                                "EVIDENCE RECONCILIATION REQUIRED. The artifact(s) you just described as still needing inspection were already read successfully: "
                                + ", ".join(repeated)
                                + ". Do not search for replacements or broaden to unrelated files. Analyze the supplied source evidence for those artifacts and correct the contradiction. "
                                "Only identify a new missing responsibility if it is genuinely not present in the already-read evidence."
                            ),
                        })
                        logger.info(
                            "Director-managed %s task %s kept an already-read artifact in its missing-evidence claim after reconciliation; forcing one bounded reasoning retry without frontier broadening.",
                            definition.name, task_id,
                        )
                        continue

            if (
                requires_local_source
                and coverage_ok
                and _draft_has_unresolved_frontier(candidate_text)
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

                # Prefer verified cross-references from source already captured before
                # using natural-language gap search. This follows real routes, event
                # keys, symbols and imports rather than guessed filenames.
                cross_records, cross_paths = await _bootstrap_cross_reference_followup_evidence(
                    task_id=task_id,
                    task=task,
                    agent_name=definition.name,
                    workspace_catalog=workspace_catalog,
                    available_tools=set(tool_names),
                    used_tools=used_tools,
                    evidence_records=source_evidence_records,
                    already_read=successful_source_paths,
                )
                if cross_records:
                    source_evidence_records.extend(cross_records)
                    successful_source_paths.update(cross_paths)
                    successful_source_reads = len(successful_source_paths)
                    messages.append({
                        "role": "user",
                        "content": (
                            "DIRECTOR VERIFIED CROSS-REFERENCE FOLLOW-UP\n"
                            "Your source-backed draft identified an unresolved implementation layer. "
                            "Jace followed concrete routes, event keys, symbols, types or imports already present in verified source and captured connected implementation evidence. "
                            "Reassess the objective using this expanded source graph before requesting broader semantic search.\n\n"
                            f"{_source_evidence_dossier(cross_records, task=task, draft=candidate_text)}\n"
                            "END DIRECTOR VERIFIED CROSS-REFERENCE FOLLOW-UP"
                        ),
                    })
                    logger.info(
                        "Director-managed %s task %s followed verified cross-references into %d additional relevant source file(s): %s",
                        definition.name,
                        task_id,
                        len(cross_paths),
                        ", ".join(sorted(cross_paths)),
                    )
                    continue

                # If cross-reference traversal cannot expand the graph, use only the
                # semantic responsibilities named in the missing-evidence statement.
                gap_records, gap_paths = await _bootstrap_gap_followup_evidence(
                    task_id=task_id,
                    task=task,
                    agent_name=definition.name,
                    workspace_catalog=workspace_catalog,
                    available_tools=set(tool_names),
                    used_tools=used_tools,
                    draft=candidate_text,
                    evidence_records=source_evidence_records,
                    already_read=successful_source_paths,
                )
                if gap_records:
                    source_evidence_records.extend(gap_records)
                    successful_source_paths.update(gap_paths)
                    successful_source_reads = len(successful_source_paths)
                    messages.append({
                        "role": "user",
                        "content": (
                            "DIRECTOR SEMANTIC EVIDENCE-FRONTIER FOLLOW-UP\n"
                            "Verified cross-reference traversal could not close the remaining implementation gap. "
                            "Jace therefore searched the approved workspace using only the semantic responsibilities described in the missing-evidence statement and captured additional anchored evidence. "
                            "Reassess the objective using the expanded evidence graph.\n\n"
                            f"{_source_evidence_dossier(gap_records, task=task, draft=candidate_text)}\n"
                            "END DIRECTOR SEMANTIC EVIDENCE-FRONTIER FOLLOW-UP"
                        ),
                    })
                    logger.info(
                        "Director-managed %s task %s expanded the unresolved evidence frontier by semantic gap search into %d additional relevant source file(s): %s",
                        definition.name,
                        task_id,
                        len(gap_paths),
                        ", ".join(sorted(gap_paths)),
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
            source_finalized = bool(
                requires_local_source
                and coverage_ok
                and source_evidence_records
                and not _draft_has_unresolved_frontier(candidate_text)
            )
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
                        # A model-triggered reread of a path that Jace already counted
                        # should retain the audited discovery provenance from the
                        # original anchored read. Otherwise the same file can appear
                        # to become "irrelevant" merely because the model omitted the
                        # preceding search call on its reread.
                        if normalized_path in successful_source_paths and not isinstance(tool_execution.get("discovery_evidence"), dict):
                            for prior_record in source_evidence_records:
                                prior_evidence = prior_record.get("evidence")
                                if not isinstance(prior_evidence, dict):
                                    continue
                                prior_path = str(prior_evidence.get("path") or "").replace("\\", "/").casefold()
                                prior_discovery = prior_record.get("discovery_evidence")
                                if prior_path == normalized_path and isinstance(prior_discovery, dict):
                                    tool_execution["discovery_evidence"] = dict(prior_discovery)
                                    break
                        relevant, relevance_score, relevance_reason = _source_read_relevance(task, tool_execution)
                        if not relevant:
                            logger.info(
                                "Director-managed %s task %s read %s successfully but did not count it as core evidence: %s",
                                definition.name,
                                task_id,
                                source_path or "<unknown path>",
                                relevance_reason,
                            )
                            post_tool_nudge = (
                                f"SOURCE READ SUCCEEDED BUT IS SUPPORTING/LOW-RELEVANCE EVIDENCE: {source_path}. "
                                f"Reason: {relevance_reason}. Continue by searching for an implementation/artifact that directly contains the task's distinctive concepts. "
                                "Do not treat a cosmetic, generic entry-point, documentation, or unrelated support file as proof of the requested mechanism unless that artifact type is what the user asked about."
                            )
                        else:
                            tool_execution["source_relevance"] = {
                                "relevant": True,
                                "score": relevance_score,
                                "reason": relevance_reason,
                            }
                            source_evidence_records.append(tool_execution)
                            if normalized_path and normalized_path not in successful_source_paths:
                                successful_source_paths.add(normalized_path)
                                successful_source_reads = len(successful_source_paths)
                                logger.info(
                                    "Director-managed %s task %s verified DISTINCT RELEVANT source read %d/%d: %s (%s)",
                                    definition.name,
                                    task_id,
                                    successful_source_reads,
                                    required_source_reads,
                                    source_path or "<unknown path>",
                                    relevance_reason,
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
                                    "Director-managed %s task %s reread relevant source %s; duplicate path does not increase coverage (%d/%d).",
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

    # A source-backed finalisation performed after the bounded model/tool loop can
    # be the first point at which the worker identifies the *right* missing file
    # or implementation layer. Do not lose that discovery simply because the
    # model tool-step budget is already exhausted. Close the remaining frontier
    # with bounded deterministic approved-workspace search/read calls, then
    # regenerate the source-backed handoff over the expanded evidence graph.
    if (
        requires_local_source
        and source_evidence_records
        and _draft_has_unresolved_frontier(final_text)
    ):
        final_text, source_evidence_records, successful_source_paths = await _close_source_evidence_frontier(
            task_id=task_id,
            cancel_event=cancel_event,
            task=task,
            agent_name=definition.name,
            model=model,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            system_prompt=worker_system_prompt,
            workspace_catalog=workspace_catalog,
            available_tools=set(tool_names),
            used_tools=used_tools,
            final_text=final_text,
            evidence_records=source_evidence_records,
            successful_source_paths=successful_source_paths,
            max_rounds=4,
        )
        successful_source_reads = len(successful_source_paths)

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
