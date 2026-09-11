import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from jace.ai.engine import structured_chat
from jace.ai.prompts import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    MEMORY_RECONCILIATION_SYSTEM_PROMPT,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.memory.service import (
    create_memory,
    normalize_project_subject,
    search_memories,
    update_memory,
)
from jace.performance import chat_activity
from jace.schemas import (
    ExtractedMemoryCandidate,
    MemoryExtractionResult,
    MemoryReconciliationResult,
)

logger = logging.getLogger("uvicorn.error")


AGENT_MEMORY_EXTRACTION_SYSTEM_PROMPT = """You are the long-term memory curator for Jace.
The input is a completed BACKGROUND AGENT handoff, not a user-authored statement.
Extract only durable findings that will materially help future work on the user's own projects, environment, codebase, configuration, or ongoing tasks.
Rules:
1. Store only information directly supported by the completed agent result. Do not invent missing details.
2. Do not store generic reference knowledge, tutorials, explanations, or facts that are not specific to the user's ongoing work.
3. Do not store transient execution narration such as searching, reading, waiting, tool names, temporary progress, or task-complete messages.
4. Do not infer the user's preferences, goals, personal facts, or decisions from an agent's suggestion. Agent-derived memories should normally use project, fact, other, or temporary.
5. A recommendation is not a user decision. Only store the discovered condition/problem/fact, not an unapproved recommendation as if it were adopted.
6. Prefer project memories when a named user project is clearly involved. Keep named projects distinct.
7. Keep each memory atomic, concise, and understandable without the original task.
8. Never store passwords, passcodes, authentication tokens, API keys, private keys, recovery codes, card details, bank details, credentials, or secret values.
9. If the result is uncertain or speculative, either lower confidence appropriately or omit it.
10. Return an empty memories list when the agent found nothing durable and project-specific enough to retain.
Importance ranges 0..1: 0 trivial, 0.5 potentially useful, 0.8 important, 1 critical.
Confidence ranges 0..1 and represents how strongly the completed result supports the finding."""


@dataclass
class MemoryCommand:
    action: str
    content: str
    forget_all: bool = False


@dataclass
class MemoryActionResult:
    action: str
    subject: str | None = None
    memory_id: str | None = None
    target_memory_id: str | None = None
    detail: str = ""


_background_tasks: set[asyncio.Task] = set()
_extraction_lock = asyncio.Lock()

SECRET_PATTERNS = [
    r"\bpassword\s*(?:is|=|:)",
    r"\bpasscode\s*(?:is|=|:)",
    r"\bapi[\s_-]*key\s*(?:is|=|:)",
    r"\b(?:access|refresh)[\s_-]*token\s*(?:is|=|:)",
    r"\bprivate[\s_-]*key\s*(?:is|=|:)",
    r"\brecovery[\s_-]*code\s*(?:is|=|:)",
    r"\bsecret[\s_-]*key\s*(?:is|=|:)",
    r"\b(?:credit|debit)[\s_-]*card\s*(?:number\s*)?(?:is|=|:)",
    r"\bbank[\s_-]*account\s*(?:number\s*)?(?:is|=|:)",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]


def contains_secret_request(text: str) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in SECRET_PATTERNS
    )


def _clip_for_memory(text: str, max_chars: int) -> str:
    """Keep memory-curation prompts bounded without throwing away the ending."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    if max_chars < 800:
        return text[:max_chars]
    head = int(max_chars * 0.70)
    tail = max_chars - head
    return (
        text[:head]
        + "\n\n[...content clipped for memory extraction...]\n\n"
        + text[-tail:]
    )


def detect_memory_command(message: str) -> MemoryCommand | None:
    text = message.strip()
    remember_patterns = [
        r"^\s*(?:please\s+)?remember\s+that\s+(.+)$",
        r"^\s*(?:please\s+)?remember\s*:\s*(.+)$",
        r"^\s*(?:please\s+)?remember\s+this\s*[:,-]\s*(.+)$",
        r"^\s*(?:please\s+)?(?:save|store)\s+(?:this|that)\s+(?:to|in)\s+memory\s*[:,-]?\s*(.+)$",
    ]
    for pattern in remember_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return MemoryCommand(action="remember", content=match.group(1).strip())

    match = re.match(
        r"^\s*(?:please\s+)?forget\s+(?:everything|all)\s+about\s+(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return MemoryCommand(
            action="forget",
            content=match.group(1).strip(),
            forget_all=True,
        )

    forget_patterns = [
        r"^\s*(?:please\s+)?forget\s+that\s+(.+)$",
        r"^\s*(?:please\s+)?forget\s*:\s*(.+)$",
        r"^\s*(?:please\s+)?(?:remove|delete)\s+(?:the\s+)?memory\s+(?:that|about)\s+(.+)$",
    ]
    for pattern in forget_patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return MemoryCommand(action="forget", content=match.group(1).strip())
    return None


async def extract_candidates(
    *,
    user_message: str,
    assistant_message: str = "",
    explicit: bool = False,
) -> list[ExtractedMemoryCandidate]:
    if contains_secret_request(user_message):
        return []

    bounded_user = _clip_for_memory(user_message, 10_000)
    bounded_assistant = _clip_for_memory(assistant_message, 6_000)

    prompt = f"""Analyse this exchange for long-term memory.

Explicit memory request: {"yes" if explicit else "no"}

USER:
{bounded_user}

ASSISTANT RESPONSE FOR CONTEXT ONLY:
{bounded_assistant}

Only information established by the USER may become memory."""

    result = await structured_chat(
        model=settings.memory_extraction_model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
        response_model=MemoryExtractionResult,
    )

    logger.info("Memory extractor proposed %d candidate(s)", len(result.memories))
    filtered: list[ExtractedMemoryCandidate] = []
    for candidate in result.memories[: settings.memory_max_candidates]:
        logger.info(
            "Memory proposal: type=%s subject=%r importance=%.2f confidence=%.2f content=%r",
            candidate.memory_type,
            candidate.subject,
            candidate.importance,
            candidate.confidence,
            candidate.content,
        )
        if contains_secret_request(candidate.content):
            continue
        if explicit:
            candidate.confidence = max(candidate.confidence, 0.95)
            candidate.importance = max(candidate.importance, 0.70)
            filtered.append(candidate)
            continue
        if candidate.importance < settings.memory_min_importance:
            continue
        if candidate.confidence < settings.memory_min_confidence:
            continue
        filtered.append(candidate)

    logger.info(
        "Memory extractor accepted %d/%d candidate(s)",
        len(filtered),
        len(result.memories),
    )
    return filtered


async def extract_agent_candidates(
    *,
    agent_name: str,
    task_title: str,
    task_instruction: str,
    agent_result: str,
    used_tools: list[str] | None = None,
) -> list[ExtractedMemoryCandidate]:
    """
    Curate durable project/environment findings from a completed background
    specialist. This path is intentionally stricter than normal user-memory
    extraction because an agent result is evidence, not user authority.
    """
    result_text = _clip_for_memory(agent_result, 12_000)
    instruction_text = _clip_for_memory(task_instruction, 4_000)
    tool_text = ", ".join(sorted(set(used_tools or []))) or "none"

    prompt = f"""Analyse this completed background-agent handoff for durable long-term memory.

AGENT: {agent_name}
TASK TITLE: {task_title}
TASK INSTRUCTION:
{instruction_text}

TOOLS USED: {tool_text}

COMPLETED AGENT RESULT:
{result_text}

Only retain durable, project-specific or environment-specific findings that the completed result actually supports."""

    result = await structured_chat(
        model=settings.memory_extraction_model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=AGENT_MEMORY_EXTRACTION_SYSTEM_PROMPT,
        response_model=MemoryExtractionResult,
    )

    logger.info(
        "Agent memory extractor proposed %d candidate(s) for %s",
        len(result.memories),
        agent_name,
    )

    filtered: list[ExtractedMemoryCandidate] = []
    min_agent_confidence = max(settings.memory_min_confidence, 0.75)

    for candidate in result.memories[: settings.memory_max_candidates]:
        logger.info(
            "Agent memory proposal: agent=%s type=%s subject=%r importance=%.2f confidence=%.2f content=%r",
            agent_name,
            candidate.memory_type,
            candidate.subject,
            candidate.importance,
            candidate.confidence,
            candidate.content,
        )

        if contains_secret_request(candidate.content):
            continue

        # Background specialists may discover facts about the user's projects,
        # but they cannot authoritatively decide what the user prefers/wants.
        if candidate.memory_type in {"preference", "decision", "goal"}:
            logger.info(
                "Agent memory proposal rejected because agents cannot establish user %s memories.",
                candidate.memory_type,
            )
            continue

        if candidate.importance < settings.memory_min_importance:
            continue
        if candidate.confidence < min_agent_confidence:
            continue
        filtered.append(candidate)

    logger.info(
        "Agent memory extractor accepted %d/%d candidate(s) for %s",
        len(filtered),
        len(result.memories),
        agent_name,
    )
    return filtered


def reconciliation_prompt(candidate: ExtractedMemoryCandidate, hits) -> str:
    existing = []
    for hit in hits:
        memory = hit.memory
        existing.append(
            f"ID: {memory.id}\n"
            f"Type: {memory.memory_type}\n"
            f"Subject: {memory.subject}\n"
            f"Content: {memory.content}\n"
            f"Importance: {memory.importance:.2f}\n"
            f"Confidence: {memory.confidence:.2f}\n"
            f"Similarity: {hit.similarity:.4f}"
        )
    return f"""PROPOSED MEMORY
Type: {candidate.memory_type}
Subject: {candidate.subject}
Content: {candidate.content}
Importance: {candidate.importance}
Confidence: {candidate.confidence}
RELATED EXISTING MEMORIES
{"\n---\n".join(existing)}"""


async def reconcile_candidate(
    session: AsyncSession,
    *,
    candidate: ExtractedMemoryCandidate,
    source_type: str,
    source_conversation_id: str | None,
    source_message_id: str | None,
) -> MemoryActionResult:
    search_text = f"{candidate.subject}. {candidate.content}"
    hits = await search_memories(
        session,
        search_text,
        limit=settings.memory_reconcile_limit,
        min_similarity=settings.memory_reconcile_min_similarity,
        update_access=False,
    )

    # Deterministic entity guard in addition to the prompt-level rule.
    if candidate.memory_type == "project":
        entity = normalize_project_subject(candidate.subject)
        hits = [
            hit
            for hit in hits
            if hit.memory.memory_type == "project"
            and normalize_project_subject(hit.memory.subject) == entity
        ]

    if not hits:
        memory = await create_memory(
            session,
            memory_type=candidate.memory_type,
            subject=candidate.subject,
            content=candidate.content,
            importance=candidate.importance,
            confidence=candidate.confidence,
            source_type=source_type,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
        )
        return MemoryActionResult(
            action="created",
            subject=memory.subject,
            memory_id=memory.id,
            detail="Created a new memory.",
        )

    reconciliation = await structured_chat(
        model=settings.memory_extraction_model,
        messages=[
            {
                "role": "user",
                "content": reconciliation_prompt(candidate, hits),
            }
        ],
        system_prompt=MEMORY_RECONCILIATION_SYSTEM_PROMPT,
        response_model=MemoryReconciliationResult,
    )

    allowed_targets = {hit.memory.id: hit.memory for hit in hits}
    target = (
        allowed_targets.get(reconciliation.target_memory_id)
        if reconciliation.target_memory_id
        else None
    )

    if reconciliation.action in {"duplicate", "merge", "supersede"} and target is None:
        reconciliation.action = "create"

    if reconciliation.action == "ignore":
        return MemoryActionResult(
            action="ignored",
            subject=candidate.subject,
            detail=reconciliation.reason,
        )

    if reconciliation.action == "duplicate" and target:
        return MemoryActionResult(
            action="duplicate",
            subject=target.subject,
            memory_id=target.id,
            detail=reconciliation.reason,
        )

    if reconciliation.action == "merge" and target:
        updated = await update_memory(
            session,
            target,
            memory_type=reconciliation.memory_type,
            subject=reconciliation.subject,
            content=reconciliation.content,
            importance=max(target.importance, reconciliation.importance),
            confidence=max(target.confidence, reconciliation.confidence),
        )
        return MemoryActionResult(
            action="merged",
            subject=updated.subject,
            memory_id=updated.id,
            target_memory_id=target.id,
            detail=reconciliation.reason,
        )

    if reconciliation.action == "supersede" and target:
        await update_memory(session, target, is_active=False)
        replacement = await create_memory(
            session,
            memory_type=reconciliation.memory_type,
            subject=reconciliation.subject,
            content=reconciliation.content,
            importance=reconciliation.importance,
            confidence=reconciliation.confidence,
            source_type=source_type,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
        )
        return MemoryActionResult(
            action="superseded",
            subject=replacement.subject,
            memory_id=replacement.id,
            target_memory_id=target.id,
            detail=reconciliation.reason,
        )

    memory = await create_memory(
        session,
        memory_type=reconciliation.memory_type,
        subject=reconciliation.subject,
        content=reconciliation.content,
        importance=reconciliation.importance,
        confidence=reconciliation.confidence,
        source_type=source_type,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    return MemoryActionResult(
        action="created",
        subject=memory.subject,
        memory_id=memory.id,
        detail=reconciliation.reason,
    )


async def process_exchange_memories(
    session: AsyncSession,
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
    explicit: bool = False,
) -> list[MemoryActionResult]:
    candidates = await extract_candidates(
        user_message=user_message,
        assistant_message=assistant_message,
        explicit=explicit,
    )

    results: list[MemoryActionResult] = []
    for candidate in candidates:
        result = await reconcile_candidate(
            session,
            candidate=candidate,
            source_type="explicit" if explicit else "inferred",
            source_conversation_id=conversation_id,
            source_message_id=source_message_id,
        )
        logger.info(
            "Memory reconciliation: action=%s subject=%r detail=%s",
            result.action,
            result.subject,
            result.detail,
        )
        results.append(result)
    return results


async def process_agent_memories(
    session: AsyncSession,
    *,
    conversation_id: str | None,
    source_message_id: str | None,
    agent_name: str,
    task_title: str,
    task_instruction: str,
    agent_result: str,
    used_tools: list[str] | None = None,
) -> list[MemoryActionResult]:
    candidates = await extract_agent_candidates(
        agent_name=agent_name,
        task_title=task_title,
        task_instruction=task_instruction,
        agent_result=agent_result,
        used_tools=used_tools,
    )

    results: list[MemoryActionResult] = []
    for candidate in candidates:
        result = await reconcile_candidate(
            session,
            candidate=candidate,
            source_type="agent",
            source_conversation_id=conversation_id,
            source_message_id=source_message_id,
        )
        logger.info(
            "Agent memory reconciliation: agent=%s action=%s subject=%r detail=%s",
            agent_name,
            result.action,
            result.subject,
            result.detail,
        )
        results.append(result)
    return results


async def remember_explicit(
    session: AsyncSession,
    *,
    conversation_id: str,
    source_message_id: str,
    content: str,
) -> str:
    if contains_secret_request(content):
        return (
            "The memory was not stored because it appears to contain a credential or secret."
        )

    results = await process_exchange_memories(
        session,
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        user_message=content,
        assistant_message="",
        explicit=True,
    )
    if not results:
        return "No safe durable memory could be identified from the request."
    return "Memory action completed. " + "; ".join(
        f"{result.action}: {result.subject}"
        for result in results
        if result.subject
    )


async def forget_explicit(
    session: AsyncSession,
    *,
    query: str,
    forget_all: bool,
) -> str:
    hits = await search_memories(
        session,
        query,
        limit=settings.memory_reconcile_limit,
        min_similarity=settings.memory_forget_min_similarity,
        update_access=False,
    )
    if not hits:
        return "No sufficiently matching active memory was found, so nothing was forgotten."

    selected = hits if forget_all else hits[:1]
    forgotten: list[str] = []
    for hit in selected:
        await update_memory(session, hit.memory, is_active=False)
        forgotten.append(f"{hit.memory.subject}: {hit.memory.content}")
    return "Forgotten memory: " + " | ".join(forgotten)


async def process_explicit_command(
    session: AsyncSession,
    *,
    command: MemoryCommand,
    conversation_id: str,
    source_message_id: str,
) -> str:
    async with _extraction_lock:
        if command.action == "remember":
            return await remember_explicit(
                session,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                content=command.content,
            )
        if command.action == "forget":
            return await forget_explicit(
                session,
                query=command.content,
                forget_all=command.forget_all,
            )
    return "No memory action was performed."


async def _automatic_extraction_job(
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    # Automatic curation is useful, but it must never compete with an
    # interactive response for the same local model/GPU. Wait until chat has
    # been quiet for a short period before doing extraction/reconciliation.
    await chat_activity.wait_for_idle(settings.memory_extraction_idle_seconds)
    async with _extraction_lock:
        # A chat may have started while this task was waiting on another memory
        # extraction. Yield again before touching Ollama.
        await chat_activity.wait_for_idle(0)
        async with SessionLocal() as session:
            results = await process_exchange_memories(
                session,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                user_message=user_message,
                assistant_message=assistant_message,
                explicit=False,
            )
            if results:
                logger.info(
                    "Memory extraction produced %s action(s) for conversation %s",
                    len(results),
                    conversation_id,
                )


async def _automatic_agent_extraction_job(
    *,
    conversation_id: str | None,
    source_message_id: str | None,
    agent_name: str,
    task_title: str,
    task_instruction: str,
    agent_result: str,
    used_tools: list[str] | None,
) -> None:
    # Agent curation shares the same local Ollama model. Give the foreground
    # conversation priority and serialize with normal memory curation.
    await chat_activity.wait_for_idle(settings.memory_extraction_idle_seconds)
    async with _extraction_lock:
        await chat_activity.wait_for_idle(0)
        async with SessionLocal() as session:
            results = await process_agent_memories(
                session,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                agent_name=agent_name,
                task_title=task_title,
                task_instruction=task_instruction,
                agent_result=agent_result,
                used_tools=used_tools,
            )
            if results:
                logger.info(
                    "Agent memory extraction produced %s action(s) for %s task %r",
                    len(results),
                    agent_name,
                    task_title,
                )


def _background_task_finished(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        logger.warning("Background memory extraction task was cancelled: %s", task.get_name())
        return

    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return

    if exception is not None:
        logger.error(
            "Background memory extraction failed (%s): %s",
            task.get_name(),
            exception,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


def _track_background_task(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_task_finished)


def schedule_memory_extraction(
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
    enabled: bool = True,
) -> None:
    if not enabled or not settings.memory_enabled or not settings.memory_auto_extract:
        return

    task = asyncio.create_task(
        _automatic_extraction_job(
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            user_message=user_message,
            assistant_message=assistant_message,
        ),
        name=f"memory:conversation:{conversation_id}",
    )
    _track_background_task(task)


def schedule_agent_memory_extraction(
    *,
    conversation_id: str | None,
    source_message_id: str | None,
    agent_name: str,
    task_title: str,
    task_instruction: str,
    agent_result: str,
    used_tools: list[str] | None = None,
    enabled: bool = True,
) -> None:
    """Schedule durable-memory curation for a completed background agent."""
    if not enabled or not settings.memory_enabled or not settings.memory_auto_extract:
        return
    if not agent_result.strip():
        return

    task = asyncio.create_task(
        _automatic_agent_extraction_job(
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            agent_name=agent_name,
            task_title=task_title,
            task_instruction=task_instruction,
            agent_result=agent_result,
            used_tools=used_tools,
        ),
        name=f"memory:agent:{agent_name}:{task_title[:40]}",
    )
    _track_background_task(task)
