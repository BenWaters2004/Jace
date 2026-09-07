import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from jace.ai.engine import (
    OllamaRequestError,
    OllamaUnavailableError,
    structured_chat,
)
from jace.ai.prompts import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    MEMORY_RECONCILIATION_SYSTEM_PROMPT,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.memory.service import (
    create_memory,
    search_memories,
    update_memory,
)
from jace.schemas import (
    ExtractedMemoryCandidate,
    MemoryExtractionResult,
    MemoryReconciliationResult,
)


logger = logging.getLogger(__name__)


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


_background_tasks: set[
    asyncio.Task
] = set()


_extraction_lock = (
    asyncio.Lock()
)


SECRET_PATTERNS = [
    r"\bpassword\b",
    r"\bpasscode\b",
    r"\bapi[\s_-]*key\b",
    r"\baccess[\s_-]*token\b",
    r"\brefresh[\s_-]*token\b",
    r"\bprivate[\s_-]*key\b",
    r"\brecovery[\s_-]*code\b",
    r"\bsecret[\s_-]*key\b",
    r"\bcredit[\s_-]*card\b",
    r"\bdebit[\s_-]*card\b",
    r"\bbank[\s_-]*account\b",
]


def contains_secret_request(
    text: str,
) -> bool:
    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern
        in SECRET_PATTERNS
    )


def detect_memory_command(
    message: str,
) -> MemoryCommand | None:
    text = message.strip()

    remember_patterns = [
        (
            r"^\s*(?:please\s+)?"
            r"remember\s+that\s+(.+)$"
        ),
        (
            r"^\s*(?:please\s+)?"
            r"remember\s*:\s*(.+)$"
        ),
        (
            r"^\s*(?:please\s+)?"
            r"remember\s+this\s*[:,-]\s*(.+)$"
        ),
        (
            r"^\s*(?:please\s+)?"
            r"(?:save|store)\s+"
            r"(?:this|that)\s+"
            r"(?:to|in)\s+memory"
            r"\s*[:,-]?\s*(.+)$"
        ),
    ]

    for pattern in remember_patterns:
        match = re.match(
            pattern,
            text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if match:
            return MemoryCommand(
                action="remember",

                content=(
                    match.group(1)
                    .strip()
                ),
            )

    forget_all_match = re.match(
        (
            r"^\s*(?:please\s+)?"
            r"forget\s+"
            r"(?:everything|all)\s+"
            r"about\s+(.+)$"
        ),
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if forget_all_match:
        return MemoryCommand(
            action="forget",

            content=(
                forget_all_match
                .group(1)
                .strip()
            ),

            forget_all=True,
        )

    forget_patterns = [
        (
            r"^\s*(?:please\s+)?"
            r"forget\s+that\s+(.+)$"
        ),
        (
            r"^\s*(?:please\s+)?"
            r"forget\s*:\s*(.+)$"
        ),
        (
            r"^\s*(?:please\s+)?"
            r"(?:remove|delete)\s+"
            r"(?:the\s+)?memory\s+"
            r"(?:that|about)\s+(.+)$"
        ),
    ]

    for pattern in forget_patterns:
        match = re.match(
            pattern,
            text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if match:
            return MemoryCommand(
                action="forget",

                content=(
                    match.group(1)
                    .strip()
                ),

                forget_all=False,
            )

    return None


async def extract_candidates(
    *,
    user_message: str,
    assistant_message: str = "",
    explicit: bool = False,
) -> list[
    ExtractedMemoryCandidate
]:
    if contains_secret_request(
        user_message
    ):
        return []

    prompt = f"""
Analyse the following exchange for long-term memory.

Explicit memory request:
{"yes" if explicit else "no"}

USER:
{user_message}

ASSISTANT RESPONSE FOR CONTEXT ONLY:
{assistant_message}

Only information established by the USER may become memory.
"""

    result = await structured_chat(
        model=(
            settings.memory_extraction_model
        ),

        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],

        system_prompt=(
            MEMORY_EXTRACTION_SYSTEM_PROMPT
        ),

        response_model=(
            MemoryExtractionResult
        ),
    )

    candidates = (
        result.memories[
            :settings.memory_max_candidates
        ]
    )

    filtered: list[
        ExtractedMemoryCandidate
    ] = []

    for candidate in candidates:
        if contains_secret_request(
            candidate.content
        ):
            continue

        if explicit:
            # Explicitly requested memories
            # should be trusted as user intent.
            candidate.confidence = max(
                candidate.confidence,
                0.95,
            )

            candidate.importance = max(
                candidate.importance,
                0.70,
            )

            filtered.append(
                candidate
            )

            continue

        if (
            candidate.importance
            < settings.memory_min_importance
        ):
            continue

        if (
            candidate.confidence
            < settings.memory_min_confidence
        ):
            continue

        filtered.append(
            candidate
        )

    return filtered


def reconciliation_prompt(
    candidate:
        ExtractedMemoryCandidate,

    hits,
) -> str:
    existing_lines: list[str] = []

    for hit in hits:
        memory = hit.memory

        existing_lines.append(
            (
                f"ID: {memory.id}\n"
                f"Type: {memory.memory_type}\n"
                f"Subject: {memory.subject}\n"
                f"Content: {memory.content}\n"
                f"Importance: {memory.importance:.2f}\n"
                f"Confidence: {memory.confidence:.2f}\n"
                f"Similarity: {hit.similarity:.4f}\n"
            )
        )

    existing_text = (
        "\n---\n".join(
            existing_lines
        )
    )

    return f"""
PROPOSED MEMORY

Type:
{candidate.memory_type}

Subject:
{candidate.subject}

Content:
{candidate.content}

Importance:
{candidate.importance}

Confidence:
{candidate.confidence}


RELATED EXISTING MEMORIES

{existing_text}
"""


async def reconcile_candidate(
    session: AsyncSession,
    *,
    candidate:
        ExtractedMemoryCandidate,
    source_type: str,
    source_conversation_id: str,
    source_message_id: str,
) -> MemoryActionResult:

    search_text = (
        f"{candidate.subject}. "
        f"{candidate.content}"
    )

    hits = await search_memories(
        session,
        search_text,

        limit=(
            settings.memory_reconcile_limit
        ),

        min_similarity=(
            settings
            .memory_reconcile_min_similarity
        ),

        update_access=False,
    )

    if not hits:
        memory = await create_memory(
            session,

            memory_type=(
                candidate.memory_type
            ),

            subject=(
                candidate.subject
            ),

            content=(
                candidate.content
            ),

            importance=(
                candidate.importance
            ),

            confidence=(
                candidate.confidence
            ),

            source_type=source_type,

            source_conversation_id=(
                source_conversation_id
            ),

            source_message_id=(
                source_message_id
            ),
        )

        return MemoryActionResult(
            action="created",

            subject=memory.subject,

            memory_id=memory.id,

            detail=(
                "Created a new memory."
            ),
        )

    reconciliation = (
        await structured_chat(
            model=(
                settings
                .memory_extraction_model
            ),

            messages=[
                {
                    "role": "user",

                    "content": (
                        reconciliation_prompt(
                            candidate,
                            hits,
                        )
                    ),
                }
            ],

            system_prompt=(
                MEMORY_RECONCILIATION_SYSTEM_PROMPT
            ),

            response_model=(
                MemoryReconciliationResult
            ),
        )
    )

    allowed_targets = {
        hit.memory.id:
            hit.memory
        for hit in hits
    }

    target = None

    if (
        reconciliation
        .target_memory_id
    ):
        target = allowed_targets.get(
            reconciliation
            .target_memory_id
        )

    # The model is not allowed to
    # reference arbitrary memory IDs.
    if (
        reconciliation.action
        in {
            "duplicate",
            "merge",
            "supersede",
        }
        and target is None
    ):
        reconciliation.action = (
            "create"
        )

    if (
        reconciliation.action
        == "ignore"
    ):
        return MemoryActionResult(
            action="ignored",

            subject=(
                candidate.subject
            ),

            detail=(
                reconciliation.reason
            ),
        )

    if (
        reconciliation.action
        == "duplicate"
        and target
        is not None
    ):
        return MemoryActionResult(
            action="duplicate",

            subject=target.subject,

            memory_id=target.id,

            detail=(
                reconciliation.reason
            ),
        )

    if (
        reconciliation.action
        == "merge"
        and target
        is not None
    ):
        updated = (
            await update_memory(
                session,
                target,

                memory_type=(
                    reconciliation
                    .memory_type
                ),

                subject=(
                    reconciliation
                    .subject
                ),

                content=(
                    reconciliation
                    .content
                ),

                importance=max(
                    target.importance,

                    reconciliation
                    .importance,
                ),

                confidence=max(
                    target.confidence,

                    reconciliation
                    .confidence,
                ),
            )
        )

        return MemoryActionResult(
            action="merged",

            subject=updated.subject,

            memory_id=updated.id,

            target_memory_id=(
                target.id
            ),

            detail=(
                reconciliation.reason
            ),
        )

    if (
        reconciliation.action
        == "supersede"
        and target
        is not None
    ):
        await update_memory(
            session,
            target,

            is_active=False,
        )

        replacement = (
            await create_memory(
                session,

                memory_type=(
                    reconciliation
                    .memory_type
                ),

                subject=(
                    reconciliation
                    .subject
                ),

                content=(
                    reconciliation
                    .content
                ),

                importance=(
                    reconciliation
                    .importance
                ),

                confidence=(
                    reconciliation
                    .confidence
                ),

                source_type=(
                    source_type
                ),

                source_conversation_id=(
                    source_conversation_id
                ),

                source_message_id=(
                    source_message_id
                ),
            )
        )

        return MemoryActionResult(
            action="superseded",

            subject=(
                replacement.subject
            ),

            memory_id=(
                replacement.id
            ),

            target_memory_id=(
                target.id
            ),

            detail=(
                reconciliation.reason
            ),
        )

    memory = await create_memory(
        session,

        memory_type=(
            reconciliation.memory_type
        ),

        subject=(
            reconciliation.subject
        ),

        content=(
            reconciliation.content
        ),

        importance=(
            reconciliation.importance
        ),

        confidence=(
            reconciliation.confidence
        ),

        source_type=source_type,

        source_conversation_id=(
            source_conversation_id
        ),

        source_message_id=(
            source_message_id
        ),
    )

    return MemoryActionResult(
        action="created",

        subject=memory.subject,

        memory_id=memory.id,

        detail=(
            reconciliation.reason
        ),
    )


async def process_exchange_memories(
    session: AsyncSession,
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
    explicit: bool = False,
) -> list[
    MemoryActionResult
]:
    candidates = (
        await extract_candidates(
            user_message=user_message,

            assistant_message=(
                assistant_message
            ),

            explicit=explicit,
        )
    )

    results: list[
        MemoryActionResult
    ] = []

    for candidate in candidates:
        result = (
            await reconcile_candidate(
                session,

                candidate=candidate,

                source_type=(
                    "explicit"
                    if explicit
                    else "inferred"
                ),

                source_conversation_id=(
                    conversation_id
                ),

                source_message_id=(
                    source_message_id
                ),
            )
        )

        results.append(
            result
        )

    return results


async def remember_explicit(
    session: AsyncSession,
    *,
    conversation_id: str,
    source_message_id: str,
    content: str,
) -> str:

    if contains_secret_request(
        content
    ):
        return (
            "The memory was not stored because "
            "it appears to contain a credential "
            "or secret."
        )

    results = (
        await process_exchange_memories(
            session,

            conversation_id=(
                conversation_id
            ),

            source_message_id=(
                source_message_id
            ),

            user_message=content,

            assistant_message="",

            explicit=True,
        )
    )

    if not results:
        return (
            "No safe durable memory could "
            "be identified from the request."
        )

    descriptions = [
        (
            f"{result.action}: "
            f"{result.subject}"
        )
        for result in results
        if result.subject
    ]

    return (
        "Memory action completed. "
        + "; ".join(descriptions)
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

        limit=(
            settings.memory_reconcile_limit
        ),

        min_similarity=(
            settings
            .memory_forget_min_similarity
        ),

        update_access=False,
    )

    if not hits:
        return (
            "No sufficiently matching active "
            "memory was found, so nothing "
            "was forgotten."
        )

    selected = (
        hits
        if forget_all
        else hits[:1]
    )

    forgotten: list[str] = []

    for hit in selected:
        await update_memory(
            session,
            hit.memory,

            is_active=False,
        )

        forgotten.append(
            (
                f"{hit.memory.subject}: "
                f"{hit.memory.content}"
            )
        )

    return (
        "Forgotten memory: "
        + " | ".join(
            forgotten
        )
    )


async def process_explicit_command(
    session: AsyncSession,
    *,
    command: MemoryCommand,
    conversation_id: str,
    source_message_id: str,
) -> str:

    async with _extraction_lock:
        if (
            command.action
            == "remember"
        ):
            return (
                await remember_explicit(
                    session,

                    conversation_id=(
                        conversation_id
                    ),

                    source_message_id=(
                        source_message_id
                    ),

                    content=(
                        command.content
                    ),
                )
            )

        if (
            command.action
            == "forget"
        ):
            return (
                await forget_explicit(
                    session,

                    query=(
                        command.content
                    ),

                    forget_all=(
                        command.forget_all
                    ),
                )
            )

    return (
        "No memory action was performed."
    )


async def _automatic_extraction_job(
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
) -> None:

    async with _extraction_lock:
        async with SessionLocal() as session:

            results = (
                await process_exchange_memories(
                    session,

                    conversation_id=(
                        conversation_id
                    ),

                    source_message_id=(
                        source_message_id
                    ),

                    user_message=(
                        user_message
                    ),

                    assistant_message=(
                        assistant_message
                    ),

                    explicit=False,
                )
            )

            if results:
                logger.info(
                    "Memory extraction produced %s action(s) "
                    "for conversation %s",
                    len(results),
                    conversation_id,
                )


def _background_task_finished(
    task: asyncio.Task,
) -> None:
    _background_tasks.discard(
        task
    )

    if task.cancelled():
        return

    try:
        exception = (
            task.exception()
        )
    except asyncio.CancelledError:
        return

    if exception is not None:
        logger.exception(
            "Automatic memory extraction failed.",
            exc_info=exception,
        )


def schedule_memory_extraction(
    *,
    conversation_id: str,
    source_message_id: str,
    user_message: str,
    assistant_message: str,
) -> None:

    if not settings.memory_auto_extract:
        return

    task = asyncio.create_task(
        _automatic_extraction_job(
            conversation_id=(
                conversation_id
            ),

            source_message_id=(
                source_message_id
            ),

            user_message=(
                user_message
            ),

            assistant_message=(
                assistant_message
            ),
        )
    )

    _background_tasks.add(
        task
    )

    task.add_done_callback(
        _background_task_finished
    )