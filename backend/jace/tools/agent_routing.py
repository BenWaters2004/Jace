from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


AGENT_TOOL_NAMES = {
    "delegate_agent_task",
    "check_agent_task",
    "list_agent_tasks",
    "get_latest_agent_result",
    "cancel_agent_task",
}


@dataclass(frozen=True)
class ExplicitDelegationPlan:
    agent_id: str
    title: str
    instruction: str


@dataclass(frozen=True)
class AgentResultPlan:
    agent_id: str | None


_NAMED_AGENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("research", r"\b(?:research|researcher)\s+agent\b"),
    ("code", r"\b(?:code|coding|developer|software)\s+agent\b"),
    ("files", r"\b(?:file|files|filesystem)\s+agent\b"),
    ("analyst", r"\b(?:analyst|analysis)\s+agent\b"),
    ("general", r"\bgeneral\s+agent\b"),
)


def _named_agent(lowered: str) -> str | None:
    for agent_id, pattern in _NAMED_AGENT_PATTERNS:
        if re.search(pattern, lowered):
            return agent_id
    return None


def _choose_agent(lowered: str) -> str:
    named = _named_agent(lowered)
    if named:
        return named

    if re.search(
        r"\b(?:research|investigate|look up|find out|search the web|sources?|"
        r"latest|current information|compare sources)\b",
        lowered,
    ):
        return "research"

    if re.search(
        r"\b(?:code|coding|bug|debug|repository|repo|function|class|typescript|"
        r"javascript|python|php|laravel|react|rust|compile|build error)\b",
        lowered,
    ):
        return "code"

    if re.search(
        r"\b(?:files?|folders?|directory|directories|workspace|organise|organize|"
        r"rename|move|locate)\b",
        lowered,
    ):
        return "files"

    if re.search(
        r"\b(?:analyse|analyze|analysis|compare|calculate|evaluate|assess|"
        r"summarise data|summarize data)\b",
        lowered,
    ):
        return "analyst"

    return "general"


def _delegation_title(message: str, agent_id: str) -> str:
    text = " ".join(message.strip().split())

    patterns = (
        r"^(?:jace[,:\s]+)?",
        r"^(?:please\s+)?(?:have|ask|get|send|delegate|use|run)\s+",
        r"^(?:the\s+)?(?:research|researcher|code|coding|developer|software|"
        r"file|files|filesystem|analyst|analysis|general)\s+agent\s+",
        r"^(?:to\s+)?",
    )

    title = text
    for pattern in patterns:
        title = re.sub(pattern, "", title, count=1, flags=re.IGNORECASE).strip()

    title = re.sub(
        r"\b(?:in|as)\s+(?:a\s+)?background(?:\s+(?:task|job))?\b.*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip(" .,:;-")

    if not title:
        friendly = {
            "research": "Background research",
            "code": "Background code task",
            "files": "Background file task",
            "analyst": "Background analysis",
            "general": "Background task",
        }
        return friendly.get(agent_id, "Background task")

    if len(title) > 92:
        title = title[:89].rstrip() + "..."

    return title[0].upper() + title[1:] if title else "Background task"


def parse_explicit_delegation(message: str) -> ExplicitDelegationPlan | None:
    """
    Detect a command to create a background agent task.

    Result/status/cancel questions are deliberately excluded so they cannot
    accidentally create a second job.
    """

    text = " ".join((message or "").strip().split())
    if not text:
        return None

    lowered = text.casefold()

    if re.search(
        r"^\s*(?:"
        r"what|when|where|why|how|did|has|have|is|are|was|were|show|list|check|"
        r"cancel|stop|abort"
        r")\b",
        lowered,
    ):
        if re.search(
            r"\b(?:agent|background task|background job|result|output|findings?|status)\b",
            lowered,
        ):
            return None

    named_agent = _named_agent(lowered) is not None

    explicit_background = bool(
        re.search(
            r"\b(?:"
            r"in the background|background task|background job|"
            r"while (?:we|you|i) (?:continue|carry on|keep working|talk)|"
            r"without blocking (?:the )?(?:chat|conversation)|"
            r"keep (?:the )?(?:chat|conversation) free"
            r")\b",
            lowered,
        )
    )

    delegation_verb = bool(
        re.search(
            r"\b(?:"
            r"delegate|delegat(?:e|ing)|"
            r"have (?:the )?(?:research|researcher|code|coding|developer|software|"
            r"file|files|filesystem|analyst|analysis|general) agent|"
            r"ask (?:the )?(?:research|researcher|code|coding|developer|software|"
            r"file|files|filesystem|analyst|analysis|general) agent|"
            r"send (?:this|that|it|the task|the job) to (?:the )?.+? agent|"
            r"use (?:the )?.+? agent (?:to|for)|"
            r"get (?:the )?.+? agent to|"
            r"run (?:this|that|it) (?:with|through) (?:the )?.+? agent"
            r")\b",
            lowered,
        )
    )

    if not delegation_verb and not explicit_background:
        return None

    if not named_agent and explicit_background:
        work_verb = bool(
            re.search(
                r"\b(?:research|investigate|analyse|analyze|compare|inspect|review|"
                r"check|look into|find out|work on|fix|debug|build|write|organise|"
                r"organize|process|calculate|summari[sz]e|explain)\b",
                lowered,
            )
        )
        if not work_verb:
            return None

    agent_id = _choose_agent(lowered)

    return ExplicitDelegationPlan(
        agent_id=agent_id,
        title=_delegation_title(text, agent_id),
        instruction=text,
    )


def parse_agent_result_followup(message: str) -> AgentResultPlan | None:
    """
    Resolve natural follow-ups referring to an existing agent task.

    These are deterministic because a small local model should never be
    permitted to answer "I cannot access the agent" when Jace has a real
    persisted result API available.
    """

    text = " ".join((message or "").strip().split())
    if not text:
        return None

    lowered = text.casefold()
    named = _named_agent(lowered)

    generic = bool(
        re.search(
            r"\b(?:"
            r"what did (?:the )?agent (?:find|do|return|say|produce|come back with)|"
            r"what has (?:the )?agent (?:found|done|returned|produced)|"
            r"what(?:'s| is) (?:the )?agent(?:'s)? "
            r"(?:result|output|answer|finding|findings|report)|"
            r"show me (?:the )?agent(?:'s)? (?:result|output|findings|report)|"
            r"give me (?:the )?agent(?:'s)? (?:result|output|findings|report)|"
            r"did (?:the )?agent finish|"
            r"has (?:the )?agent finished|"
            r"is (?:the )?agent finished|"
            r"what came back from (?:the )?agent|"
            r"what did (?:the )?background (?:task|job|agent) "
            r"(?:find|return|produce|say)|"
            r"background (?:task|job|agent) (?:result|output|status|report)"
            r")\b",
            lowered,
        )
    )

    named_followup = bool(
        named
        and re.search(
            r"\b(?:"
            r"what did .* agent (?:find|do|return|say|produce)|"
            r"what has .* agent (?:found|done|returned|produced)|"
            r"what(?:'s| is) .* agent(?:'s)? (?:result|output|report|status)|"
            r"did .* agent finish|"
            r"has .* agent finished|"
            r"is .* agent finished|"
            r"show .* agent(?:'s)? (?:result|output|report)|"
            r"check .* agent"
            r")\b",
            lowered,
        )
    )

    pronoun = bool(
        re.fullmatch(
            r"(?:"
            r"what did it (?:find|return|say|produce|come back with)|"
            r"what has it (?:found|returned|done|produced)|"
            r"what came back|"
            r"what did they (?:find|return|say|produce)|"
            r"what(?:'s| is) the result|"
            r"what(?:'s| is) the output|"
            r"and the result|"
            r"and the output|"
            r"any result|"
            r"any update"
            r")[?.!]*",
            lowered,
        )
    )

    if not (generic or named_followup or pronoun):
        return None

    return AgentResultPlan(agent_id=named)


def build_forced_delegation_call(
    message: str,
    *,
    reasoning_mode: str,
    available_tool_names: list[str] | set[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    if "delegate_agent_task" not in set(available_tool_names):
        return None

    plan = parse_explicit_delegation(message)
    if plan is None:
        return None

    return {
        "type": "function",
        "function": {
            "name": "delegate_agent_task",
            "arguments": {
                "agent_id": plan.agent_id,
                "title": plan.title,
                "instruction": plan.instruction,
                "priority": 0,
                "reasoning_mode": (
                    reasoning_mode
                    if reasoning_mode in {"fast", "balanced", "deep"}
                    else "balanced"
                ),
            },
        },
    }


def build_forced_agent_result_call(
    message: str,
    *,
    available_tool_names: list[str] | set[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    if "get_latest_agent_result" not in set(available_tool_names):
        return None

    plan = parse_agent_result_followup(message)
    if plan is None:
        return None

    arguments: dict[str, Any] = {}
    if plan.agent_id is not None:
        arguments["agent_id"] = plan.agent_id

    return {
        "type": "function",
        "function": {
            "name": "get_latest_agent_result",
            "arguments": arguments,
        },
    }


def extend_agent_tool_route(
    base_router: Callable[[str], set[str]],
) -> Callable[[str], set[str]]:
    """
    Extend Jace's mature smart router with agent delegation/result language.
    """

    def route(message: str) -> set[str]:
        selected = set(base_router(message))

        text = " ".join((message or "").strip().split())
        lowered = text.casefold()

        if not text:
            return selected

        if re.search(r"\b(?:use|show|list)\s+all\s+tools\b", lowered):
            selected.update(AGENT_TOOL_NAMES)
            return selected

        if parse_explicit_delegation(text) is not None:
            selected.add("delegate_agent_task")

        if parse_agent_result_followup(text) is not None:
            selected.add("get_latest_agent_result")

        if re.search(
            r"\b(?:"
            r"what (?:are|is) (?:the )?agents? doing|"
            r"what(?:'s| is) (?:the )?(?:agent|background) status|"
            r"agent (?:tasks?|jobs?|status)|"
            r"background (?:tasks?|jobs?|status)|"
            r"show (?:me )?(?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"list (?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"which agents? (?:are )?(?:working|running|busy)|"
            r"finished background|completed background"
            r")\b",
            lowered,
        ):
            selected.update(
                {
                    "list_agent_tasks",
                    "check_agent_task",
                    "get_latest_agent_result",
                }
            )

        if re.search(
            r"\b(?:cancel|stop|abort)\b.{0,35}\b(?:agent|background|task|job)\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "cancel_agent_task"})

        return selected

    return route
