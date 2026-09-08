import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.db.models import Memory


_ALWAYS_RECALL_PATTERNS = (
    r"\bremember\b",
    r"\brecall\b",
    r"\bmemory\b",
    r"\bprevious(?:ly)?\b",
    r"\bearlier\b",
    r"\blast time\b",
    r"\bwe (?:discussed|decided|chose|agreed|used|built|planned)\b",
    r"\bwhat did i\b",
    r"\bwhat did we\b",
    r"\bwhich (?:database|framework|model|tool|stack|option) did\b",
    r"\bmy (?:project|server|website|portfolio|app|application|preference|plan|goal|setup|computer|pc)\b",
    r"\bour (?:project|server|website|app|application|plan|setup|decision)\b",
    r"\bi (?:prefer|like|use|work on|am building|built|decided|chose)\b",
    r"\bproject\s+[a-z0-9_-]+\b",
)

_SKIP_PATTERNS = (
    r"^(?:hi|hello|hey|thanks|thank you|cheers|ok|okay|yes|no|cool|great)[!. ]*$",
    r"^(?:good morning|good afternoon|good evening)[!. ]*$",
)


def should_retrieve_memory(message: str) -> bool:
    """Cheap deterministic first-stage memory gate."""
    text = " ".join(message.strip().split())
    if not text:
        return False

    lowered = text.lower()
    for pattern in _SKIP_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return False

    return any(
        re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in _ALWAYS_RECALL_PATTERNS
    )


def _normalise(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^(?:project|system|app|application|website)\s*[:\-]?\s*", "", value)
    value = re.sub(r"[^a-z0-9_-]+", " ", value)
    return " ".join(value.split())


async def has_memory_subject_match(session: AsyncSession, message: str) -> bool:
    """
    Cheap lexical fallback for named memories.

    This lets "What database does Atlas use?" recall an existing Atlas memory
    without running the embedding model for unrelated capitalised words such as
    Python, London or Ollama.
    """
    message_norm = f" {_normalise(message)} "
    if not message_norm.strip():
        return False

    result = await session.execute(
        select(Memory.subject).where(Memory.is_active.is_(True))
    )
    for subject in result.scalars().all():
        subject_norm = _normalise(subject)
        if len(subject_norm) < 3:
            continue
        if f" {subject_norm} " in message_norm:
            return True

    return False
