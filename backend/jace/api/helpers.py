import json
from typing import Any

from jace.schemas import (
    AssistantSettingsResponse,
    ConversationDetail,
    GenerationStatsResponse,
    MemoryResponse,
    MessageResponse,
)


def ndjson_event(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def nanoseconds_to_ms(value: int | None) -> float | None:
    return None if value is None else round(value / 1_000_000, 2)


def tokens_per_second(count: int | None, duration_ns: int | None) -> float | None:
    if not count or not duration_ns or duration_ns <= 0:
        return None
    seconds = duration_ns / 1_000_000_000
    return None if seconds <= 0 else round(count / seconds, 2)


def message_response(message) -> MessageResponse:
    values = [
        message.time_to_first_token_ms,
        message.total_duration_ms,
        message.load_duration_ms,
        message.prompt_eval_count,
        message.prompt_eval_cached_count,
        message.prompt_eval_duration_ms,
        message.eval_count,
        message.eval_duration_ms,
        message.tokens_per_second,
    ]
    stats = None
    if any(value is not None for value in values):
        stats = GenerationStatsResponse(
            time_to_first_token_ms=message.time_to_first_token_ms,
            total_duration_ms=message.total_duration_ms,
            load_duration_ms=message.load_duration_ms,
            prompt_eval_count=message.prompt_eval_count,
            prompt_eval_cached_count=message.prompt_eval_cached_count,
            prompt_eval_duration_ms=message.prompt_eval_duration_ms,
            eval_count=message.eval_count,
            eval_duration_ms=message.eval_duration_ms,
            tokens_per_second=message.tokens_per_second,
        )
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        status=message.status,
        model=message.model,
        created_at=message.created_at,
        stats=stats,
    )


def conversation_detail_response(conversation) -> ConversationDetail:
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        model=conversation.model,
        system_prompt=conversation.system_prompt,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[message_response(message) for message in conversation.messages],
    )


def memory_response(memory) -> MemoryResponse:
    return MemoryResponse(
        id=memory.id,
        memory_type=memory.memory_type,
        subject=memory.subject,
        content=memory.content,
        importance=memory.importance,
        confidence=memory.confidence,
        source_type=memory.source_type,
        source_conversation_id=memory.source_conversation_id,
        source_message_id=memory.source_message_id,
        embedding_model=memory.embedding_model,
        is_pinned=memory.is_pinned,
        is_active=memory.is_active,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_accessed_at=memory.last_accessed_at,
        access_count=memory.access_count,
    )


def assistant_settings_response(profile) -> AssistantSettingsResponse:
    return AssistantSettingsResponse(
        assistant_name=profile.assistant_name,
        user_name=profile.user_name,
        system_prompt=profile.system_prompt,
        default_model=profile.default_model,
        reasoning_mode=profile.reasoning_mode,
        response_style=profile.response_style,
        temperature=profile.temperature,
        memory_enabled=profile.memory_enabled,
        memory_auto_extract=profile.memory_auto_extract,
        memory_top_k=profile.memory_top_k,
        memory_min_similarity=profile.memory_min_similarity,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
