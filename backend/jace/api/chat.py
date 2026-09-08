import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from jace.ai.engine import OllamaRequestError, OllamaUnavailableError
from jace.ai.prompts import TOOL_AGENT_SYSTEM_PROMPT
from jace.attachments.processors import prepare_attachments
from jace.attachments.service import assign_attachments_to_message, get_attachments
from jace.api.helpers import ndjson_event, nanoseconds_to_ms, tokens_per_second
from jace.config import settings as env_settings
from jace.database import SessionLocal
from jace.db.conversations import (
    add_message,
    get_conversation,
    model_history,
    store_user_message,
    update_conversation,
)
from jace.db.settings import build_profile_prompt, get_or_create_assistant_settings
from jace.memory.extractor import (
    detect_memory_command,
    process_explicit_command,
    schedule_memory_extraction,
)
from jace.memory.gating import has_memory_subject_match, should_retrieve_memory
from jace.memory.service import build_memory_context, search_memories
from jace.performance import chat_activity
from jace.schemas import PersistentChatRequest
from jace.runtime import runtime_events
from jace.tools.agent import routed_tool_names, stream_agent


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def send_streaming_chat(request: PersistentChatRequest):
    if not request.message.strip() and not request.attachment_ids:
        raise HTTPException(status_code=400, detail="Enter a message or attach a file.")
    if len(request.attachment_ids) > env_settings.attachment_max_count:
        raise HTTPException(status_code=400, detail="Too many attachments for one message.")

    async with SessionLocal() as session:
        conversation = await get_conversation(session, request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        profile = await get_or_create_assistant_settings(session)
        conversation_model = request.model or conversation.model or profile.default_model
        conversation_prompt = (
            request.system_prompt
            if request.system_prompt is not None
            else conversation.system_prompt or profile.system_prompt
        )

        await update_conversation(
            session,
            conversation,
            model=conversation_model,
            system_prompt=conversation_prompt,
        )

        attachments = await get_attachments(
            session,
            request.attachment_ids,
            conversation_id=conversation.id,
        )
        if len(attachments) != len(list(dict.fromkeys(request.attachment_ids))):
            raise HTTPException(
                status_code=400,
                detail="One or more attachments are unavailable for this conversation.",
            )

        attachment_names = ", ".join(item.original_name for item in attachments)
        stored_user_text = request.message.strip()
        if not stored_user_text:
            stored_user_text = f"Attached {len(attachments)} file(s): {attachment_names}"

        user_message = await store_user_message(session, conversation, stored_user_text)
        user_message_id = user_message.id
        if attachments:
            await assign_attachments_to_message(session, attachments, user_message_id)

        memory_command = detect_memory_command(request.message) if request.message.strip() else None
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

        history = model_history(
            conversation,
            max_messages=env_settings.history_max_messages,
            max_chars=env_settings.history_max_chars,
        )
        history_chars = sum(len(message.get("content", "")) for message in history)
        conversation_id = conversation.id
        conversation_system_prompt = conversation.system_prompt

        # Copy primitive settings while the session is active.
        reasoning_mode = request.reasoning_mode or profile.reasoning_mode
        temperature = request.temperature if request.temperature is not None else profile.temperature
        memory_top_k = profile.memory_top_k
        memory_min_similarity = profile.memory_min_similarity
        auto_extract = bool(profile.memory_auto_extract and memory_allowed)
        profile_prompt = build_profile_prompt(profile, conversation_system_prompt)
        current_attachment_ids = [item.id for item in attachments]

    async def persist_assistant(
        content: str,
        status: str,
        metrics: dict | None = None,
        *,
        model_name: str | None = None,
    ) -> str | None:
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
                model=model_name or conversation_model,
                metrics=metrics,
            )
            return message.id

    async def generate() -> AsyncIterator[str]:
        response_parts: list[str] = []
        started_at = time.perf_counter()
        first_token_at: float | None = None
        saved = False
        memory_hits = []
        response_model = conversation_model

        await chat_activity.begin()
        await runtime_events.publish(
            "jace.state.changed",
            state="thinking",
            conversation_id=conversation_id,
        )

        try:
            attachment_started = time.perf_counter()
            attachment_context = ""
            attachment_images: list[str] = []
            attachment_summaries: list[dict] = []

            if current_attachment_ids:
                async with SessionLocal() as session:
                    current_attachments = await get_attachments(
                        session,
                        current_attachment_ids,
                        conversation_id=conversation_id,
                    )
                    attachment_context, attachment_images, attachment_summaries = await prepare_attachments(
                        session,
                        current_attachments,
                    )

            attachment_processing_ms = round(
                (time.perf_counter() - attachment_started) * 1000,
                2,
            )

            memory_started = time.perf_counter()
            memory_retrieval_used = bool(
                memory_allowed
                and not memory_command_handled
                and (
                    not env_settings.memory_smart_retrieval
                    or should_retrieve_memory(request.message)
                )
            )

            if memory_allowed and not memory_command_handled:
                async with SessionLocal() as session:
                    if env_settings.memory_smart_retrieval and not memory_retrieval_used:
                        memory_retrieval_used = await has_memory_subject_match(
                            session,
                            request.message,
                        )

                    if memory_retrieval_used:
                        memory_hits = await search_memories(
                            session,
                            request.message,
                            limit=memory_top_k,
                            min_similarity=memory_min_similarity,
                            update_access=True,
                        )

            memory_retrieval_ms = round(
                (time.perf_counter() - memory_started) * 1000,
                2,
            )

            tool_started = time.perf_counter()
            routed_tools = await routed_tool_names(request.message)
            if current_attachment_ids:
                routed_tools = [name for name in routed_tools if name != "inspect_attachment"]
            tool_routing_ms = round((time.perf_counter() - tool_started) * 1000, 2)

            multimodal_tool_names = {
                "inspect_attachment",
                "inspect_workspace_media",
                "capture_screen",
            }
            use_specialist_vision = bool(
                env_settings.vision_model.strip()
                and (
                    attachment_images
                    or multimodal_tool_names.intersection(routed_tools)
                )
            )
            response_model = (
                env_settings.vision_model.strip()
                if use_specialist_vision
                else conversation_model
            )

            preprocess_ms = round((time.perf_counter() - started_at) * 1000, 2)
            yield ndjson_event(
                {
                    "type": "context",
                    "memory_count": len(memory_hits),
                    "memory_retrieval_used": memory_retrieval_used,
                    "memory_retrieval_ms": memory_retrieval_ms,
                    "tool_count": len(routed_tools),
                    "tool_names": routed_tools,
                    "tool_routing_ms": tool_routing_ms,
                    "history_messages": len(history),
                    "history_chars": history_chars,
                    "preprocess_ms": preprocess_ms,
                    "reasoning_mode": reasoning_mode,
                    "response_model": response_model,
                    "attachment_count": len(current_attachment_ids),
                    "attachment_image_count": len(attachment_images),
                    "attachment_processing_ms": attachment_processing_ms,
                    "attachments": attachment_summaries,
                }
            )

            memory_context = build_memory_context(memory_hits) if memory_allowed else ""
            tool_context = TOOL_AGENT_SYSTEM_PROMPT if (routed_tools or current_attachment_ids) else ""

            effective_system_prompt = (
                profile_prompt
                + memory_context
                + memory_action_context
                + tool_context
            )

            async for event in stream_agent(
                model=response_model,
                messages=history,
                system_prompt=effective_system_prompt,
                reasoning_mode=reasoning_mode,
                temperature=temperature,
                conversation_id=conversation_id,
                user_message=request.message or stored_user_text,
                tool_names=routed_tools,
                current_images=attachment_images,
                attachment_context=attachment_context,
            ):
                event_type = event.get("type")

                if event_type == "token":
                    content = event.get("content") or ""
                    if content:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                            await runtime_events.publish(
                                "jace.state.changed",
                                state="working",
                                conversation_id=conversation_id,
                                reason="responding",
                            )
                        response_parts.append(content)
                        yield ndjson_event({"type": "token", "content": content})
                    continue

                if event_type in {"tool_call", "approval_required", "tool_result"}:
                    if event_type == "tool_call":
                        await runtime_events.publish(
                            "tool.started",
                            conversation_id=conversation_id,
                            tool_name=event.get("tool_name"),
                            label=event.get("label"),
                        )
                        await runtime_events.publish(
                            "jace.state.changed",
                            state="working",
                            reason="tool",
                            conversation_id=conversation_id,
                        )
                    elif event_type == "approval_required":
                        await runtime_events.publish(
                            "permission.requested",
                            conversation_id=conversation_id,
                            tool_name=event.get("tool_name"),
                            label=event.get("label"),
                            risk=event.get("risk"),
                        )
                        await runtime_events.publish(
                            "jace.state.changed",
                            state="waiting_permission",
                            conversation_id=conversation_id,
                        )
                    else:
                        await runtime_events.publish(
                            "tool.completed",
                            conversation_id=conversation_id,
                            tool_name=event.get("tool_name"),
                            status=event.get("status"),
                            summary=event.get("summary"),
                        )
                        await runtime_events.publish(
                            "jace.state.changed",
                            state="thinking",
                            conversation_id=conversation_id,
                        )

                    yield ndjson_event(event)
                    continue

                if event_type == "agent_done":
                    raw_metrics = event.get("metrics") or {}
                    eval_count = raw_metrics.get("eval_count")
                    eval_duration = raw_metrics.get("eval_duration")

                    metrics = {
                        "time_to_first_token_ms": (
                            round((first_token_at - started_at) * 1000, 2)
                            if first_token_at is not None
                            else None
                        ),
                        "total_duration_ms": nanoseconds_to_ms(raw_metrics.get("total_duration")),
                        "load_duration_ms": nanoseconds_to_ms(raw_metrics.get("load_duration")),
                        "prompt_eval_count": raw_metrics.get("prompt_eval_count"),
                        "prompt_eval_cached_count": raw_metrics.get("prompt_eval_cached_count"),
                        "prompt_eval_duration_ms": nanoseconds_to_ms(
                            raw_metrics.get("prompt_eval_duration")
                        ),
                        "eval_count": eval_count,
                        "eval_duration_ms": nanoseconds_to_ms(eval_duration),
                        "tokens_per_second": tokens_per_second(eval_count, eval_duration),
                    }

                    full_response = "".join(response_parts)
                    assistant_message_id = await persist_assistant(
                        full_response,
                        "complete",
                        metrics,
                        model_name=response_model,
                    )

                    # An empty response is not a successful turn. Without this
                    # guard the user message remains in history without a paired
                    # assistant message, which produces the apparent every-other-
                    # message behaviour on later turns.
                    if assistant_message_id is None:
                        raise OllamaRequestError(
                            "The model completed the turn without producing a response."
                        )

                    saved = True

                    if not memory_command_handled:
                        schedule_memory_extraction(
                            conversation_id=conversation_id,
                            source_message_id=user_message_id,
                            user_message=request.message or stored_user_text,
                            assistant_message=full_response,
                            enabled=auto_extract,
                        )

                    await runtime_events.publish(
                        "jace.state.changed",
                        state="idle",
                        conversation_id=conversation_id,
                        reason="response_complete",
                    )

                    yield ndjson_event(
                        {
                            "type": "done",
                            "model": event.get("model", response_model),
                            "done_reason": event.get("done_reason"),
                            "metrics": metrics,
                            "model_turns": raw_metrics.get("model_turns", 1),
                            "tool_calls": raw_metrics.get("tool_calls", 0),
                            "diagnostics": {
                                "preprocess_ms": preprocess_ms,
                                "memory_retrieval_used": memory_retrieval_used,
                                "memory_retrieval_ms": memory_retrieval_ms,
                                "memory_count": len(memory_hits),
                                "tool_routing_ms": tool_routing_ms,
                                "tool_names": routed_tools,
                                "history_messages": len(history),
                                "history_chars": history_chars,
                                "response_model": response_model,
                                "attachment_count": len(current_attachment_ids),
                                "attachment_image_count": len(attachment_images),
                                "attachment_processing_ms": attachment_processing_ms,
                            },
                        }
                    )
                    return

        except asyncio.CancelledError:
            if response_parts and not saved:
                await asyncio.shield(
                    persist_assistant(
                        "".join(response_parts),
                        "stopped",
                        model_name=response_model,
                    )
                )
            raise

        except (OllamaUnavailableError, OllamaRequestError) as exc:
            if response_parts and not saved:
                await persist_assistant(
                    "".join(response_parts),
                    "error",
                    model_name=response_model,
                )
                saved = True
            yield ndjson_event({"type": "error", "message": str(exc)})

        except Exception as exc:
            if response_parts and not saved:
                await persist_assistant(
                    "".join(response_parts),
                    "error",
                    model_name=response_model,
                )
            yield ndjson_event(
                {
                    "type": "error",
                    "message": f"Unexpected streaming error: {exc}",
                }
            )

        finally:
            await chat_activity.end()
            if runtime_events.state != "offline":
                await runtime_events.publish(
                    "jace.state.changed",
                    state="idle",
                    conversation_id=conversation_id,
                    reason="stream_finished",
                )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
