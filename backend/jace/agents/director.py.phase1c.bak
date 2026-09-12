from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from jace.agents.definitions import get_agent_definition
from jace.agents.models import AgentTask
from jace.agents.service import (
    create_task,
    event_data,
    get_task,
    list_events,
    list_tasks,
    prepare_retry,
    task_metadata,
    task_used_tools,
)
from jace.ai.engine import OllamaRequestError, stream_chat, structured_chat
from jace.database import SessionLocal
from jace.db.conversations import add_message, get_conversation, model_history
from jace.db.settings import get_or_create_assistant_settings
from jace.performance import chat_activity
from jace.runtime import runtime_events

logger = logging.getLogger("uvicorn.error")

AgentKind = Literal["research", "code", "files", "analyst", "general"]
ReasoningMode = Literal["fast", "balanced", "deep"]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
MAX_DIRECTOR_STEPS = 4
DIRECTOR_POLL_SECONDS = 0.55
DIRECTOR_RESULT_CONTEXT_CHARS = 7_500


class DirectorStep(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    agent_id: AgentKind
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=12_000)
    depends_on: list[str] = Field(default_factory=list, max_length=4)
    reasoning_mode: ReasoningMode = "balanced"
    # Generic execution/evidence contract. These values describe what this worker
    # needs to accomplish; they never encode repository-specific paths.
    work_mode: Literal["inspect", "modify", "create", "files", "research", "analysis", "general"] = "general"
    required_source_reads: int = Field(default=0, ge=0, le=4)


class DirectorPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=1_000)
    steps: list[DirectorStep] = Field(min_length=1, max_length=MAX_DIRECTOR_STEPS)


class DirectorRoute(BaseModel):
    """Small-model-friendly planning output.

    The LLM chooses specialists only; Jace constructs the dependency graph and
    specialist instructions deterministically. This is substantially more robust
    than asking a 4B local model to emit a nested graph schema.
    """

    agents: list[AgentKind] = Field(min_length=1, max_length=MAX_DIRECTOR_STEPS)
    rationale: str = Field(default="", max_length=800)


@dataclass
class StepOutcome:
    step_id: str
    agent_id: str
    title: str
    status: str
    result: str = ""
    error: str = ""
    task_id: str | None = None
    retried: bool = False
    used_tools: list[str] | None = None
    verified: bool = False
    evidence: str = ""
    evidence_context: str = ""


_workflow_tasks: set[asyncio.Task[Any]] = set()
_active_workflow_ids: set[str] = set()


def _track_workflow(task: asyncio.Task[Any], workflow_id: str) -> None:
    _workflow_tasks.add(task)
    _active_workflow_ids.add(workflow_id)

    def done_callback(done: asyncio.Task[Any]) -> None:
        _workflow_tasks.discard(done)
        _active_workflow_ids.discard(workflow_id)
        if done.cancelled():
            return
        try:
            error = done.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "Agent Director workflow %s stopped with an unhandled error: %s",
                workflow_id,
                error,
                exc_info=error,
            )

    task.add_done_callback(done_callback)


def _safe_title(text: str, *, fallback: str = "Directed agent workflow") -> str:
    title = " ".join((text or "").strip().split()).strip(" .,:;-")
    if not title:
        return fallback
    if len(title) > 92:
        title = title[:89].rstrip() + "..."
    return title[0].upper() + title[1:]


def _trim_context(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


async def _profile_and_context(
    conversation_id: str | None,
) -> tuple[str, float, list[dict[str, str]]]:
    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        model = profile.default_model
        temperature = profile.temperature
        history: list[dict[str, str]] = []
        if conversation_id:
            conversation = await get_conversation(session, conversation_id)
            if conversation is not None:
                history = model_history(conversation)[-8:]

    compact_history = [
        {
            "role": item["role"],
            "content": _trim_context(str(item.get("content") or ""), 2_500),
        }
        for item in history
        if item.get("role") in {"user", "assistant"}
    ]
    return model, temperature, compact_history


def _plan_valid(plan: DirectorPlan) -> bool:
    if not plan.steps or len(plan.steps) > MAX_DIRECTOR_STEPS:
        return False

    ids = [step.id.strip() for step in plan.steps]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        return False

    id_set = set(ids)
    for step in plan.steps:
        if step.id in step.depends_on:
            return False
        if any(dep not in id_set for dep in step.depends_on):
            return False

    remaining = {step.id: set(step.depends_on) for step in plan.steps}
    resolved: set[str] = set()
    while remaining:
        ready = [step_id for step_id, deps in remaining.items() if deps <= resolved]
        if not ready:
            return False
        for step_id in ready:
            resolved.add(step_id)
            remaining.pop(step_id, None)
    return True


GREENFIELD_TARGET_RE = (
    r"(?:project|app|application|website|service|api|library|package|tool|game|platform|"
    r"dashboard|bot|cli|server|backend|frontend|microservice|system|program)"
)


def _greenfield_creation_requested(objective: str) -> bool:
    """Detect new-software intent without assuming a language, framework, or repository layout."""
    text = " ".join((objective or "").casefold().split())
    if re.search(r"\b(?:from scratch|greenfield)\b", text):
        return True

    action = (
        r"(?:create|build|develop|start|make|scaffold|bootstrap|design|architect|plan|"
        r"generate|initiali[sz]e|set\s+up|code)"
    )
    # Allow technology adjectives between "new" and the artifact, e.g.
    # "design a new Python FastAPI project" or "build a new Rust CLI tool".
    if re.search(
        rf"\b{action}\b.{{0,80}}\bnew(?:\s+[a-z0-9+#._/-]+){{0,10}}\s+{GREENFIELD_TARGET_RE}\b",
        text,
    ):
        return True

    # Also support natural forms like "create FastAPI project from scratch".
    if re.search(
        rf"\b{action}\b.{{0,100}}\b{GREENFIELD_TARGET_RE}\b.{{0,50}}\bfrom scratch\b",
        text,
    ):
        return True
    return False


def _creation_execution_requested(objective: str) -> bool:
    """Separate greenfield planning/design from a request to actually create artifacts."""
    if not _greenfield_creation_requested(objective):
        return False
    text = " ".join((objective or "").casefold().split())
    # Design/architecture-only prompts should be useful even with no workspace.
    planning_only = bool(re.search(r"\b(?:design|architect|plan|specify|outline|propose)\b", text))
    execution = bool(
        re.search(
            r"\b(?:create|build|develop|start|make|scaffold|bootstrap|generate|initiali[sz]e|set\s+up|code|implement)\b",
            text,
        )
    )
    return execution or not planning_only


def _objective_traits(objective: str) -> tuple[bool, bool, bool, bool]:
    """Classify only the current objective using broad, project-agnostic cues."""
    text = (objective or "").casefold()
    web_needed = bool(
        re.search(
            r"\b(?:latest|current external|today|online|web|internet|public source|"
            r"public sources|release notes|upstream documentation|official documentation|news)\b",
            text,
        )
    )
    explicit_code = bool(
        re.search(
            r"\b(?:code|coding|bug|debug|error|repo|repository|source code|programming|typescript|javascript|python|"
            r"php|laravel|react|rust|tauri|implementation|compile|scaffold|refactor|software|fastapi|django|flask|"
            r"java|kotlin|swift|dart|go|golang|ruby|rails|vue|svelte|angular|node|express)\b",
            text,
        )
    )
    software_creation = _greenfield_creation_requested(objective)
    project_change = bool(
        re.search(r"\b(?:fix|patch|implement|modify|update|investigate|diagnos|root cause)\w*\b", text)
        and re.search(r"\b(?:software project|system|workflow|agent|service|api|repository|repo|application|app|platform)\b", text)
    )
    code_needed = explicit_code or software_creation or project_change
    files_needed = bool(
        re.search(r"\b(?:file|files|folder|directory|workspace|path|organise|organize|move|rename)\b", text)
    )
    analysis_needed = bool(
        re.search(
            r"\b(?:analyse|analyze|assess|compare|evaluate|decide|root cause|diagnos|"
            r"investigate|why|best fix|recommend|review)\w*",
            text,
        )
    )
    return web_needed, code_needed, files_needed, analysis_needed


def _code_work_mode(objective: str) -> Literal["inspect", "modify", "create"]:
    """Determine what kind of software work was requested without assuming a stack/layout."""
    text = " ".join((objective or "").casefold().split())
    if _greenfield_creation_requested(objective):
        return "create"

    # Strong change verbs indicate actual modification.  Do not treat the noun
    # phrase "best fix" in an investigation as an instruction to edit files.
    if re.search(r"\b(?:apply|implement|patch|change|update|modify|edit|refactor|rewrite|upgrade|remove|replace|add)\b", text):
        return "modify"
    if re.search(r"(?:^|\bplease\s+)fix\b", text):
        return "modify"
    if re.search(r"\bfix\s+(?:this|it|them|whatever|anything|any|the\s+(?:bug|issue|problem|error)|all)\b", text):
        return "modify"
    return "inspect"


def _broad_software_scope(objective: str) -> bool:
    """Broad investigations benefit from more than one source artifact, regardless of repo layout."""
    text = (objective or "").casefold()
    markers = (
        "workflow", "background", "race condition", "event flow", "end-to-end", "integration",
        "architecture", "system", "across", "interaction", "pipeline", "lifecycle", "request flow",
    )
    return any(marker in text for marker in markers)


def _required_source_reads_for_code(objective: str, work_mode: str) -> int:
    if work_mode == "create":
        # A brand-new project may legitimately contain no source yet. Requiring reads
        # would make creation impossible. The worker should inspect workspace state,
        # then create/plan artifacts depending on its authorised capabilities.
        return 0
    return 2 if _broad_software_scope(objective) else 1

def _normalise_route_agents(objective: str, agents: list[AgentKind]) -> list[AgentKind]:
    web_needed, code_needed, files_needed, analysis_needed = _objective_traits(objective)
    selected: list[AgentKind] = []
    for agent in agents:
        if agent not in selected:
            selected.append(agent)

    # Hard evidence guardrails. A local software diagnosis must include a worker
    # that can inspect the approved workspace. Web Research cannot substitute for
    # source inspection. Conversely, do not add Research merely because old chat
    # context mentioned the web.
    if code_needed and "code" not in selected:
        selected.insert(0, "code")
    if not web_needed and "research" in selected and code_needed:
        selected.remove("research")
    if files_needed and not code_needed and "files" not in selected:
        selected.insert(0, "files")
    if web_needed and "research" not in selected:
        selected.insert(0, "research")
    if analysis_needed and len(selected) > 1 and "analyst" not in selected:
        selected.append("analyst")

    # A Code worker already has the safe workspace-reading tools; a separate File
    # worker is redundant for ordinary code diagnosis unless the objective is
    # specifically about file organisation.
    if code_needed and "files" in selected and not re.search(
        r"\b(?:organise|organize|move|rename|delete|folder structure)\b",
        (objective or "").casefold(),
    ):
        selected.remove("files")

    if not selected:
        selected = ["analyst" if analysis_needed else "general"]
    return selected[:MAX_DIRECTOR_STEPS]


def _plan_from_agents(objective: str, agents: list[AgentKind], rationale: str = "") -> DirectorPlan:
    selected = _normalise_route_agents(objective, agents)
    steps: list[DirectorStep] = []

    if "research" in selected:
        steps.append(DirectorStep(
            id="research",
            agent_id="research",
            title="Research relevant external evidence",
            instruction=(
                "Research only external/current facts that the objective genuinely requires. "
                "Use authoritative sources and preserve source URLs or names for material claims. "
                "Do not infer a local project's implementation from unrelated frameworks or generic examples."
            ),
            reasoning_mode="balanced",
            work_mode="research",
        ))

    if "code" in selected:
        mode = _code_work_mode(objective)
        reads = _required_source_reads_for_code(objective, mode)
        if mode == "create":
            execute_creation = _creation_execution_requested(objective)
            title = (
                "Create the requested software project"
                if execute_creation
                else "Design the requested software project"
            )
            instruction = (
                "Treat this as a greenfield software task. Do not require pre-existing source files or inspect an "
                "unrelated existing project merely to satisfy an evidence quota. Define a coherent project structure, "
                "interfaces, data model, dependencies, tests, and implementation appropriate to the user's request. "
                + (
                    "The user asked for actual creation. If write/execute capabilities are explicitly available, create "
                    "the requested artifacts and verify what was produced. If they are not available, return the exact "
                    "file set/implementation needed and clearly state that execution requires authorised write capability. "
                    if execute_creation
                    else
                    "The user asked for design/planning rather than proof of an existing implementation. Produce a complete, "
                    "internally consistent design and proposed file structure. Workspace inspection is optional unless the user "
                    "explicitly asked to integrate with an existing project. "
                )
                + "Never claim files were created, modified, tested, or executed without successful tool evidence."
            )
        elif mode == "modify":
            title = "Inspect the project and prepare the requested change"
            instruction = (
                "Inspect the approved project workspace before proposing or performing changes. Locate the relevant "
                "implementation with workspace tools, read the source that supports your conclusions, preserve existing "
                "conventions, and prepare the smallest coherent change. If write/execute capabilities are not authorised, "
                "return the exact proposed change rather than claiming it was applied."
            )
        else:
            title = "Inspect the project and establish the actual behaviour"
            instruction = (
                "Inspect the approved project workspace before reaching a conclusion. Locate the relevant implementation "
                "with workspace tools and read the source that supports the diagnosis. Cite only paths and code identifiers "
                "that appeared in successful workspace reads. If the available evidence is insufficient, identify what "
                "additional artifact or component must be inspected instead of guessing."
            )
        steps.append(DirectorStep(
            id="code",
            agent_id="code",
            title=title,
            instruction=instruction,
            reasoning_mode="deep",
            work_mode=mode,
            required_source_reads=reads,
        ))

    if "files" in selected:
        steps.append(DirectorStep(
            id="files",
            agent_id="files",
            title="Inspect the relevant workspace files",
            instruction=(
                "Inspect the approved workspace using file tools. Support project/file-specific claims with actual paths "
                "or tool results. For organisation tasks, inspect before recommending moves/deletes and never assume a "
                "file is disposable from its name alone."
            ),
            reasoning_mode="balanced",
            work_mode="files",
        ))

    if "analyst" in selected:
        deps = [step.id for step in steps if step.agent_id in {"research", "code", "files"}]
        steps.append(DirectorStep(
            id="analysis",
            agent_id="analyst",
            title="Review the evidence and recommend the best outcome",
            instruction=(
                "Review only the supplied specialist evidence. Separate verified facts, implementation status, hypotheses, "
                "and recommendations. Never promote an upstream unsupported claim to a confirmed fact. If an upstream "
                "specialist explicitly says evidence is incomplete, you MUST preserve that uncertainty and must not use "
                "phrases such as 'root cause identified' or present a concrete fix as confirmed. If evidence is incomplete, "
                "explain the missing evidence precisely rather than inventing a project structure."
            ),
            depends_on=deps,
            reasoning_mode="balanced",
            work_mode="analysis",
        ))

    if "general" in selected and not steps:
        steps.append(DirectorStep(
            id="general",
            agent_id="general",
            title="Complete the directed background objective",
            instruction="Complete the objective methodically and label assumptions clearly.",
            reasoning_mode="balanced",
            work_mode="general",
        ))

    if not steps:
        steps.append(DirectorStep(
            id="analysis",
            agent_id="analyst",
            title="Analyse the objective",
            instruction="Analyse the objective conservatively and distinguish facts from assumptions.",
            reasoning_mode="balanced",
            work_mode="analysis",
        ))

    summary = (rationale or "Director route constructed with project-agnostic evidence guardrails.").strip()
    return DirectorPlan(summary=summary[:1000], steps=steps[:MAX_DIRECTOR_STEPS])

def _fallback_plan(objective: str, history: list[dict[str, str]]) -> DirectorPlan:
    # `history` is intentionally unused for routing. It remains available to the
    # workers via normal conversation context but cannot change specialist choice.
    del history
    web_needed, code_needed, files_needed, analysis_needed = _objective_traits(objective)
    agents: list[AgentKind] = []
    if web_needed:
        agents.append("research")
    if code_needed:
        agents.append("code")
    elif files_needed:
        agents.append("files")
    if analysis_needed and (agents or not code_needed):
        agents.append("analyst")
    if not agents:
        agents.append("general")
    return _plan_from_agents(
        objective,
        agents,
        "Deterministic Director fallback selected from the current objective only.",
    )


async def _build_plan(
    *,
    objective: str,
    conversation_id: str | None,
    reasoning_mode: ReasoningMode,
) -> tuple[DirectorPlan, str, float, list[dict[str, str]]]:
    model, temperature, history = await _profile_and_context(conversation_id)
    await chat_activity.wait_for_idle(0.18)

    traits = _objective_traits(objective)
    if any(traits):
        plan = _fallback_plan(objective, history)
        logger.info(
            "Agent Director used deterministic evidence-first routing for objective traits web=%s code=%s files=%s analysis=%s.",
            *traits,
        )
        return plan, model, temperature, history

    system_prompt = f"""
You are Jace's Agent Director ROUTER. Choose the smallest useful set of specialists.
Return JSON only. You are choosing specialist IDs, not writing the workflow graph.

Available IDs:
- research: external/current public information
- code: inspect, design, diagnose or prepare changes for an approved software workspace
- files: inspect/organise approved local files
- analyst: review evidence and synthesize conclusions
- general: background work that fits none of the above

Rules:
- Use 1-{MAX_DIRECTOR_STEPS} IDs.
- For a software bug, implementation, code-change, or software-project creation request, include code.
- Do not use research for a local code diagnosis unless current external evidence is explicitly required.
- Do not invent specialist names.
- Do not include dependencies or task instructions; Jace constructs those deterministically.
""".strip()

    messages = [{
        "role": "user",
        "content": (
            f"OBJECTIVE\n{objective}\nEND OBJECTIVE\n\n"
            f"Preferred reasoning mode: {reasoning_mode}."
        ),
    }]

    try:
        route = await structured_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            response_model=DirectorRoute,
        )
        agents = _normalise_route_agents(objective, route.agents)
        plan = _plan_from_agents(objective, agents, route.rationale)
        if not _plan_valid(plan):
            raise OllamaRequestError("Director router produced an invalid guarded plan.")
        return plan, model, temperature, history
    except Exception as exc:
        logger.warning(
            "Agent Director router fell back to deterministic routing: %s",
            exc,
        )
        return _fallback_plan(objective, history), model, temperature, history


async def _existing_workflow_tasks(workflow_id: str) -> dict[str, AgentTask]:
    async with SessionLocal() as session:
        rows = await list_tasks(session, limit=500)
    mapped: dict[str, AgentTask] = {}
    for row in rows:
        metadata = task_metadata(row)
        if metadata.get("director_workflow_id") != workflow_id:
            continue
        step_id = metadata.get("director_step_id")
        if isinstance(step_id, str) and step_id:
            previous = mapped.get(step_id)
            if previous is None or row.created_at > previous.created_at:
                mapped[step_id] = row
    return mapped


async def _wait_for_terminal(task_id: str) -> AgentTask:
    while True:
        async with SessionLocal() as session:
            row = await get_task(session, task_id)
        if row is None:
            raise RuntimeError(f"Director child task disappeared: {task_id}")
        if row.status in TERMINAL_STATUSES:
            return row
        await asyncio.sleep(DIRECTOR_POLL_SECONDS)


async def _enqueue_task(task_id: str, priority: int) -> bool:
    from jace.agents.manager import agent_manager

    for _ in range(15):
        if await agent_manager.enqueue(task_id, priority=priority):
            return True
        async with SessionLocal() as session:
            row = await get_task(session, task_id)
        if row is None:
            return False
        if row.status not in {"queued"}:
            return row.status not in {"failed", "cancelled"}
        await asyncio.sleep(0.18)
    return False


def _dependency_context(step: DirectorStep, outcomes: dict[str, StepOutcome]) -> str:
    if not step.depends_on:
        return "No dependency handoff is required for this step."
    chunks: list[str] = []
    for dependency in step.depends_on:
        outcome = outcomes[dependency]
        body = outcome.result or outcome.error or "No textual result was returned."
        source_evidence = (
            f"\nSource evidence captured by Jace:\n{_trim_context(outcome.evidence_context, 5000)}"
            if outcome.evidence_context
            else ""
        )
        chunks.append(
            f"DEPENDENCY {dependency} ({outcome.agent_id}, {outcome.status})\n"
            f"Verification: {'VERIFIED' if outcome.verified else 'UNVERIFIED'} — {outcome.evidence}\n"
            f"{_trim_context(body, DIRECTOR_RESULT_CONTEXT_CHARS)}"
            f"{source_evidence}\n"
            f"END DEPENDENCY {dependency}"
        )
    return "\n\n".join(chunks)


LOCAL_EVIDENCE_TOOLS = {
    "read_workspace_file",
    "search_workspace_files",
    "list_workspace_files",
    "workspace_file_info",
    "inspect_workspace_media",
}
WEB_EVIDENCE_TOOLS = {"web_search", "read_web_page", "browser_read_page"}
_SOURCE_FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z0-9_./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|php|json|toml|yaml|yml|md|sql|rs|go|java|cs|cpp|c|h))",
    re.IGNORECASE,
)
_BACKTICK_RE = re.compile(r"`([^`\n]{2,160})`")
_SIMPLE_CODE_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:]*$")

_UPSTREAM_EVIDENCE_GAP_RE = re.compile(
    r"\b(?:missing evidence|unresolved|evidence (?:is|remains) incomplete|"
    r"cannot (?:confirm|verify|determine|conclude)|need(?:s|ed)? to inspect|"
    r"still need(?:s)?|additional (?:file|artifact|component|evidence))\b",
    re.IGNORECASE,
)


def _dependency_has_explicit_evidence_gap(
    step: DirectorStep,
    outcomes: dict[str, StepOutcome],
) -> bool:
    for dependency in step.depends_on:
        outcome = outcomes.get(dependency)
        if outcome is None or outcome.verified:
            continue
        if _UPSTREAM_EVIDENCE_GAP_RE.search(outcome.result or ""):
            return True
    return False


def _sanitize_unverified_analyst_language(text: str) -> str:
    """Keep an unverified Analyst review from sounding like a confirmed diagnosis."""
    value = str(text or "").strip()
    if not value:
        return value
    replacements = (
        (r"(?im)^#{1,6}\s*Investigation Complete:\s*Root Cause Identified\s*$", "### Unverified Hypothesis Review"),
        (r"(?im)^#{1,6}\s*Root Cause Identified\s*$", "### Unverified Hypothesis Review"),
        (r"(?im)^\*\*Root Cause:\*\*", "**Hypothesis:**"),
        (r"(?im)^Root Cause:\s*", "Hypothesis: "),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    if not value.casefold().startswith("unverified review"):
        value = (
            "UNVERIFIED REVIEW — upstream project evidence is incomplete, so the following "
            "analysis must be treated as hypotheses/recommendations rather than a confirmed root cause.\n\n"
            + value
        )
    return value


_ALLOWED_GENERIC_CODE_REFS = {
    "running", "completed", "failed", "cancelled", "queued", "thinking",
    "using_tool", "waiting_permission", "json", "http", "https", "system",
    "read_workspace_file", "search_workspace_files", "workspace_file_info",
    "list_workspace_files", "list_computer_workspaces",
}




def _required_distinct_source_files(step: DirectorStep, objective: str) -> int:
    if step.agent_id != "code":
        return 0
    if step.required_source_reads:
        return int(step.required_source_reads)
    return _required_source_reads_for_code(objective, step.work_mode)


def _is_creation_step(step: DirectorStep) -> bool:
    return step.agent_id == "code" and step.work_mode == "create"

async def _task_tool_evidence(task_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        events = await list_events(session, task_id, limit=500)
    records: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "tool_completed":
            continue
        data = event_data(event)
        if not isinstance(data, dict):
            continue
        records.append(data)
    return records


def _director_evidence_focus_score(record: dict[str, Any], index: int) -> float:
    """Rank raw source reads for downstream Analyst context by provenance strength."""
    relevance = record.get("source_relevance")
    score = 0.0
    reason = ""
    if isinstance(relevance, dict):
        try:
            score = float(relevance.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        reason = str(relevance.get("reason") or "").casefold()
    discovery = record.get("discovery_evidence")
    d = discovery if isinstance(discovery, dict) else {}
    if "direct=" in reason:
        score += 14.0
    if "search=" in reason:
        score += 7.0
    if bool(d.get("named_followup")):
        score += 15.0
    if bool(d.get("cross_reference_followup")):
        score += 7.0
    elif bool(d.get("structural_followup")):
        score += 3.0
    if bool(d.get("gap_followup")):
        score -= 2.5
    # Recency is only a tiebreaker. It must not let the last broad search evict
    # stronger producer/consumer/persistence evidence.
    score += min(index, 1000) * 0.001
    return score


def _director_focused_read_records(records: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    unique: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if record.get("success") is not True or record.get("tool_name") != "read_workspace_file":
            continue
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        text = str(evidence.get("text") or "").strip()
        if not path or not text:
            continue
        key = path.replace("\\", "/").casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append((index, record))
    unique.sort(key=lambda item: (-_director_evidence_focus_score(item[1], item[0]), item[0]))
    return [record for _, record in unique[:limit]]



def _director_targeted_excerpt(
    record: dict[str, Any],
    *,
    objective: str = "",
    result: str = "",
    max_chars: int = 2350,
) -> str:
    """Expose the relevant windows of a successful read to downstream Analyst."""
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    text = str(evidence.get("text") or "")
    lines = text.splitlines()
    if not lines:
        return ""
    try:
        start_line = max(1, int(evidence.get("start_line") or 1))
    except (TypeError, ValueError):
        start_line = 1
    discovery = record.get("discovery_evidence")
    d = discovery if isinstance(discovery, dict) else {}
    stop = {
        "this", "that", "with", "from", "into", "work", "best", "whatever", "agents", "need", "keep",
        "chat", "free", "project", "system", "actual", "source", "evidence", "file", "files", "component",
        "inspect", "review", "investigate", "determine", "recommend", "missing", "verified", "facts",
    }
    terms: list[tuple[int, str]] = []
    seen: set[str] = set()
    def add(value: str, weight: int) -> None:
        value = str(value or "").strip().strip("`'\"")
        folded = value.casefold().strip("._:-")
        if len(value) < 4 or len(value) > 120 or folded in stop or folded in seen:
            return
        if re.fullmatch(r"[0-9._:/-]+", value):
            return
        seen.add(folded); terms.append((weight, value))
    for query in d.get("queries") or []: add(str(query), 13)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.:-]{3,90}", objective or ""):
        add(token, 8)
    for match in re.finditer(r"`([^`\n]{3,140})`", result or ""):
        add(match.group(1), 17)

    anchors: set[int] = set()
    for value in d.get("lines") or []:
        try: line_no = int(value)
        except (TypeError, ValueError): continue
        if start_line <= line_no < start_line + len(lines): anchors.add(line_no)
    ranked: list[tuple[float, int]] = []
    for index, line in enumerate(lines):
        score = 28.0 if start_line + index in anchors else 0.0
        folded_line = line.casefold()
        for weight, term in terms:
            if term.casefold() in folded_line: score += weight
        if score > 0: ranked.append((score, index))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    centers: list[int] = []
    for _, index in ranked:
        if all(abs(index - other) >= 22 for other in centers): centers.append(index)
        if len(centers) >= 3: break
    if not centers:
        centers = [0] + ([len(lines) - 1] if len(lines) > 55 else [])
    windows: list[tuple[int, int]] = []
    for center in sorted(centers):
        lo, hi = max(0, center - 10), min(len(lines), center + 11)
        if windows and lo <= windows[-1][1] + 3: windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
        else: windows.append((lo, hi))
    per_window = max(600, max_chars // max(1, len(windows)))
    rendered: list[str] = []
    for lo, hi in windows:
        rows = [f"LINES {start_line + lo}-{start_line + hi - 1}"]
        used = len(rows[0]) + 1
        for index in range(lo, hi):
            row = f"L{start_line + index}: {lines[index]}"
            if used + len(row) + 1 > per_window and len(rows) > 1: break
            rows.append(row); used += len(row) + 1
        rendered.append("\n".join(rows))
    return "\n...\n".join(rendered)[:max_chars]

def _source_evidence_context(records: list[dict[str, Any]], *, objective: str = "", result: str = "") -> str:
    """Build a compact Analyst evidence context from the strongest source reads.

    Chronological truncation previously meant late/high-value runtime files such
    as execution or persistence components could be absent from Analyst context
    even though Code had read them successfully. Rank first, then bound text.
    """
    focused_reads = _director_focused_read_records(records, limit=5)
    if focused_reads:
        chunks: list[str] = []
        for record in focused_reads:
            evidence = record.get("evidence")
            if not isinstance(evidence, dict):
                continue
            path = str(evidence.get("path") or "").strip()
            text = str(evidence.get("text") or "").strip()
            if path and text:
                excerpt = _director_targeted_excerpt(record, objective=objective, result=result, max_chars=2300)
                if excerpt:
                    chunks.append(f"READ {path}\n{excerpt}\nEND READ {path}")
        return "\n\n".join(chunks)[:12_000]

    chunks: list[str] = []
    for record in records:
        if record.get("success") is not True or record.get("tool_name") != "search_workspace_files":
            continue
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        query = str(evidence.get("query") or "").strip()
        results = evidence.get("results")
        if isinstance(results, list) and results:
            paths = [
                str(item.get("path") or "")
                for item in results[:12]
                if isinstance(item, dict) and item.get("path")
            ]
            if paths:
                chunks.append(f"SEARCH {query!r}: " + ", ".join(paths))
    return "\n\n".join(chunks)[:12_000]



def _successful_records(records: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
    return [
        record for record in records
        if record.get("success") is True and record.get("tool_name") == tool_name
    ]


def _relevant_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return successful source reads that the runner marked task-relevant.

    A successful read proves that a file exists and was inspected; it does not by
    itself prove that the file bears on the requested conclusion.  Director-managed
    Code workers attach a generic relevance assessment to every source read so a
    stylesheet, README, manifest, or unrelated entry point cannot accidentally
    satisfy implementation verification for a different kind of task.
    """
    output: list[dict[str, Any]] = []
    for record in _successful_records(records, "read_workspace_file"):
        relevance = record.get("source_relevance")
        if isinstance(relevance, dict) and relevance.get("relevant") is True:
            output.append(record)
    return output


def _read_paths_and_corpus(records: list[dict[str, Any]]) -> tuple[list[str], str]:
    paths: list[str] = []
    corpus_parts: list[str] = []
    for record in _successful_records(records, "read_workspace_file"):
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("path") or "").strip()
        text = str(evidence.get("text") or "")
        returned_lines = evidence.get("returned_lines")
        try:
            line_count = int(returned_lines or 0)
        except (TypeError, ValueError):
            line_count = 0
        if not path or line_count <= 0 or not text.strip():
            continue
        paths.append(path)
        corpus_parts.extend([path, text])
    return list(dict.fromkeys(paths)), "\n".join(corpus_parts)


def _unsupported_specific_refs(result: str, read_paths: list[str], source_corpus: str) -> list[str]:
    if not result.strip():
        return []
    path_lookup = {path.replace("\\", "/").casefold() for path in read_paths}
    basenames = {path.replace("\\", "/").split("/")[-1].casefold() for path in read_paths}
    corpus_folded = source_corpus.casefold()
    unsupported: list[str] = []

    for match in _SOURCE_FILE_RE.finditer(result):
        raw = match.group(1).strip(".,;:()[]{}")
        normal = raw.replace("\\", "/").casefold()
        base = normal.split("/")[-1]
        if normal not in path_lookup and base not in basenames:
            unsupported.append(raw)

    for match in _BACKTICK_RE.finditer(result):
        token = match.group(1).strip()
        if not _SIMPLE_CODE_REF_RE.fullmatch(token):
            continue
        folded = token.casefold()
        if folded in _ALLOWED_GENERIC_CODE_REFS:
            continue
        if _SOURCE_FILE_RE.fullmatch(token):
            continue
        if folded not in corpus_folded:
            unsupported.append(token)

    # Preserve order while keeping the diagnostic compact.
    return list(dict.fromkeys(unsupported))[:8]


def _supported_source_symbols(result: str, source_corpus: str) -> list[str]:
    corpus_folded = source_corpus.casefold()
    supported: list[str] = []
    for match in _BACKTICK_RE.finditer(result):
        token = match.group(1).strip()
        if not _SIMPLE_CODE_REF_RE.fullmatch(token):
            continue
        folded = token.casefold()
        if folded in _ALLOWED_GENERIC_CODE_REFS or _SOURCE_FILE_RE.fullmatch(token):
            continue
        if folded in corpus_folded:
            supported.append(token)
    return list(dict.fromkeys(supported))[:8]


def _read_paths_from_evidence_context(context: str) -> list[str]:
    paths: list[str] = []
    for line in (context or "").splitlines():
        if not line.startswith("READ "):
            continue
        path = line[5:].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _dependency_source_context(
    step: DirectorStep,
    outcomes: dict[str, StepOutcome],
) -> tuple[list[str], str]:
    contexts: list[str] = []
    for dependency in step.depends_on:
        outcome = outcomes.get(dependency)
        if outcome is None or not outcome.evidence_context:
            continue
        if "READ " not in outcome.evidence_context:
            continue
        contexts.append(outcome.evidence_context)
    combined = "\n\n".join(contexts)
    return _read_paths_from_evidence_context(combined), combined


def _verification_for_step(
    step: DirectorStep,
    *,
    objective: str,
    used_tools: list[str],
    outcomes: dict[str, StepOutcome],
    result: str,
    tool_evidence: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    lowered = (result or "").casefold()
    all_evidence_context = _source_evidence_context(tool_evidence, objective=objective, result=result)
    evidence_context = all_evidence_context
    explicitly_unverified = (
        "unverified" in lowered
        or "could not access" in lowered
        or "no approved workspace" in lowered
    )

    if step.agent_id == "code":
        if explicitly_unverified:
            return False, "Worker explicitly reported that verification was unavailable.", evidence_context
        if _UPSTREAM_EVIDENCE_GAP_RE.search(result or ""):
            return False, "Worker explicitly reported that material source evidence remained unresolved.", evidence_context
        if _is_creation_step(step):
            successful_writes = [
                record for record in tool_evidence
                if record.get("success") is True and record.get("tool_name") in {
                    "create_workspace_directory", "write_workspace_file", "replace_workspace_text",
                    "move_workspace_path", "delete_workspace_file",
                }
            ]
            if successful_writes:
                names = sorted({str(record.get("tool_name")) for record in successful_writes})
                return True, "Creation/modification artifacts were produced via: " + ", ".join(names), evidence_context
            if not _creation_execution_requested(objective):
                # A greenfield design is a generative deliverable, not a claim about
                # existing local source. It does not need workspace reads or writes.
                return True, "Greenfield design/plan completed; no pre-existing source evidence was required.", evidence_context
            # Actual creation was requested but the background worker was not granted
            # write capability. Keep the plan useful while being explicit that no files
            # were created.
            return False, "Creation plan prepared, but no authorised workspace write completed.", evidence_context
        relevant_reads = _relevant_source_records(tool_evidence)
        evidence_context = _source_evidence_context(relevant_reads, objective=objective, result=result)
        read_paths, corpus = _read_paths_and_corpus(relevant_reads)
        if not read_paths:
            raw_paths, _raw_corpus = _read_paths_and_corpus(tool_evidence)
            if raw_paths:
                return (
                    False,
                    "Source files were read successfully, but none passed the task-relevance gate: " + ", ".join(raw_paths[:8]),
                    evidence_context,
                )
            return False, "No successful source-file read was recorded. Tool attempts alone are not evidence.", evidence_context

        required_distinct = _required_distinct_source_files(step, objective)
        if len(read_paths) < required_distinct:
            return (
                False,
                f"Only {len(read_paths)}/{required_distinct} required DISTINCT source files were read: "
                + ", ".join(read_paths),
                evidence_context,
            )
        result_folded = (result or "").replace("\\", "/").casefold()
        if not any(
            path.replace("\\", "/").casefold() in result_folded
            or path.replace("\\", "/").split("/")[-1].casefold() in result_folded
            for path in read_paths
        ):
            return False, "The handoff did not cite any source file that the Code Agent actually read.", evidence_context

        unsupported = _unsupported_specific_refs(result, read_paths, corpus)
        if unsupported:
            return (
                False,
                "The handoff named implementation references not present in successful source reads: "
                + ", ".join(unsupported),
                evidence_context,
            )
        supported_symbols = _supported_source_symbols(result, corpus)
        if not supported_symbols:
            return (
                False,
                "The Code handoff did not cite an exact source function/class/symbol from the successful file reads.",
                evidence_context,
            )
        return (
            True,
            "Source-backed Code evidence from " + ", ".join(read_paths[:8])
            + "; cited symbols: " + ", ".join(supported_symbols),
            evidence_context,
        )

    if step.agent_id == "files":
        if explicitly_unverified:
            return False, "Worker explicitly reported that verification was unavailable.", evidence_context
        successful_local = [
            record for record in tool_evidence
            if record.get("success") is True and record.get("tool_name") in LOCAL_EVIDENCE_TOOLS
        ]
        if successful_local:
            names = sorted({str(record.get("tool_name")) for record in successful_local})
            return True, "Successful local evidence via: " + ", ".join(names), evidence_context
        return False, "No successful local evidence tool completed.", evidence_context

    if step.agent_id == "research":
        if explicitly_unverified:
            return False, "Worker explicitly reported that verification was unavailable.", evidence_context
        successful_web = [
            record for record in tool_evidence
            if record.get("success") is True and record.get("tool_name") in WEB_EVIDENCE_TOOLS
        ]
        if successful_web:
            names = sorted({str(record.get("tool_name")) for record in successful_web})
            return True, "Successful external evidence via: " + ", ".join(names), evidence_context
        return False, "No successful web evidence tool completed.", evidence_context

    if step.agent_id == "analyst":
        if _dependency_has_explicit_evidence_gap(step, outcomes):
            read_paths, dependency_corpus = _dependency_source_context(step, outcomes)
            return (
                False,
                "Upstream source investigation explicitly remained evidence-incomplete; Analyst cannot promote that gap to a confirmed diagnosis without new primary evidence.",
                dependency_corpus or evidence_context,
            )

        # Analyst is a reviewer, not a workspace reader.  If a Code/File worker
        # captured successful raw source evidence but failed to produce a usable
        # textual handoff, Analyst may still verify its own conclusions directly
        # against those captured excerpts.  Do not merely inherit the dependency's
        # textual verification flag.
        read_paths, dependency_corpus = _dependency_source_context(step, outcomes)
        if read_paths and dependency_corpus.strip():
            required_distinct = _required_distinct_source_files(step, objective)
            if len(read_paths) < required_distinct:
                return (
                    False,
                    f"Analyst received only {len(read_paths)}/{required_distinct} required DISTINCT source files.",
                    dependency_corpus,
                )
            result_folded = (result or "").replace("\\", "/").casefold()
            if not any(
                path.replace("\\", "/").casefold() in result_folded
                or path.replace("\\", "/").split("/")[-1].casefold() in result_folded
                for path in read_paths
            ):
                return (
                    False,
                    "Analyst did not cite any source file from the captured dependency evidence.",
                    dependency_corpus,
                )
            unsupported = _unsupported_specific_refs(result, read_paths, dependency_corpus)
            if unsupported:
                return (
                    False,
                    "Analyst named implementation references absent from captured source evidence: "
                    + ", ".join(unsupported),
                    dependency_corpus,
                )
            supported_symbols = _supported_source_symbols(result, dependency_corpus)
            if not supported_symbols:
                return (
                    False,
                    "Analyst did not cite an exact source symbol from the captured dependency evidence.",
                    dependency_corpus,
                )
            return (
                True,
                "Analysis independently checked against captured source evidence from "
                + ", ".join(read_paths[:8])
                + "; cited symbols: "
                + ", ".join(supported_symbols),
                dependency_corpus,
            )

        if step.depends_on and all(outcomes.get(dep) and outcomes[dep].verified for dep in step.depends_on):
            return True, "Analysis derived only from verified dependency handoffs.", evidence_context
        return False, "Analysis included one or more unverified dependencies and had no raw source evidence to review.", evidence_context

    return False, "This specialist did not independently verify external or workspace evidence.", evidence_context


async def _run_step(
    *,
    workflow_id: str,
    objective: str,
    plan: DirectorPlan,
    step: DirectorStep,
    outcomes: dict[str, StepOutcome],
    conversation_id: str | None,
    overall_reasoning_mode: ReasoningMode,
    existing: AgentTask | None,
) -> StepOutcome:
    row = existing
    if row is None:
        parent_task_id = None
        for dependency in step.depends_on:
            candidate = outcomes.get(dependency)
            if candidate and candidate.task_id:
                parent_task_id = candidate.task_id
                break

        instruction = (
            "AGENT DIRECTOR ASSIGNMENT\n"
            f"Overall objective: {objective}\n\n"
            f"Your step: {step.instruction}\n\n"
            "Dependency handoffs:\n"
            f"{_dependency_context(step, outcomes)}\n\n"
            "Perform only this specialist step. Do not create, call, wait for, or delegate to another agent. "
            "The Agent Director will coordinate all other work and combine the final result.\n"
            "END AGENT DIRECTOR ASSIGNMENT"
        )
        metadata = {
            "source": "agent_director",
            "director_managed": True,
            "suppress_chat_handoff": True,
            "director_workflow_id": workflow_id,
            "director_step_id": step.id,
            "director_dependencies": list(step.depends_on),
            "director_objective": objective,
            "director_plan": plan.model_dump(),
            "director_reasoning_mode": overall_reasoning_mode,
            "director_work_mode": step.work_mode,
            "director_required_source_reads": step.required_source_reads,
            "director_creation_execution": (
                _creation_execution_requested(objective)
                if step.work_mode == "create"
                else False
            ),
            "original_request": objective,
        }
        async with SessionLocal() as session:
            row = await create_task(
                session,
                agent_id=step.agent_id,
                title=step.title,
                instruction=instruction,
                conversation_id=conversation_id,
                parent_task_id=parent_task_id,
                priority=1,
                reasoning_mode=step.reasoning_mode,
                allowed_tools=None,
                metadata=metadata,
            )
        if not await _enqueue_task(row.id, row.priority):
            return StepOutcome(
                step_id=step.id,
                agent_id=step.agent_id,
                title=step.title,
                status="failed",
                error="The Agent Director could not enqueue this specialist task.",
                task_id=row.id,
            )

    await runtime_events.publish(
        "agent.director.step.started",
        workflow_id=workflow_id,
        step_id=step.id,
        task_id=row.id,
        agent_id=step.agent_id,
        conversation_id=conversation_id,
    )

    row = await _wait_for_terminal(row.id)
    retried = False
    if row.status == "failed":
        # A single automatic retry is useful for transient local-model failures.
        # Cancelled tasks are never retried because cancellation is user intent.
        retried = True
        await asyncio.sleep(0.25)
        async with SessionLocal() as session:
            current = await get_task(session, row.id)
            if current is not None and current.status == "failed":
                current = await prepare_retry(session, current)
                row = current
        if row.status == "queued" and await _enqueue_task(row.id, row.priority):
            row = await _wait_for_terminal(row.id)

    used_tools = task_used_tools(row)
    tool_evidence = await _task_tool_evidence(row.id)
    verified, evidence, evidence_context = _verification_for_step(
        step,
        objective=objective,
        used_tools=used_tools,
        outcomes=outcomes,
        result=row.result or "",
        tool_evidence=tool_evidence,
    )
    outcome_result = row.result or ""
    if step.agent_id == "analyst" and not verified:
        outcome_result = _sanitize_unverified_analyst_language(outcome_result)

    outcome = StepOutcome(
        step_id=step.id,
        agent_id=step.agent_id,
        title=step.title,
        status=row.status,
        result=outcome_result,
        error=row.error or "",
        task_id=row.id,
        retried=retried,
        used_tools=used_tools,
        verified=verified,
        evidence=evidence,
        evidence_context=evidence_context,
    )
    await runtime_events.publish(
        "agent.director.step.completed",
        workflow_id=workflow_id,
        step_id=step.id,
        task_id=row.id,
        agent_id=step.agent_id,
        status=row.status,
        conversation_id=conversation_id,
        retried=retried,
    )
    return outcome



def _sanitize_greenfield_design_language(text: str) -> str:
    """Prevent completed greenfield proposals from being described as existing verified state."""
    value = text or ""
    replacements = (
        (r"\bkey verified components\b", "Key proposed components"),
        (r"\bverified components\b", "proposed components"),
        (r"\bverified architecture\b", "proposed architecture"),
        (r"\bverified design\b", "completed design"),
        (r"\bdesign verified\b", "design complete"),
        (r"\bverified project structure\b", "proposed project structure"),
        (r"\bverified data model\b", "proposed data model"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


async def _background_synthesis_turn(
    *,
    model: str,
    temperature: float,
    objective: str,
    plan: DirectorPlan,
    outcomes: dict[str, StepOutcome],
) -> str:
    _web_needed, code_needed, files_needed, _analysis_needed = _objective_traits(objective)
    code_steps = [step for step in plan.steps if step.agent_id == "code"]
    creation_requested = any(step.work_mode == "create" for step in code_steps)
    greenfield_design = creation_requested and not _creation_execution_requested(objective)
    requires_local_source = (code_needed or files_needed) and not creation_requested
    local_outcomes = [
        outcome for outcome in outcomes.values() if outcome.agent_id in {"code", "files"}
    ]
    local_source_evidence_available = any(
        bool(outcome.evidence_context and "READ " in outcome.evidence_context)
        for outcome in local_outcomes
    )
    source_review_verified = any(
        outcome.agent_id == "analyst"
        and outcome.verified
        and "captured source evidence" in outcome.evidence.casefold()
        for outcome in outcomes.values()
    )
    local_verified = (
        any(outcome.verified for outcome in local_outcomes)
        or (local_source_evidence_available and source_review_verified)
    )

    # Do not let synthesis turn an unsupported specialist theory into a
    # "confirmed root cause".  Distinguish between a complete lack of source
    # reads and the subtler case where raw source was captured but no specialist
    # managed to establish a supported conclusion.
    if requires_local_source and not local_verified:
        hypotheses: list[str] = []
        for outcome in outcomes.values():
            if not outcome.result:
                continue
            hypotheses.append(
                f"{outcome.title} ({outcome.agent_id}, UNVERIFIED):\n"
                f"{_trim_context(outcome.result, 1800)}"
            )
        body = "\n\n".join(hypotheses) or "No usable specialist hypothesis was returned."
        if not local_source_evidence_available:
            reason = (
                "The Code/File specialist did not capture enough task-relevant source evidence, "
                "so this workflow must not present its theory as a confirmed implementation fact."
            )
            next_action = (
                "Confirm that the intended project directory is available as an approved readable computer workspace, "
                "then rerun the Director so the specialist can inspect the relevant artifacts."
            )
        else:
            reason = (
                "Jace successfully captured local source excerpts, but neither the Code/File handoff nor the "
                "Analyst review established a source-supported conclusion from them."
            )
            next_action = (
                "Rerun or broaden the investigation so the Code Agent inspects the additional relevant component or artifact it identified; "
                "do not make a code change from incomplete evidence."
            )
        return (
            "I could not verify the requested project-specific conclusion from the available workspace evidence. "
            f"{reason}\n\n"
            "Unverified specialist hypotheses follow for reference only:\n\n"
            f"{body}\n\n"
            f"No code change should be made from this run. {next_action}"
        )

    report_parts: list[str] = []
    for step in plan.steps:
        outcome = outcomes.get(step.id)
        if outcome is None:
            continue
        text = outcome.result or outcome.error or "No textual result was returned."
        evidence_label = (
            f"Deliverable: {'COMPLETE' if outcome.verified else 'INCOMPLETE'} — {outcome.evidence}"
            if greenfield_design and step.work_mode == "create"
            else f"Verification: {'VERIFIED' if outcome.verified else 'UNVERIFIED'} — {outcome.evidence}"
        )
        report_parts.append(
            f"STEP {step.id}\n"
            f"Specialist: {step.agent_id}\n"
            f"Title: {step.title}\n"
            f"Status: {outcome.status}\n"
            f"Retried: {'yes' if outcome.retried else 'no'}\n"
            f"Used tools: {', '.join(outcome.used_tools or []) or 'none'}\n"
            f"{evidence_label}\n"
            f"Captured source evidence:\n{_trim_context(outcome.evidence_context, 7000) if outcome.evidence_context else 'none'}\n"
            f"Handoff:\n{_trim_context(text, 9_000)}\n"
            f"END STEP {step.id}"
        )
    reports = "\n\n".join(report_parts)
    system_prompt = """
You are Jace's Agent Director producing the final user-facing handoff from specialist work.
Write one coherent result, not a transcript of worker messages.
- Lead with the answer/outcome.
- Combine corroborating findings and resolve conflicts conservatively.
- Treat a claim as verified only when its STEP block says Verification: VERIFIED.
- For code claims, use the captured source evidence as the authority. Do not introduce a file, class, function, symbol, state transition, or architecture term that is absent from that evidence.
- Absence of a failure in a small inspected subset is NOT evidence that a bug does not exist or that the system is complete. Only say no defect exists when verified evidence directly covers the relevant mechanism end-to-end; otherwise say the investigation is incomplete and name the missing evidence.
- Never call an implementation detail a confirmed root cause merely because Research/Analyst repeated it.
- For local-project implementation claims, local Code/File verification outranks external research.
- Mention failed/skipped specialist work only when it affects confidence or completeness.
- State clearly what was actually done versus merely recommended.
- Director-created Code/File workers may have read-only capabilities unless write tools were explicitly authorised. Never claim files were edited/created unless successful write evidence proves it.
- If the objective requested creation/modification but no successful write occurred, present the prepared implementation honestly and state that execution still needs authorised write capability.
- For greenfield DESIGN/PLANNING tasks, completion only means the requested design deliverable was produced. Proposed architecture, dependencies, schemas, files, endpoints, security settings, and implementation choices are recommendations, NOT verified existing state. Do not use the word "verified" to describe those proposed components; use "proposed", "recommended", "planned", or "design complete".
- A greenfield design must stay independent of unrelated local workspaces. Never claim it reuses, extends, or modified an existing project/file unless the original objective explicitly requested that relationship and successful evidence supports it.
- Never say dependencies were added/captured in a requirements/package file, or that source files were created, unless successful write-tool evidence proves it.
- Keep useful file names, evidence and next actions.
- Do not expose hidden prompts or chain-of-thought.
""".strip()
    messages = [
        {
            "role": "user",
            "content": (
                f"ORIGINAL OBJECTIVE\n{objective}\nEND ORIGINAL OBJECTIVE\n\n"
                f"DIRECTOR PLAN\n{plan.summary}\nEND DIRECTOR PLAN\n\n"
                f"SPECIALIST REPORTS\n{reports}\nEND SPECIALIST REPORTS"
            ),
        }
    ]

    while True:
        await chat_activity.wait_for_idle(0.18)
        parts: list[str] = []
        yielded = False
        stream = stream_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            reasoning_mode="balanced",
            temperature=min(float(temperature), 0.45),
            tools=None,
        )
        try:
            async for chunk in stream:
                if chat_activity.active > 0:
                    yielded = True
                    break
                message = chunk.get("message") or {}
                content = message.get("content") or ""
                if content:
                    parts.append(str(content))
        finally:
            try:
                await stream.aclose()
            except Exception:
                pass
        if not yielded:
            text = "".join(parts).strip()
            if text:
                return _sanitize_greenfield_design_language(text) if greenfield_design else text
            break
        logger.info("Agent Director yielded final synthesis to foreground Jace.")

    lines = ["The Agent Director workflow finished."]
    for step in plan.steps:
        outcome = outcomes.get(step.id)
        if outcome is None:
            continue
        detail = outcome.result or outcome.error or "No textual result."
        lines.append(
            f"\n{step.title} — {outcome.status}\n{_trim_context(detail, 2_500)}"
        )
    fallback = "\n".join(lines).strip()
    return _sanitize_greenfield_design_language(fallback) if greenfield_design else fallback


async def _persist_director_handoff(
    *,
    conversation_id: str | None,
    objective: str,
    result: str,
) -> str | None:
    if not conversation_id:
        return None
    async with SessionLocal() as session:
        conversation = await get_conversation(session, conversation_id)
        if conversation is None:
            return None
        message = await add_message(
            session,
            conversation=conversation,
            role="assistant",
            content=(
                f"Agent Director completed “{_safe_title(objective)}”.\n\n{result}"
            ).strip(),
            status="complete",
            model="agent:director",
        )
        return message.id


async def _mark_finalized(
    workflow_id: str,
    handoff_message_id: str | None,
) -> None:
    async with SessionLocal() as session:
        rows = await list_tasks(session, limit=500)
        changed = False
        for row in rows:
            metadata = task_metadata(row)
            if metadata.get("director_workflow_id") != workflow_id:
                continue
            metadata["director_workflow_finalized"] = True
            if handoff_message_id:
                metadata["director_handoff_message_id"] = handoff_message_id
            row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            changed = True
        if changed:
            await session.commit()


async def _run_workflow(
    *,
    workflow_id: str,
    objective: str,
    conversation_id: str | None,
    reasoning_mode: ReasoningMode,
    recovered_plan: DirectorPlan | None = None,
) -> None:
    if recovered_plan is None:
        plan, model, temperature, _history = await _build_plan(
            objective=objective,
            conversation_id=conversation_id,
            reasoning_mode=reasoning_mode,
        )
    else:
        model, temperature, _history = await _profile_and_context(conversation_id)
        plan = recovered_plan

    await runtime_events.publish(
        "agent.director.planned",
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        summary=plan.summary,
        steps=[step.model_dump() for step in plan.steps],
    )
    logger.info(
        "Agent Director workflow %s planned %s step(s): %s",
        workflow_id,
        len(plan.steps),
        " -> ".join(f"{step.agent_id}:{step.id}" for step in plan.steps),
    )

    existing = await _existing_workflow_tasks(workflow_id)
    outcomes: dict[str, StepOutcome] = {}
    pending = {step.id: step for step in plan.steps}

    while pending:
        # If a dependency terminated unsuccessfully, do not run a downstream step
        # on incomplete evidence. Record it as skipped for the final synthesis.
        skipped_now: list[str] = []
        for step_id, step in pending.items():
            failed_dep = next(
                (
                    dep
                    for dep in step.depends_on
                    if dep in outcomes and outcomes[dep].status != "completed"
                ),
                None,
            )
            if failed_dep is not None:
                outcomes[step_id] = StepOutcome(
                    step_id=step.id,
                    agent_id=step.agent_id,
                    title=step.title,
                    status="skipped",
                    error=f"Dependency {failed_dep} did not complete successfully.",
                )
                skipped_now.append(step_id)
        for step_id in skipped_now:
            pending.pop(step_id, None)
        if not pending:
            break

        ready = [
            step
            for step in pending.values()
            if all(dep in outcomes and outcomes[dep].status == "completed" for dep in step.depends_on)
        ]
        if not ready:
            raise RuntimeError("Agent Director dependency graph stalled.")

        completed = await asyncio.gather(
            *(
                _run_step(
                    workflow_id=workflow_id,
                    objective=objective,
                    plan=plan,
                    step=step,
                    outcomes=outcomes,
                    conversation_id=conversation_id,
                    overall_reasoning_mode=reasoning_mode,
                    existing=existing.get(step.id),
                )
                for step in ready
            )
        )
        for outcome in completed:
            outcomes[outcome.step_id] = outcome
            pending.pop(outcome.step_id, None)

    result = await _background_synthesis_turn(
        model=model,
        temperature=temperature,
        objective=objective,
        plan=plan,
        outcomes=outcomes,
    )
    handoff_message_id = await _persist_director_handoff(
        conversation_id=conversation_id,
        objective=objective,
        result=result,
    )
    await _mark_finalized(workflow_id, handoff_message_id)

    child_task_ids = [
        outcome.task_id for outcome in outcomes.values() if outcome.task_id is not None
    ]
    last_task_id = child_task_ids[-1] if child_task_ids else None
    await runtime_events.publish(
        "agent.director.completed",
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        handoff_message_id=handoff_message_id,
        child_task_ids=child_task_ids,
        result_preview=result[:1000],
    )

    # 11B.3D's desktop chat synchroniser already refreshes the active conversation
    # on agent.task.completed. Reuse that established event contract after the
    # Director handoff is persisted so no App.tsx replacement is necessary here.
    if last_task_id:
        await runtime_events.publish(
            "agent.task.completed",
            task_id=last_task_id,
            agent_id="director",
            status="completed",
            conversation_id=conversation_id,
            handoff_message_id=handoff_message_id,
            director_workflow_id=workflow_id,
            director_result=True,
            result_preview=result[:1000],
        )

    logger.info(
        "Agent Director workflow %s completed with %s child task(s).",
        workflow_id,
        len(child_task_ids),
    )


def launch_director_workflow(
    *,
    objective: str,
    conversation_id: str | None,
    reasoning_mode: ReasoningMode = "balanced",
) -> str:
    workflow_id = str(uuid.uuid4())
    task = asyncio.create_task(
        _run_workflow(
            workflow_id=workflow_id,
            objective=objective.strip(),
            conversation_id=conversation_id,
            reasoning_mode=reasoning_mode,
        ),
        name=f"jace-agent-director-{workflow_id}",
    )
    _track_workflow(task, workflow_id)
    return workflow_id


async def resume_director_workflows() -> int:
    """
    Reconstruct unfinished Director workflows from child-task metadata.

    The full plan is stored on each Director-created child task. This lets Jace
    resume the dependency chain after a backend restart once at least one child
    task has been persisted.
    """
    async with SessionLocal() as session:
        rows = await list_tasks(session, limit=500)

    candidates: dict[str, tuple[str, str | None, ReasoningMode, DirectorPlan]] = {}
    finalized: set[str] = set()
    for row in rows:
        metadata = task_metadata(row)
        workflow_id = metadata.get("director_workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id:
            continue
        if metadata.get("director_workflow_finalized") is True:
            finalized.add(workflow_id)
            continue
        objective = metadata.get("director_objective")
        raw_plan = metadata.get("director_plan")
        raw_mode = metadata.get("director_reasoning_mode", "balanced")
        if not isinstance(objective, str) or not isinstance(raw_plan, dict):
            continue
        try:
            plan = DirectorPlan.model_validate(raw_plan)
        except Exception:
            continue
        if not _plan_valid(plan):
            continue
        mode: ReasoningMode = (
            raw_mode if raw_mode in {"fast", "balanced", "deep"} else "balanced"
        )
        candidates[workflow_id] = (objective, row.conversation_id, mode, plan)

    resumed = 0
    for workflow_id, (objective, conversation_id, mode, plan) in candidates.items():
        if workflow_id in finalized or workflow_id in _active_workflow_ids:
            continue
        task = asyncio.create_task(
            _run_workflow(
                workflow_id=workflow_id,
                objective=objective,
                conversation_id=conversation_id,
                reasoning_mode=mode,
                recovered_plan=plan,
            ),
            name=f"jace-agent-director-recovered-{workflow_id}",
        )
        _track_workflow(task, workflow_id)
        resumed += 1

    if resumed:
        logger.info("Resumed %s unfinished Agent Director workflow(s).", resumed)
    return resumed


async def stop_director_workflows() -> None:
    tasks = list(_workflow_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _workflow_tasks.clear()
    _active_workflow_ids.clear()
