import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jace.db.models import Conversation, Message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_title(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    if not cleaned:
        return "New conversation"
    max_length = 58
    return cleaned if len(cleaned) <= max_length else cleaned[:max_length].rstrip() + "…"


async def create_conversation(
    session: AsyncSession,
    model: str,
    system_prompt: str,
) -> Conversation:
    conversation = Conversation(title="New conversation", model=model, system_prompt=system_prompt)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession) -> list[tuple[Conversation, int]]:
    statement = (
        select(Conversation, func.count(Message.id))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await session.execute(statement)
    return [(conversation, message_count) for conversation, message_count in result.all()]


async def get_conversation(session: AsyncSession, conversation_id: str) -> Conversation | None:
    statement = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def update_conversation(
    session: AsyncSession,
    conversation: Conversation,
    *,
    title: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
) -> Conversation:
    if title is not None:
        conversation.title = title.strip() or "New conversation"
    if model is not None:
        conversation.model = model
    if system_prompt is not None:
        conversation.system_prompt = system_prompt
    conversation.updated_at = utc_now()
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def delete_conversation(session: AsyncSession, conversation_id: str) -> bool:
    result = await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await session.commit()
    return (result.rowcount or 0) > 0


async def add_message(
    session: AsyncSession,
    *,
    conversation: Conversation,
    role: str,
    content: str,
    status: str = "complete",
    model: str | None = None,
    metrics: dict | None = None,
) -> Message:
    metrics = metrics or {}
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        status=status,
        model=model,
        time_to_first_token_ms=metrics.get("time_to_first_token_ms"),
        total_duration_ms=metrics.get("total_duration_ms"),
        load_duration_ms=metrics.get("load_duration_ms"),
        prompt_eval_count=metrics.get("prompt_eval_count"),
        prompt_eval_cached_count=metrics.get("prompt_eval_cached_count"),
        prompt_eval_duration_ms=metrics.get("prompt_eval_duration_ms"),
        eval_count=metrics.get("eval_count"),
        eval_duration_ms=metrics.get("eval_duration_ms"),
        tokens_per_second=metrics.get("tokens_per_second"),
    )
    session.add(message)
    conversation.updated_at = utc_now()
    await session.commit()
    await session.refresh(message)
    return message


async def store_user_message(
    session: AsyncSession,
    conversation: Conversation,
    content: str,
) -> Message:
    result = await session.execute(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
        )
    )
    existing_user_messages = result.scalar_one()
    message = await add_message(
        session,
        conversation=conversation,
        role="user",
        content=content,
    )
    if existing_user_messages == 0 and conversation.title == "New conversation":
        conversation.title = create_title(content)
        conversation.updated_at = utc_now()
        await session.commit()
    return message


def model_history(
    conversation: Conversation,
    *,
    max_messages: int | None = None,
    max_chars: int | None = None,
) -> list[dict[str, str]]:
    """Return recent model-visible history with optional bounded context.

    Long conversations otherwise grow without limit and make every subsequent
    prompt slower. Trimming from the oldest end preserves the most recent turn
    (including the user message that was just stored) while keeping local-model
    prompt evaluation predictable.
    """
    valid: list[dict[str, str]] = []
    for message in conversation.messages:
        if not message.content.strip() or message.role not in {"user", "assistant"}:
            continue
        if message.role == "assistant" and message.status not in {"complete", "stopped"}:
            continue
        valid.append({"role": message.role, "content": message.content})

    if max_messages is not None and max_messages > 0:
        valid = valid[-max_messages:]

    if max_chars is None or max_chars <= 0:
        return valid

    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(valid):
        content = message["content"]
        cost = len(content)
        if selected and used + cost > max_chars:
            break

        # Always keep at least the newest message. If it alone is unusually
        # large, trim it rather than dropping the current user request.
        if not selected and cost > max_chars:
            content = content[-max_chars:]
            cost = len(content)

        selected.append({"role": message["role"], "content": content})
        used += cost

    selected.reverse()
    return selected
