import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from jace.ai.engine import OllamaRequestError, OllamaUnavailableError, stream_chat
from jace.api.helpers import ndjson_event, nanoseconds_to_ms, tokens_per_second
from jace.config import settings as env_settings
from jace.database import SessionLocal
from jace.db.conversations import add_message, get_conversation, model_history, store_user_message, update_conversation
from jace.db.settings import build_profile_prompt, get_or_create_assistant_settings
from jace.memory.extractor import detect_memory_command, process_explicit_command, schedule_memory_extraction
from jace.memory.service import build_memory_context, search_memories
from jace.schemas import PersistentChatRequest


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def send_streaming_chat(request: PersistentChatRequest):
    async with SessionLocal() as session:
        conversation = await get_conversation(session, request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        profile = await get_or_create_assistant_settings(session)
        conversation_model = request.model or conversation.model or profile.default_model
        conversation_prompt = (
            request.system_prompt if request.system_prompt is not None else conversation.system_prompt or profile.system_prompt
        )
        await update_conversation(
            session,
            conversation,
            model=conversation_model,
            system_prompt=conversation_prompt,
        )

        user_message = await store_user_message(session, conversation, request.message)
        user_message_id = user_message.id

        memory_command = detect_memory_command(request.message)
        memory_command_handled = memory_command is not None
        memory_action_context = ""
        memory_allowed = bool(profile.memory_enabled and env_settings.memory_enabled)

        if memory_command is not None:
            if not memory_allowed:
                memory_action_context = (
                    "\n\nMEMORY SYSTEM ACTION\n"
                    "The user requested a memory action, but long-term memory is currently disabled in Jace settings. "
                    "Do not claim the action succeeded.\nEND MEMORY SYSTEM ACTION"
                )
            else:
                try:
                    result = await process_explicit_command(
                        session,
                        command=memory_command,
                        conversation_id=conversation.id,
                        source_message_id=user_message_id,
                    )
                    memory_action_context = (
                        "\n\nMEMORY SYSTEM ACTION\n"
                        "Jace has already processed the user's explicit memory instruction.\n"
                        f"Result: {result}\n"
                        "This is an actual application result; acknowledge it accurately.\n"
                        "END MEMORY SYSTEM ACTION"
                    )
                except (OllamaUnavailableError, OllamaRequestError) as exc:
                    memory_action_context = (
                        "\n\nMEMORY SYSTEM ACTION\n"
                        f"The requested memory action failed: {exc}\n"
                        "Do not claim the action succeeded.\nEND MEMORY SYSTEM ACTION"
                    )

        conversation = await get_conversation(session, conversation.id)
        if conversation is None:
            raise HTTPException(status_code=500, detail="Conversation could not be reloaded.")
        history = model_history(conversation)
        conversation_id = conversation.id
        conversation_system_prompt = conversation.system_prompt

        # Copy settings while the session is open; these primitive values remain safe after it closes.
        reasoning_mode = request.reasoning_mode or profile.reasoning_mode
        temperature = request.temperature if request.temperature is not None else profile.temperature
        memory_top_k = profile.memory_top_k
        memory_min_similarity = profile.memory_min_similarity
        auto_extract = bool(profile.memory_auto_extract and memory_allowed)

    async def persist_assistant(content: str, status: str, metrics: dict | None = None) -> str | None:
        if not content.strip():
            return None
        async with SessionLocal() as session:
            current = await get_conversation(session, conversation_id)
            if current is None:
                return None
            message = await add_message(
                session,
                conversation=current,
                role="assistant",
                content=content,
                status=status,
                model=conversation_model,
                metrics=metrics,
            )
            return message.id

    async def generate() -> AsyncIterator[str]:
        response_parts: list[str] = []
        started_at = time.perf_counter()
        first_token_at: float | None = None
        saved = False
        memory_hits = []

        try:
            if memory_allowed:
                async with SessionLocal() as session:
                    memory_hits = await search_memories(
                        session,
                        request.message,
                        limit=memory_top_k,
                        min_similarity=memory_min_similarity,
                        update_access=True,
                    )

            yield ndjson_event({
                "type": "context",
                "memory_count": len(memory_hits),
                "reasoning_mode": reasoning_mode,
            })

            memory_context = build_memory_context(memory_hits) if memory_allowed else ""
            effective_system_prompt = (
                build_profile_prompt(profile, conversation_system_prompt)
                + memory_context
                + memory_action_context
            )

            async for chunk in stream_chat(
                model=conversation_model,
                messages=history,
                system_prompt=effective_system_prompt,
                reasoning_mode=reasoning_mode,
                temperature=temperature,
            ):
                message = chunk.get("message") or {}
                content = message.get("content") or ""
                if content:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    response_parts.append(content)
                    yield ndjson_event({"type": "token", "content": content})

                if chunk.get("done"):
                    eval_count = chunk.get("eval_count")
                    eval_duration = chunk.get("eval_duration")
                    metrics = {
                        "time_to_first_token_ms": (
                            round((first_token_at - started_at) * 1000, 2) if first_token_at is not None else None
                        ),
                        "total_duration_ms": nanoseconds_to_ms(chunk.get("total_duration")),
                        "load_duration_ms": nanoseconds_to_ms(chunk.get("load_duration")),
                        "prompt_eval_count": chunk.get("prompt_eval_count"),
                        "prompt_eval_cached_count": chunk.get("prompt_eval_cached_count"),
                        "prompt_eval_duration_ms": nanoseconds_to_ms(chunk.get("prompt_eval_duration")),
                        "eval_count": eval_count,
                        "eval_duration_ms": nanoseconds_to_ms(eval_duration),
                        "tokens_per_second": tokens_per_second(eval_count, eval_duration),
                    }
                    full_response = "".join(response_parts)
                    assistant_message_id = await persist_assistant(full_response, "complete", metrics)
                    saved = True

                    if not memory_command_handled and assistant_message_id:
                        schedule_memory_extraction(
                            conversation_id=conversation_id,
                            source_message_id=user_message_id,
                            user_message=request.message,
                            assistant_message=full_response,
                            enabled=auto_extract,
                        )

                    yield ndjson_event({
                        "type": "done",
                        "model": chunk.get("model", conversation_model),
                        "done_reason": chunk.get("done_reason"),
                        "metrics": metrics,
                    })

        except asyncio.CancelledError:
            if response_parts and not saved:
                await asyncio.shield(persist_assistant("".join(response_parts), "stopped"))
            raise
        except (OllamaUnavailableError, OllamaRequestError) as exc:
            if response_parts and not saved:
                await persist_assistant("".join(response_parts), "error")
                saved = True
            yield ndjson_event({"type": "error", "message": str(exc)})
        except Exception as exc:
            if response_parts and not saved:
                await persist_assistant("".join(response_parts), "error")
            yield ndjson_event({"type": "error", "message": f"Unexpected streaming error: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
