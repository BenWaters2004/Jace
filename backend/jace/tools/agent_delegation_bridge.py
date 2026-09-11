from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any, Callable

from jace.tools.agent_routing import (
    build_forced_agent_result_call,
    build_forced_delegation_call,
    build_forced_director_call,
)

logger = logging.getLogger("uvicorn.error")


async def _run_tool(
    *,
    call: dict[str, Any],
    conversation_id: str | None,
    user_message: str,
):
    from jace.tools.agent import _execute_tool_call

    tool_message: dict[str, Any] | None = None
    public_summary = ""
    async for event in _execute_tool_call(
        call=call,
        conversation_id=conversation_id,
        user_message=user_message,
    ):
        if event.get("type") == "_tool_message":
            tool_message = event.get("message")
            continue
        if event.get("type") == "tool_result":
            public_summary = str(event.get("summary") or "")
        yield event
    yield {
        "type": "_jace_forced_tool_capture",
        "tool_message": tool_message,
        "summary": public_summary,
    }


def _direct_done_metrics() -> dict[str, Any]:
    return {
        "total_duration": None,
        "load_duration": None,
        "prompt_eval_count": None,
        "prompt_eval_cached_count": None,
        "prompt_eval_duration": None,
        "eval_count": None,
        "eval_duration": None,
        "model_turns": 0,
        "tool_calls": 1,
    }


def wrap_stream_agent(
    base_stream_agent: Callable[..., AsyncIterator[dict[str, Any]]],
):
    """
    Explicit specialist delegation, open-ended Agent Director delegation and
    result retrieval are application actions rather than model guesses.

    The real tool executes first. Jace may phrase a short acknowledgement only
    after the application has accepted the task/workflow.
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

        forced_director = build_forced_director_call(
            user_message,
            reasoning_mode=reasoning_mode,
            available_tool_names=names,
        )
        forced_delegation = None
        forced_result = None
        if forced_director is None:
            forced_delegation = build_forced_delegation_call(
                user_message,
                reasoning_mode=reasoning_mode,
                available_tool_names=names,
            )
        if forced_director is None and forced_delegation is None:
            forced_result = build_forced_agent_result_call(
                user_message,
                available_tool_names=names,
            )

        forced_call = forced_director or forced_delegation or forced_result
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
        if tool_name == "delegate_agent_director":
            logger.info(
                "Deterministic Agent Director requested: objective=%r conversation=%s",
                str(arguments.get("objective") or "")[:300],
                conversation_id,
            )
        elif tool_name == "delegate_agent_task":
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
        public_summary = ""
        async for event in _run_tool(
            call=forced_call,
            conversation_id=conversation_id,
            user_message=user_message,
        ):
            if event.get("type") == "_jace_forced_tool_capture":
                tool_message = event.get("tool_message")
                public_summary = str(event.get("summary") or "")
                continue
            yield event

        if tool_message is None:
            tool_message = {
                "role": "tool",
                "tool_name": tool_name,
                "content": f"{tool_name} did not return a result.",
            }
        tool_content = str(tool_message.get("content") or "").strip()

        if tool_name == "get_latest_agent_result":
            logger.info(
                "Deterministic agent result lookup resolved: %s",
                (public_summary or tool_content).replace("\n", " ")[:1200],
            )
            answer = tool_content or "No agent result was returned."
            yield {"type": "token", "content": answer}
            yield {
                "type": "agent_done",
                "model": model,
                "done_reason": "application_result",
                "metrics": _direct_done_metrics(),
            }
            return

        if tool_name == "delegate_agent_director":
            logger.info(
                "Deterministic Agent Director accepted: %s",
                (public_summary or tool_content).replace("\n", " ")[:900],
            )
            match = re.search(
                r"Workflow ID:\s*([0-9a-fA-F-]{20,})",
                tool_content or public_summary,
            )
            workflow_id = match.group(1) if match else "unknown"
            answer = (
                "Agent Director has started this in the background "
                f"(Workflow ID: {workflow_id}). "
                "This conversation stays available while it chooses and coordinates the specialists. "
                "I’ll surface one combined handoff when the workflow finishes."
            )
            yield {"type": "token", "content": answer}
            yield {
                "type": "agent_done",
                "model": model,
                "done_reason": "application_result",
                "metrics": _direct_done_metrics(),
            }
            return

        logger.info(
            "Deterministic background delegation resolved: %s",
            (public_summary or tool_content).replace("\n", " ")[:900],
        )
        match = re.search(r"Task ID:\s*([0-9a-fA-F-]{20,})", tool_content or public_summary)
        task_id = match.group(1) if match else "unknown"
        agent_match = re.search(r"dispatched the ([^\n.]+?) to", tool_content, flags=re.IGNORECASE)
        agent_name = agent_match.group(1).strip() if agent_match else "background specialist"
        answer = (
            f"Delegated to the {agent_name} in the background (Task ID: {task_id}). "
            "This conversation stays available while it works; I’ll surface the result when it finishes."
        )
        yield {"type": "token", "content": answer}
        yield {
            "type": "agent_done",
            "model": model,
            "done_reason": "application_result",
            "metrics": _direct_done_metrics(),
        }
        return

    setattr(stream_agent_with_delegation, "_jace_agent_delegation_bridge", True)
    return stream_agent_with_delegation
