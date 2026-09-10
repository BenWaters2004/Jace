from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Callable

from jace.tools.agent_routing import (
    build_forced_agent_result_call,
    build_forced_delegation_call,
)


logger = logging.getLogger("uvicorn.error")


async def _execute_forced_tool(
    *,
    call: dict[str, Any],
    conversation_id: str | None,
    user_message: str,
):
    from jace.tools.agent import _execute_tool_call

    private_message: dict[str, Any] | None = None
    public_summary = ""

    async for event in _execute_tool_call(
        call=call,
        conversation_id=conversation_id,
        user_message=user_message,
    ):
        if event.get("type") == "_tool_message":
            private_message = event.get("message")
            continue

        if event.get("type") == "tool_result":
            public_summary = str(event.get("summary") or "")

        yield event

    return_value = {
        "tool_message": private_message,
        "summary": public_summary,
    }
    yield {
        "type": "_forced_tool_complete",
        "value": return_value,
    }


async def _run_forced_call_and_capture(
    *,
    call: dict[str, Any],
    conversation_id: str | None,
    user_message: str,
):
    tool_message: dict[str, Any] | None = None
    public_summary = ""

    async for event in _execute_forced_tool(
        call=call,
        conversation_id=conversation_id,
        user_message=user_message,
    ):
        if event.get("type") == "_forced_tool_complete":
            value = event.get("value") or {}
            tool_message = value.get("tool_message")
            public_summary = str(value.get("summary") or "")
            continue

        yield event

    yield {
        "type": "_forced_capture",
        "tool_message": tool_message,
        "summary": public_summary,
    }


def wrap_stream_agent(base_stream_agent: Callable[..., AsyncIterator[dict[str, Any]]]):
    """
    Deterministic bridge for two operations that must not be left to a small
    local model's discretion:

    1. Explicitly requested background delegation.
    2. Explicitly requested retrieval/status of an existing background job.

    Both still execute through Jace's existing tool permission and audit layer.
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

        forced_delegation = build_forced_delegation_call(
            user_message,
            reasoning_mode=reasoning_mode,
            available_tool_names=names,
        )

        forced_result = None
        if forced_delegation is None:
            forced_result = build_forced_agent_result_call(
                user_message,
                available_tool_names=names,
            )

        forced_call = forced_delegation or forced_result

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

        function = forced_call["function"]
        tool_name = function["name"]
        arguments = function.get("arguments") or {}

        if tool_name == "delegate_agent_task":
            logger.info(
                "Deterministic background delegation requested: agent=%s title=%r conversation=%s",
                arguments.get("agent_id"),
                arguments.get("title"),
                conversation_id,
            )
        else:
            logger.info(
                "Deterministic agent result lookup requested: agent=%s conversation=%s",
                arguments.get("agent_id") or "latest",
                conversation_id,
            )

        tool_message: dict[str, Any] | None = None
        public_result_summary = ""

        async for event in _run_forced_call_and_capture(
            call=forced_call,
            conversation_id=conversation_id,
            user_message=user_message,
        ):
            if event.get("type") == "_forced_capture":
                tool_message = event.get("tool_message")
                public_result_summary = str(event.get("summary") or "")
                continue

            yield event

        if tool_message is None:
            tool_message = {
                "role": "tool",
                "tool_name": tool_name,
                "content": (
                    f"The deterministic {tool_name} operation did not return a tool result. "
                    "Do not claim that it succeeded."
                ),
            }

        tool_content = str(tool_message.get("content") or "")

        if tool_name == "delegate_agent_task":
            logger.info(
                "Deterministic background delegation resolved: %s",
                (public_result_summary or tool_content).replace("\n", " ")[:700],
            )

            forced_context = (
                "\n\nDETERMINISTIC AGENT DELEGATION\n"
                "Jace has already processed the user's explicit background-agent request "
                "through the application's real delegation and permission system. Do NOT "
                "try to delegate it again and do NOT claim a task exists unless the result "
                "below says it was created.\n\n"
                f"APPLICATION RESULT:\n{tool_content}\n\n"
                "Respond naturally and briefly using that real result. If the task was "
                "created, say it is running asynchronously and the main conversation can "
                "continue. If it was denied or failed, say so accurately.\n"
                "END DETERMINISTIC AGENT DELEGATION"
            )
        else:
            logger.info(
                "Deterministic agent result lookup resolved: %s",
                (public_result_summary or tool_content).replace("\n", " ")[:900],
            )

            forced_context = (
                "\n\nDETERMINISTIC AGENT RESULT\n"
                "The application has already retrieved the real persisted background-agent "
                "record requested by the user. This data is authoritative. Do NOT claim "
                "that the agent is unavailable, that its output is inaccessible, that it "
                "must write to a memory vault, or that the user needs to provide the output.\n\n"
                f"APPLICATION RESULT:\n{tool_content}\n\n"
                "Answer the user's question directly from this result. If it is still "
                "running, report its actual status. If it failed, report the actual error. "
                "If it completed, summarise/communicate its real findings naturally.\n"
                "END DETERMINISTIC AGENT RESULT"
            )

        async for event in base_stream_agent(
            model=model,
            messages=messages,
            system_prompt=system_prompt + forced_context,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            conversation_id=conversation_id,
            user_message=user_message,
            # The required operation already happened. Removing tools prevents
            # duplicate delegation/lookups and forces a user-facing answer.
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
