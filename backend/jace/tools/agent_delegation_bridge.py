from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Callable

from jace.tools.agent_routing import (
    build_forced_agent_result_call,
    build_forced_delegation_call,
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
    Explicit delegation and result retrieval are application actions, not guesses.

    Delegation:
      execute the real tool first, then let Jace phrase a short acknowledgement.

    Result/status lookup:
      execute the real tool and stream its authoritative content DIRECTLY to chat.
      Do not pass it through another model turn, because a small model can ignore
      the supplied result and hallucinate that the agent is unavailable.
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
                "Deterministic background delegation requested: "
                "agent=%s title=%r conversation=%s",
                arguments.get("agent_id"),
                arguments.get("title"),
                conversation_id,
            )
        else:
            logger.info(
                "Deterministic agent result lookup requested: "
                "agent=%s conversation=%s",
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

        # ------------------------------------------------------------------
        # RESULT LOOKUPS ARE FINAL APPLICATION DATA.
        # ------------------------------------------------------------------
        if tool_name == "get_latest_agent_result":
            logger.info(
                "Deterministic agent result lookup resolved: %s",
                (public_summary or tool_content).replace("\n", " ")[:1200],
            )

            answer = tool_content or "No agent result was returned."

            # This becomes a normal assistant chat message via api/chat.py.
            # No second Ollama generation can overwrite or contradict it.
            yield {"type": "token", "content": answer}
            yield {
                "type": "agent_done",
                "model": model,
                "done_reason": "application_result",
                "metrics": _direct_done_metrics(),
            }
            return

        # ------------------------------------------------------------------
        # DELEGATION IS REAL, THEN JACE MAY PHRASE THE ACKNOWLEDGEMENT.
        # ------------------------------------------------------------------
        logger.info(
            "Deterministic background delegation resolved: %s",
            (public_summary or tool_content).replace("\n", " ")[:900],
        )

        forced_context = (
            "\n\nDETERMINISTIC AGENT DELEGATION\n"
            "The application has already processed the user's background-agent request. "
            "The following is the authoritative application result:\n\n"
            f"{tool_content}\n\n"
            "Acknowledge it briefly and naturally. Do not perform the delegated task "
            "yourself. Do not wait for the background specialist. Do not launch another "
            "copy of the task. The main conversation remains available.\n"
            "END DETERMINISTIC AGENT DELEGATION"
        )

        async for event in base_stream_agent(
            model=model,
            messages=messages,
            system_prompt=system_prompt + forced_context,
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

    setattr(
        stream_agent_with_delegation,
        "_jace_agent_delegation_bridge",
        True,
    )
    return stream_agent_with_delegation
