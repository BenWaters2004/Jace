from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Callable

from jace.tools.agent_routing import build_forced_delegation_call


logger = logging.getLogger("uvicorn.error")


def wrap_stream_agent(base_stream_agent: Callable[..., AsyncIterator[dict[str, Any]]]):
    """
    Add deterministic execution for explicit background-agent commands.

    Jace's normal tool loop remains model-directed for ordinary tool usage.
    Delegation is special: if the user explicitly says "have the Analyst Agent
    do X in the background", merely *offering* delegate_agent_task to a small
    local model is not reliable enough. This wrapper executes that already
    routed tool call through the existing approval/audit machinery first, then
    gives the real application result back to the model for a short natural
    acknowledgement.

    No permission is bypassed.
    """

    async def stream_agent_with_delegation(
        *,
        model: str,
        messages: list[dict[str, Any]],
        system_prompt: str,
        reasoning_mode: str,
        temperature: float,
        conversation_id: str | None,
        user_message: str,
        tool_names: list[str] | None = None,
        current_images: list[str] | None = None,
        attachment_context: str = "",
    ):
        names = list(tool_names or [])

        forced_call = build_forced_delegation_call(
            user_message,
            reasoning_mode=reasoning_mode,
            available_tool_names=names,
        )

        if forced_call is None:
            async for event in base_stream_agent(
                model=model,
                messages=messages,
                system_prompt=system_prompt,
                reasoning_mode=reasoning_mode,
                temperature=temperature,
                conversation_id=conversation_id,
                user_message=user_message,
                tool_names=tool_names,
                current_images=current_images,
                attachment_context=attachment_context,
            ):
                yield event
            return

        from jace.tools.agent import _execute_tool_call

        function = forced_call["function"]
        arguments = function.get("arguments") or {}

        logger.info(
            "Deterministic background delegation requested: agent=%s title=%r conversation=%s",
            arguments.get("agent_id"),
            arguments.get("title"),
            conversation_id,
        )

        tool_message: dict[str, Any] | None = None
        public_result_summary = ""

        async for event in _execute_tool_call(
            call=forced_call,
            conversation_id=conversation_id,
            user_message=user_message,
        ):
            if event.get("type") == "_tool_message":
                tool_message = event.get("message")
                continue

            if event.get("type") == "tool_result":
                public_result_summary = str(event.get("summary") or "")

            yield event

        if tool_message is None:
            tool_message = {
                "role": "tool",
                "tool_name": "delegate_agent_task",
                "content": (
                    "The deterministic delegation attempt did not return a tool result. "
                    "Do not claim that a background task was created."
                ),
            }

        tool_content = str(tool_message.get("content") or "")
        logger.info(
            "Deterministic background delegation resolved: %s",
            (public_result_summary or tool_content).replace("\n", " ")[:700],
        )

        delegation_context = (
            "\n\nDETERMINISTIC AGENT DELEGATION\n"
            "Jace has already processed the user's explicit background-agent request "
            "through the application's real delegation and permission system. Do NOT "
            "try to delegate it again and do NOT claim a task exists unless the result "
            "below says it was created.\n\n"
            f"APPLICATION RESULT:\n{tool_content}\n\n"
            "Respond naturally and briefly to the user using that real result. If the "
            "task was created, make clear it is running asynchronously and the main "
            "conversation can continue. If it was denied or failed, say so accurately.\n"
            "END DETERMINISTIC AGENT DELEGATION"
        )

        # Delegation has already happened. The acknowledgement turn gets no
        # primary-chat tools, preventing Qwen from launching a duplicate task or
        # doing the delegated research itself.
        async for event in base_stream_agent(
            model=model,
            messages=messages,
            system_prompt=system_prompt + delegation_context,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            conversation_id=conversation_id,
            user_message=user_message,
            tool_names=[],
            current_images=current_images,
            attachment_context=attachment_context,
        ):
            if event.get("type") == "agent_done":
                metrics = dict(event.get("metrics") or {})
                metrics["tool_calls"] = int(metrics.get("tool_calls") or 0) + 1
                event = {**event, "metrics": metrics}
            yield event

    setattr(stream_agent_with_delegation, "_jace_agent_delegation_bridge", True)
    return stream_agent_with_delegation
