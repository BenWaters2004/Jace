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
    get_task,
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


def _objective_traits(objective: str) -> tuple[bool, bool, bool, bool]:
    """Classify only the current objective.

    Recent conversation history is useful context for workers, but it must not
    accidentally trigger a Research/Code/File route because an older message
    happened to contain words such as "current", "web", or "file".
    """
    text = (objective or "").casefold()
    web_needed = bool(
        re.search(
            r"\b(?:latest|current external|today|online|web|internet|public source|"
            r"public sources|release notes|upstream documentation|official documentation|news)\b",
            text,
        )
    )
    code_needed = bool(
        re.search(
            r"\b(?:code|bug|debug|error|repo|repository|typescript|javascript|python|"
            r"php|laravel|react|rust|tauri|backend|frontend|api|app\.tsx|fix|"
            r"implementation|compile|build|source|handoff system|jace project)\b",
            text,
        )
    )
    files_needed = bool(
        re.search(r"\b(?:file|files|folder|directory|workspace|path|organise|organize)\b", text)
    )
    analysis_needed = bool(
        re.search(
            r"\b(?:analyse|analyze|assess|compare|evaluate|decide|root cause|diagnos|"
            r"investigate|why|best fix|recommend)\w*",
            text,
        )
    )
    return web_needed, code_needed, files_needed, analysis_needed


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
                "Use authoritative sources and include the exact URLs or source names supporting "
                "material claims. Do not infer Jace's local implementation from generic agent "
                "framework articles or unrelated projects."
            ),
            reasoning_mode="balanced",
        ))

    if "code" in selected:
        steps.append(DirectorStep(
            id="code",
            agent_id="code",
            title="Inspect the Jace source and establish the actual behaviour",
            instruction=(
                "Inspect the approved Jace workspace before reaching a conclusion. Search for the "
                "relevant implementation, read the surrounding files, and identify the actual data "
                "flow. Cite concrete file paths/functions from tool output. Explicitly say UNVERIFIED "
                "if the Jace workspace is unavailable or you cannot inspect the relevant source. "
                "Prepare the smallest coherent fix, but do not claim files were modified because "
                "Director-created Code tasks are read-only by default."
            ),
            reasoning_mode="deep",
        ))

    if "files" in selected:
        steps.append(DirectorStep(
            id="files",
            agent_id="files",
            title="Inspect the relevant workspace files",
            instruction=(
                "Inspect the approved workspace and support every project-specific claim with concrete "
                "paths or file contents obtained through workspace tools. Say UNVERIFIED if the "
                "workspace is unavailable."
            ),
            reasoning_mode="balanced",
        ))

    if "analyst" in selected:
        deps = [step.id for step in steps if step.agent_id in {"research", "code", "files"}]
        steps.append(DirectorStep(
            id="analysis",
            agent_id="analyst",
            title="Review the evidence and recommend the best fix",
            instruction=(
                "Review only the supplied specialist evidence. Separate verified source-backed facts "
                "from hypotheses. Never promote an upstream specialist's unsupported claim to a "
                "confirmed fact. If Code/File could not inspect the local source, state that the local "
                "root cause remains unverified."
            ),
            depends_on=deps,
            reasoning_mode="balanced",
        ))

    if "general" in selected and not steps:
        steps.append(DirectorStep(
            id="general",
            agent_id="general",
            title="Complete the directed background objective",
            instruction="Complete the objective methodically and label assumptions clearly.",
            reasoning_mode="balanced",
        ))

    # If selection somehow reduced to nothing after de-duplication, stay useful.
    if not steps:
        steps.append(DirectorStep(
            id="analysis",
            agent_id="analyst",
            title="Analyse the objective",
            instruction="Analyse the objective conservatively and distinguish facts from assumptions.",
            reasoning_mode="balanced",
        ))

    summary = (rationale or "Director route constructed with deterministic evidence guardrails.").strip()
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
- code: inspect and diagnose an approved software workspace
- files: inspect/organise approved local files
- analyst: review evidence and synthesize conclusions
- general: background work that fits none of the above

Rules:
- Use 1-{MAX_DIRECTOR_STEPS} IDs.
- For a bug or implementation question about the local Jace project, include code.
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
        chunks.append(
            f"DEPENDENCY {dependency} ({outcome.agent_id}, {outcome.status})\n"
            f"Verification: {'VERIFIED' if outcome.verified else 'UNVERIFIED'} — {outcome.evidence}\n"
            f"{_trim_context(body, DIRECTOR_RESULT_CONTEXT_CHARS)}\n"
            f"END DEPENDENCY {dependency}"
        )
    return "\n\n".join(chunks)


LOCAL_EVIDENCE_TOOLS = {
    "read_workspace_file",
    "search_workspace_files",
    "workspace_file_info",
    "inspect_workspace_media",
}
WEB_EVIDENCE_TOOLS = {"web_search", "read_web_page", "browser_read_page"}


def _verification_for_step(
    step: DirectorStep,
    *,
    used_tools: list[str],
    outcomes: dict[str, StepOutcome],
    result: str,
) -> tuple[bool, str]:
    tools = set(used_tools)
    lowered = (result or "").casefold()
    if "unverified" in lowered or "could not access" in lowered or "no approved workspace" in lowered:
        return False, "Worker explicitly reported that verification was unavailable."
    if step.agent_id in {"code", "files"}:
        hits = sorted(tools & LOCAL_EVIDENCE_TOOLS)
        if hits:
            return True, "Local workspace evidence via: " + ", ".join(hits)
        return False, "No source-reading workspace tool was used."
    if step.agent_id == "research":
        hits = sorted(tools & WEB_EVIDENCE_TOOLS)
        if hits:
            return True, "External evidence via: " + ", ".join(hits)
        return False, "No web evidence tool was used."
    if step.agent_id == "analyst":
        if step.depends_on and all(outcomes.get(dep) and outcomes[dep].verified for dep in step.depends_on):
            return True, "Analysis derived only from verified dependency handoffs."
        return False, "Analysis included one or more unverified dependencies."
    return False, "This specialist did not independently verify external or workspace evidence."


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
    verified, evidence = _verification_for_step(
        step,
        used_tools=used_tools,
        outcomes=outcomes,
        result=row.result or "",
    )
    outcome = StepOutcome(
        step_id=step.id,
        agent_id=step.agent_id,
        title=step.title,
        status=row.status,
        result=row.result or "",
        error=row.error or "",
        task_id=row.id,
        retried=retried,
        used_tools=used_tools,
        verified=verified,
        evidence=evidence,
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


async def _background_synthesis_turn(
    *,
    model: str,
    temperature: float,
    objective: str,
    plan: DirectorPlan,
    outcomes: dict[str, StepOutcome],
) -> str:
    _web_needed, code_needed, files_needed, _analysis_needed = _objective_traits(objective)
    requires_local_source = code_needed or files_needed
    local_outcomes = [
        outcome for outcome in outcomes.values() if outcome.agent_id in {"code", "files"}
    ]
    local_verified = any(outcome.verified for outcome in local_outcomes)

    # Do not let synthesis turn an unsupported specialist theory into a
    # "confirmed root cause". If local source inspection was required but never
    # actually happened, return a deterministic failure-to-verify handoff.
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
        return (
            "I could not verify the requested Jace root cause in the actual source code. "
            "The Code/File specialist did not successfully use a source-reading workspace tool, "
            "so this workflow must not present its theory as a confirmed implementation fact.\n\n"
            "Unverified specialist hypotheses follow for reference only:\n\n"
            f"{body}\n\n"
            "No code change should be made from this run. Confirm that the Jace repository is "
            "available as an approved computer workspace, then rerun the Director so the Code "
            "Agent can inspect the relevant files and cite concrete paths/functions."
        )

    report_parts: list[str] = []
    for step in plan.steps:
        outcome = outcomes.get(step.id)
        if outcome is None:
            continue
        text = outcome.result or outcome.error or "No textual result was returned."
        report_parts.append(
            f"STEP {step.id}\n"
            f"Specialist: {step.agent_id}\n"
            f"Title: {step.title}\n"
            f"Status: {outcome.status}\n"
            f"Retried: {'yes' if outcome.retried else 'no'}\n"
            f"Used tools: {', '.join(outcome.used_tools or []) or 'none'}\n"
            f"Verification: {'VERIFIED' if outcome.verified else 'UNVERIFIED'} — {outcome.evidence}\n"
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
- Never call an implementation detail a confirmed root cause merely because Research/Analyst repeated it.
- For Jace/local-project implementation claims, local Code/File verification outranks external research.
- Mention failed/skipped specialist work only when it affects confidence or completeness.
- State clearly what was actually done versus merely recommended.
- Director-created Code/File workers receive safe read-only defaults. Never claim source files were edited unless a worker result explicitly proves a write occurred.
- If the objective requested a source-code/file modification but only diagnosis was possible, say that the exact fix is prepared but write-capable execution still requires Jace's normal explicit approval path.
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
                return text
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
    return "\n".join(lines).strip()


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
