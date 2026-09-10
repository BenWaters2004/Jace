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


_NAMED_AGENT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("research", r"\b(?:research|researcher)\s+agent\b"),
    ("code", r"\b(?:code|coding|developer|software)\s+agent\b"),
    ("files", r"\b(?:file|files|filesystem)\s+agent\b"),
    ("analyst", r"\b(?:analyst|analysis)\s+agent\b"),
    ("general", r"\bgeneral\s+agent\b"),
)


def _choose_agent(lowered: str) -> str:
    for agent_id, pattern in _NAMED_AGENT_PATTERNS:
        if re.search(pattern, lowered):
            return agent_id

    # No specialist was named. Pick a sensible worker from the work itself.
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

    # Remove conversational wrappers so the office shows a useful compact title.
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
    Detect a *command to create* a background agent task.

    This intentionally does not match result/status questions such as:
      "What did the agent find?"
      "Has the Analyst Agent finished?"
    """

    text = " ".join((message or "").strip().split())
    if not text:
        return None

    lowered = text.casefold()

    # Result/status/cancel follow-ups are not new delegations, even when they
    # mention a named agent.
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

    named_agent = any(
        re.search(pattern, lowered)
        for _, pattern in _NAMED_AGENT_PATTERNS
    )

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

    # Explicit "agent" command OR a clear request to perform work in the
    # background. Mere discussion about agents does not qualify.
    if not delegation_verb and not explicit_background:
        return None

    # "Tell me about background agents" contains the words but is explanatory,
    # not a task-creation request.
    if not named_agent and explicit_background:
        work_verb = bool(
            re.search(
                r"\b(?:research|investigate|analyse|analyze|compare|inspect|review|"
                r"check|look into|find out|work on|fix|debug|build|write|organise|"
                r"organize|process|calculate|summari[sz]e)\b",
                lowered,
            )
        )
        if not work_verb:
            return None

    agent_id = _choose_agent(lowered)

    return ExplicitDelegationPlan(
        agent_id=agent_id,
        title=_delegation_title(text, agent_id),
        # Preserve the user's actual wording. The specialist prompt already
        # explains that this is a delegated background task.
        instruction=text,
    )


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

        # Only expose delegate_agent_task when this is genuinely a command to
        # create work. Named-agent status questions no longer accidentally get
        # the delegation tool too.
        if parse_explicit_delegation(text) is not None:
            selected.add("delegate_agent_task")

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
            r"\b(?:"
            r"check (?:on )?(?:the )?(?:agent|background) (?:task|job)|"
            r"what did (?:the )?(?:research|code|coding|file|files|analyst|general) agent "
            r"(?:find|do|return|say)|"
            r"what has (?:the )?(?:research|code|coding|file|files|analyst|general) agent "
            r"(?:found|done|returned)|"
            r"agent result|background result|"
            r"is .* agent .* finished"
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

        generic_result_follow_up = bool(
            re.search(
                r"\b(?:"
                r"what did (?:the )?agent (?:find|do|return|say|come back with)|"
                r"what has (?:the )?agent (?:found|done|returned)|"
                r"what(?:'s| is) (?:the )?agent(?:'s)? "
                r"(?:result|output|answer|finding|findings)|"
                r"show me (?:the )?agent(?:'s)? (?:result|output|findings)|"
                r"give me (?:the )?agent(?:'s)? (?:result|output|findings)|"
                r"did (?:the )?agent finish|"
                r"has (?:the )?agent finished|"
                r"what came back from (?:the )?agent|"
                r"what did (?:the )?background (?:task|job|agent) "
                r"(?:find|return|produce)|"
                r"background (?:task|job) result"
                r")\b",
                lowered,
            )
        )

        pronoun_result_follow_up = bool(
            re.fullmatch(
                r"(?:"
                r"what did it (?:find|return|say|come back with)|"
                r"what has it (?:found|returned|done)|"
                r"what came back|"
                r"what did they (?:find|return|say)|"
                r"what(?:'s| is) the result|"
                r"and the result\??|"
                r"any result\??"
                r")\??",
                lowered,
            )
        )

        if generic_result_follow_up or pronoun_result_follow_up:
            selected.add("get_latest_agent_result")

        if re.search(
            r"\b(?:cancel|stop|abort)\b.{0,35}\b(?:agent|background|task|job)\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "cancel_agent_task"})

        return selected

    return route
