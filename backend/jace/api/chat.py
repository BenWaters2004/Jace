import asyncio
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from jace.ai.engine import OllamaRequestError, OllamaUnavailableError
from jace.model_gateway.providers.cloud_common import CloudProviderError
from jace.model_gateway.gateway import ModelGatewayError
from jace.model_gateway.smart_router import select_route
from jace.model_gateway.reliability import ReliabilityPolicy, provider_reliability, ProviderReliabilityError
from jace.model_gateway.cutover import (
    ChatCutoverConfigurationError, choose_chat_model,
)
from jace.ai.prompts import (
    PERSONALITY_ANCHOR,
    VOICE_RESPONSE_STYLE,
    build_tool_context,
)
from jace.attachments.processors import prepare_attachments
from jace.capabilities.runtime import resolve_runtime_capabilities
from jace.calendar.write_continuation import calendar_capability_message
from jace.computer.host_context import host_context_message
from jace.calendar.write_routing import compact_calendar_write_tools
from jace.attachments.service import assign_attachments_to_message, get_attachments
from jace.api.helpers import ndjson_event, nanoseconds_to_ms, tokens_per_second
from jace.config import settings as env_settings
from jace.database import SessionLocal
from jace.auth.actor_context import require_actor
from jace.auth.resource_ownership import require_or_claim_local
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
logger = logging.getLogger("uvicorn.error")


@router.post("/stream")
async def send_streaming_chat(
    request: PersistentChatRequest,
    http_request: Request,
):
    # JACE_4B4A2_CHAT_ACTOR
    actor = await require_actor(http_request)
    if not request.message.strip() and not request.attachment_ids:
        raise HTTPException(status_code=400, detail="Enter a message or attach a file.")
    if len(request.attachment_ids) > env_settings.attachment_max_count:
        raise HTTPException(status_code=400, detail="Too many attachments for one message.")

    async with SessionLocal() as session:
        conversation = await get_conversation(session, request.conversation_id)
        if conversation is not None:
            await require_or_claim_local(
                session,
                resource_kind="conversation",
                resource_id=conversation.id,
                actor_id=actor.actor_id,
                client_id=actor.client_id,
                server_mode=actor.server_mode,
            )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        profile = await get_or_create_assistant_settings(session)
        try:
            conversation_model = choose_chat_model(
                request.model or conversation.model or profile.default_model,
                cutover_enabled=env_settings.cloud_chat_cutover,
                fast_route=env_settings.model_route_conversation_fast,
                auto_enabled=env_settings.smart_routing_enabled,
            )
        except ChatCutoverConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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
            raise HTTPException(status_code=400, detail="One or more attachments are unavailable for this conversation.")

        attachment_names = ", ".join(item.original_name for item in attachments)
        stored_user_text = request.message.strip()
        if not stored_user_text:
            stored_user_text = f"Attached {len(attachments)} file(s): {attachment_names}"

        # JACE_STEP3_RICH_CHAT_PHASE3E2_RETRY
        retry_assistant_message_id = request.retry_assistant_message_id
        if retry_assistant_message_id:
            conversation_messages = list(conversation.messages)
            if len(conversation_messages) < 2:
                raise HTTPException(status_code=409, detail="There is no completed response to retry.")

            retry_assistant_message = conversation_messages[-1]
            retry_user_message = conversation_messages[-2]
            if (
                retry_assistant_message.id != retry_assistant_message_id
                or retry_assistant_message.role != "assistant"
                or retry_user_message.role != "user"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Try again is only available for the latest assistant response.",
                )
            if (
                request.retry_user_message_id
                and retry_user_message.id != request.retry_user_message_id
            ):
                raise HTTPException(status_code=409, detail="The retry source message no longer matches this response.")

            expected_attachment_ids = [
                item.id for item in getattr(retry_user_message, "attachments", [])
            ]
            if set(request.attachment_ids) != set(expected_attachment_ids):
                raise HTTPException(
                    status_code=400,
                    detail="The retry must use the original message attachments.",
                )

            stored_user_text = retry_user_message.content
            user_message_id = retry_user_message.id
        else:
            user_message = await store_user_message(session, conversation, stored_user_text)
            user_message_id = user_message.id
            if attachments:
                await assign_attachments_to_message(session, attachments, user_message_id)

        memory_command = (
            None
            if retry_assistant_message_id
            else (detect_memory_command(request.message) if request.message.strip() else None)
        )
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
                except (OllamaUnavailableError, OllamaRequestError, CloudProviderError, ModelGatewayError, ProviderReliabilityError) as exc:
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
        if (
            retry_assistant_message_id
            and history
            and history[-1].get("role") == "assistant"
        ):
            # Regenerate from the original user turn, not from the answer being replaced.
            history = history[:-1]
        history_chars = sum(len(message.get("content", "")) for message in history)
        conversation_id = conversation.id
        conversation_system_prompt = conversation.system_prompt

        # Copy primitive settings while the session is active.
        reasoning_mode = request.reasoning_mode or profile.reasoning_mode
        temperature = request.temperature if request.temperature is not None else profile.temperature
        memory_top_k = profile.memory_top_k
        memory_min_similarity = profile.memory_min_similarity
        auto_extract = bool(profile.memory_auto_extract and memory_allowed)
        # include_anchor=False: the personality anchor is appended below, after
        # memory/tool/voice context, so tool policy is never the final thing the
        # model reads before it answers.
        profile_prompt = build_profile_prompt(
            profile,
            conversation_system_prompt,
            include_anchor=False,
        )
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

            if retry_assistant_message_id:
                message = next(
                    (
                        item
                        for item in current.messages
                        if item.id == retry_assistant_message_id and item.role == "assistant"
                    ),
                    None,
                )
                if message is None:
                    return None

                metric_values = metrics or {}
                message.content = content
                message.status = status
                message.model = model_name or conversation_model
                message.time_to_first_token_ms = metric_values.get("time_to_first_token_ms")
                message.total_duration_ms = metric_values.get("total_duration_ms")
                message.load_duration_ms = metric_values.get("load_duration_ms")
                message.prompt_eval_count = metric_values.get("prompt_eval_count")
                message.prompt_eval_cached_count = metric_values.get("prompt_eval_cached_count")
                message.prompt_eval_duration_ms = metric_values.get("prompt_eval_duration_ms")
                message.eval_count = metric_values.get("eval_count")
                message.eval_duration_ms = metric_values.get("eval_duration_ms")
                message.tokens_per_second = metric_values.get("tokens_per_second")
                # update_conversation commits the tracked message replacement too.
                await update_conversation(session, current)
                await session.refresh(message)
                return message.id

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
        memory_retrieval_error = False
        response_model = conversation_model
        route_selection = None

        await chat_activity.begin()
        await runtime_events.publish("jace.state.changed", state="thinking", conversation_id=conversation_id)
        try:
            if conversation_model == "auto":
                route_selection = select_route(
                    message=request.message or stored_user_text,
                    reasoning_mode=reasoning_mode,
                    fast_route=env_settings.model_route_conversation_fast,
                    balanced_route=env_settings.model_route_conversation_balanced,
                    deep_route=env_settings.model_route_reasoning_high,
                    coding_route=env_settings.model_route_coding_high,
                    research_route=env_settings.model_route_research_high,
                )
                response_model = route_selection.route
                # C3B: only Auto can preselect a healthy fast-route fallback.
                # This is a circuit-open check BEFORE any inference/tool action.
                policy = ReliabilityPolicy.from_settings(env_settings)
                if (
                    policy.enabled
                    and env_settings.cloud_auto_fast_fallback
                    and response_model != env_settings.model_route_conversation_fast.strip()
                    and provider_reliability.circuit_open(response_model)
                ):
                    alternative = env_settings.model_route_conversation_fast.strip()
                    if alternative and not provider_reliability.circuit_open(alternative):
                        response_model = alternative
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
                        session, current_attachments
                    )
            attachment_processing_ms = round((time.perf_counter() - attachment_started) * 1000, 2)

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
                        try:
                            memory_hits = await search_memories(
                                session,
                                request.message,
                                limit=memory_top_k,
                                min_similarity=memory_min_similarity,
                                update_access=True,
                            )
                        except (OllamaUnavailableError, OllamaRequestError,
                                CloudProviderError, ModelGatewayError, ProviderReliabilityError) as exc:
                            if not env_settings.cloud_chat_cutover:
                                raise
                            memory_retrieval_error = True
                            logger.warning(
                                "Memory retrieval unavailable during cloud chat; "
                                "continuing without retrieved memories (%s)", type(exc).__name__
                            )
            memory_retrieval_ms = round((time.perf_counter() - memory_started) * 1000, 2)

            # JACE_STEP4A4_CHAT_RESOLUTION
            tool_started = time.perf_counter()
            # JACE_STEP4C5B_V2_WRITE_CONTINUATION_CHAT
            raw_user_message = request.message or stored_user_text
            # JACE_STEP4B2_V3_HOST_CONTEXT_CHAT
            host_message = host_context_message(
                raw_user_message,
                history,
            )
            capability_message = calendar_capability_message(
                host_message,
                history,
            )
            routed_tools = await routed_tool_names(
                capability_message
            )

            async with SessionLocal() as session:
                capability_plan = await resolve_runtime_capabilities(
                    session,
                    capability_message,
                )

            for capability_tool_name in capability_plan.tool_names:
                if capability_tool_name not in routed_tools:
                    routed_tools.append(capability_tool_name)

            # JACE_STEP4C5B_DETERMINISTIC_WRITE_COMPACTION
            # Compact Calendar write turns only after the runtime capability
            # resolver has supplied an executable provider write tool.
            routed_tools = compact_calendar_write_tools(
                capability_message,
                routed_tools,
                capability_plan.tool_names,
            )

            routed_tools = sorted(set(routed_tools))

            if current_attachment_ids:
                routed_tools = [
                    name
                    for name in routed_tools
                    if name != "inspect_attachment"
                ]

            tool_routing_ms = round(
                (time.perf_counter() - tool_started) * 1000,
                2,
            )

            multimodal_tool_names = {
                "inspect_attachment",
                "inspect_workspace_media",
                "capture_screen",
                "inspect_host_media",
            }
            use_specialist_vision = bool(
                env_settings.vision_model.strip()
                and (
                    attachment_images
                    or multimodal_tool_names.intersection(routed_tools)
                )
            )
            # C4D2_FIX1_AUTO_ROUTE: preserve the selected Auto tier unless a
            # specialist vision model is explicitly required. Previously this
            # assignment reset every Auto selection to the literal 'auto'.
            if use_specialist_vision:
                response_model = env_settings.vision_model.strip()

            preprocess_ms = round((time.perf_counter() - started_at) * 1000, 2)

            yield ndjson_event(
                {
                    "type": "context",
                    "memory_count": len(memory_hits),
                    "memory_retrieval_used": memory_retrieval_used,
                    "memory_retrieval_ms": memory_retrieval_ms,
                    "tool_count": len(routed_tools),
                    "tool_names": routed_tools,
                    "capability_needs": [
                        item.as_dict()
                        for item in capability_plan.needs
                    ],
                    "capability_resolutions": [
                        item.as_dict()
                        for item in capability_plan.resolutions
                    ],
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

            # Only the tool policy relevant to the routed tools is included. The
            # previous monolithic block cost ~2,400 tokens on every tool-enabled
            # turn, which crowded out both history and Jace's personality inside
            # a 4k context window.
            tool_context = build_tool_context(
                routed_tools,
                has_attachments=bool(current_attachment_ids),
            )

            prompt_sections = [
                profile_prompt,
                memory_context,
                ("MEMORY STATUS: Memory retrieval was unavailable for this reply. "
                 "Do not claim to have recalled facts from long-term memory. "
                 "Tell the user if this limitation affects the answer.")
                if memory_retrieval_error else "",
                memory_action_context,
                capability_plan.prompt_context(),
                tool_context,
                VOICE_RESPONSE_STYLE if request.voice_mode else "",
                # Always last: recency-weighted identity reminder.
                PERSONALITY_ANCHOR,
            ]

            effective_system_prompt = "\n\n".join(
                section.strip() for section in prompt_sections if section and section.strip()
            )

            async for event in stream_agent(
                model=response_model,
                messages=history,
                system_prompt=effective_system_prompt,
                reasoning_mode=reasoning_mode,
                temperature=temperature,
                conversation_id=conversation_id,
                actor_id=actor.actor_id,
                client_id=actor.client_id,
                # Use the effective capability message for execution policy only.
                # Conversation history still contains the literal follow-up text.
                user_message=capability_message,
                tool_names=routed_tools,
                current_images=attachment_images,
                attachment_context=attachment_context,
                capability_bindings=capability_plan.tool_bindings,
            ):
                event_type = event.get("type")

                if event_type == "token":
                    content = event.get("content") or ""
                    if content:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                            await runtime_events.publish("jace.state.changed", state="working", conversation_id=conversation_id, reason="responding")
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
                        await runtime_events.publish("jace.state.changed", state="working", reason="tool", conversation_id=conversation_id)
                    elif event_type == "approval_required":
                        await runtime_events.publish(
                            "permission.requested",
                            conversation_id=conversation_id,
                            tool_name=event.get("tool_name"),
                            label=event.get("label"),
                            risk=event.get("risk"),
                        )
                        await runtime_events.publish("jace.state.changed", state="waiting_permission", conversation_id=conversation_id)
                    else:
                        await runtime_events.publish(
                            "tool.completed",
                            conversation_id=conversation_id,
                            tool_name=event.get("tool_name"),
                            status=event.get("status"),
                            summary=event.get("summary"),
                        )
                        await runtime_events.publish("jace.state.changed", state="thinking", conversation_id=conversation_id)
                    yield ndjson_event(event)
                    continue

                if event_type == "agent_done":
                    # C4D2_FIX1_OBSERVED: only the gateway's completed chunk can
                    # identify the provider used. Configuration is not proof.
                    observed_provider = str(event.get("model_provider") or "").strip().lower()
                    observed_model = str(event.get("model") or "").strip()
                    if observed_provider in {"openai", "anthropic", "ollama"} and observed_model:
                        bare_model = (observed_model[len(observed_provider) + 1:]
                                      if observed_model.startswith(observed_provider + ":")
                                      else observed_model)
                        observed_route = f"{observed_provider}:{bare_model}"
                    else:
                        observed_route = None
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
                        model_name=observed_route or response_model,
                    )
                    saved = True
                    if (
                        not memory_command_handled
                        and not retry_assistant_message_id
                        and assistant_message_id
                    ):
                        schedule_memory_extraction(
                            conversation_id=conversation_id,
                            source_message_id=user_message_id,
                            user_message=request.message or stored_user_text,
                            assistant_message=full_response,
                            enabled=auto_extract,
                        )

                    await runtime_events.publish("jace.state.changed", state="idle", conversation_id=conversation_id, reason="response_complete")

                    yield ndjson_event(
                        {
                            "type": "done",
                            "model": observed_route or event.get("model", response_model),
                            "model_provider": observed_provider if observed_route else None,
                            "provider_observed": bool(observed_route),
                            "selected_model_route": response_model,
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
                                "capability_resolutions": [
                                    item.as_dict()
                                    for item in capability_plan.resolutions
                                ],
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
        except (OllamaUnavailableError, OllamaRequestError, CloudProviderError, ModelGatewayError, ProviderReliabilityError) as exc:
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
                await runtime_events.publish("jace.state.changed", state="idle", conversation_id=conversation_id, reason="stream_finished")

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
