import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from jace.ai.engine import structured_chat
from jace.ai.prompts import MEMORY_EXTRACTION_SYSTEM_PROMPT, MEMORY_RECONCILIATION_SYSTEM_PROMPT
from jace.config import settings
from jace.database import SessionLocal
from jace.memory.service import (
    create_memory,
    normalize_project_subject,
    search_memories,
    update_memory,
)
from jace.schemas import ExtractedMemoryCandidate, MemoryExtractionResult, MemoryReconciliationResult


logger = logging.getLogger("uvicorn.error")


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
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SECRET_PATTERNS)


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
        return MemoryCommand(action="forget", content=match.group(1).strip(), forget_all=True)

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

    prompt = f"""Analyse this exchange for long-term memory.

Explicit memory request: {"yes" if explicit else "no"}

USER:\n{user_message}\n\nASSISTANT RESPONSE FOR CONTEXT ONLY:\n{assistant_message}\n
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

    logger.info("Memory extractor accepted %d/%d candidate(s)", len(filtered), len(result.memories))
    return filtered


def reconciliation_prompt(candidate: ExtractedMemoryCandidate, hits) -> str:
    existing = []
    for hit in hits:
        m = hit.memory
        existing.append(
            f"ID: {m.id}\nType: {m.memory_type}\nSubject: {m.subject}\nContent: {m.content}\n"
            f"Importance: {m.importance:.2f}\nConfidence: {m.confidence:.2f}\nSimilarity: {hit.similarity:.4f}"
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
    source_conversation_id: str,
    source_message_id: str,
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
        return MemoryActionResult(action="created", subject=memory.subject, memory_id=memory.id, detail="Created a new memory.")

    reconciliation = await structured_chat(
        model=settings.memory_extraction_model,
        messages=[{"role": "user", "content": reconciliation_prompt(candidate, hits)}],
        system_prompt=MEMORY_RECONCILIATION_SYSTEM_PROMPT,
        response_model=MemoryReconciliationResult,
    )
    allowed_targets = {hit.memory.id: hit.memory for hit in hits}
    target = allowed_targets.get(reconciliation.target_memory_id) if reconciliation.target_memory_id else None

    if reconciliation.action in {"duplicate", "merge", "supersede"} and target is None:
        reconciliation.action = "create"

    if reconciliation.action == "ignore":
        return MemoryActionResult(action="ignored", subject=candidate.subject, detail=reconciliation.reason)
    if reconciliation.action == "duplicate" and target:
        return MemoryActionResult(action="duplicate", subject=target.subject, memory_id=target.id, detail=reconciliation.reason)
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
        return MemoryActionResult(action="merged", subject=updated.subject, memory_id=updated.id, target_memory_id=target.id, detail=reconciliation.reason)
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
    return MemoryActionResult(action="created", subject=memory.subject, memory_id=memory.id, detail=reconciliation.reason)


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
        logger.info("Memory reconciliation: action=%s subject=%r detail=%s", result.action, result.subject, result.detail)
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
        return "The memory was not stored because it appears to contain a credential or secret."
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
        f"{result.action}: {result.subject}" for result in results if result.subject
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
            return await forget_explicit(session, query=command.content, forget_all=command.forget_all)
    return "No memory action was performed."


async def _automatic_extraction_job(
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    async with _extraction_lock:
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
                logger.info("Memory extraction produced %s action(s) for conversation %s", len(results), conversation_id)


def _background_task_finished(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        logger.warning("Automatic memory extraction task was cancelled.")
        return
    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return
    if exception is not None:
        logger.error(
            "Automatic memory extraction failed: %s",
            exception,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


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
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_task_finished)
