from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


AGENT_TOOL_NAMES = {
    "delegate_agent_task",
    "delegate_agent_director",
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
class DirectorDelegationPlan:
    objective: str
    title: str


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

_AGENT_NAME_PATTERN = (
    r"(?:research|researcher|code|coding|developer|software|"
    r"file|files|filesystem|analyst|analysis|general)\s+agent"
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
        r"summari[sz]e data)\b",
        lowered,
    ):
        return "analyst"
    return "general"


def _clean_delegated_instruction(message: str) -> str:
    text = " ".join((message or "").strip().split())
    if not text:
        return text
    text = re.sub(r"^(?:hey\s+)?jace[\s,:;-]*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(
        rf"^(?:please\s+)?(?:have|ask|get)\s+(?:the\s+)?{_AGENT_NAME_PATTERN}\s+(?:to\s+)?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        rf"^(?:please\s+)?delegate\s+(?:this|that|it|the task|the job)\s+to\s+"
        rf"(?:the\s+)?{_AGENT_NAME_PATTERN}\s*(?:to\s+)?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        rf"^(?:please\s+)?send\s+(?:this|that|it|the task|the job)\s+to\s+"
        rf"(?:the\s+)?{_AGENT_NAME_PATTERN}\s*(?:to\s+)?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        rf"^(?:please\s+)?use\s+(?:the\s+)?{_AGENT_NAME_PATTERN}\s+(?:to|for)\s+",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"\s*(?:[,;.-]\s*)?(?:in|as)\s+(?:(?:a|the)\s+)?background"
        r"(?:\s+(?:task|job))?(?:[.!?].*)?$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"\s*(?:[,;.-]\s*)?(?:while\s+(?:we|you|i)\s+(?:continue|carry on|keep working|talk)"
        r"|keep\s+(?:this|the)\s+(?:chat|conversation)\s+free"
        r"|without\s+blocking\s+(?:this|the)?\s*(?:chat|conversation)).*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"\s*(?:[,;.-]\s*)?(?:in|as)\s+(?:(?:a|the)\s+)?background"
        r"(?:\s+(?:task|job))?[.!?]*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = text.strip(" \t\r\n,;:-")
    if not text:
        return "Complete the delegated background task described by the user's request."
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _delegation_title(instruction: str, agent_id: str) -> str:
    title = " ".join(instruction.strip().split()).strip(" .,:;-")
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
    text = " ".join((message or "").strip().split())
    if not text:
        return None
    lowered = text.casefold()
    if re.search(
        r"^\s*(?:what|when|where|why|how|did|has|have|is|are|was|were|show|list|check|cancel|stop|abort)\b",
        lowered,
    ) and re.search(
        r"\b(?:agent|background task|background job|result|output|findings?|status)\b",
        lowered,
    ):
        return None

    named_agent = _named_agent(lowered) is not None
    explicit_background = bool(
        re.search(
            r"\b(?:in the background|background task|background job|"
            r"while (?:we|you|i) (?:continue|carry on|keep working|talk)|"
            r"without blocking (?:the )?(?:chat|conversation)|"
            r"keep (?:this|the )?(?:chat|conversation) free)\b",
            lowered,
        )
    )
    delegation_verb = bool(
        re.search(
            r"\b(?:delegate|delegat(?:e|ing)|"
            r"have (?:the )?(?:research|researcher|code|coding|developer|software|file|files|filesystem|analyst|analysis|general) agent|"
            r"ask (?:the )?(?:research|researcher|code|coding|developer|software|file|files|filesystem|analyst|analysis|general) agent|"
            r"send (?:this|that|it|the task|the job) to (?:the )?.+? agent|"
            r"use (?:the )?.+? agent (?:to|for)|get (?:the )?.+? agent to|"
            r"run (?:this|that|it) (?:with|through) (?:the )?.+? agent)\b",
            lowered,
        )
    )
    if not delegation_verb and not explicit_background:
        return None
    if not named_agent and explicit_background:
        work_verb = bool(
            re.search(
                r"\b(?:research|investigate|analyse|analyze|compare|inspect|review|check|"
                r"look into|find out|work on|fix|debug|build|write|organise|organize|"
                r"process|calculate|summari[sz]e|explain)\b",
                lowered,
            )
        )
        if not work_verb:
            return None
    agent_id = _choose_agent(lowered)
    instruction = _clean_delegated_instruction(text)
    return ExplicitDelegationPlan(
        agent_id=agent_id,
        title=_delegation_title(instruction, agent_id),
        instruction=instruction,
    )


def parse_director_request(message: str) -> DirectorDelegationPlan | None:
    """
    Detect an open-ended autonomous objective where Jace should choose and
    coordinate the specialists instead of requiring the user to name one.

    Explicitly named worker requests remain single-agent delegations.
    """
    text = " ".join((message or "").strip().split())
    if not text:
        return None
    lowered = text.casefold()

    if _named_agent(lowered) is not None:
        return None
    if parse_agent_result_followup(text) is not None:
        return None
    if re.search(r"\b(?:cancel|stop|abort)\b.{0,35}\b(?:agent|background|task|job)\b", lowered):
        return None

    explicit_director = bool(
        re.search(
            r"\b(?:agent director|director agent|use (?:the )?director|"
            r"use whatever agents?|choose (?:the )?(?:best|right) agents?|"
            r"decide which agents?|coordinate (?:the )?agents?|orchestrate (?:the )?agents?|"
            r"use (?:the )?(?:agent )?team|have (?:the )?agents work together)\b",
            lowered,
        )
    )
    investigate = bool(
        re.search(
            r"\b(?:investigate|diagnose|debug|audit|review|research|look into|"
            r"figure out|work out|find (?:the )?(?:problem|issue|cause)|assess)\b",
            lowered,
        )
    )
    follow_through = bool(
        re.search(
            r"\b(?:fix|resolve|repair|implement|change|update|correct|address|handle|"
            r"act on|do whatever|whatever you find|then (?:fix|implement|change|update|"
            r"resolve|handle)|and (?:fix|implement|change|update|resolve|handle))\b",
            lowered,
        )
    )
    broad_autonomy = bool(
        re.search(
            r"\b(?:take care of (?:this|it)|handle (?:this|it) end[- ]to[- ]end|"
            r"work through (?:this|it)|sort (?:this|it) out|do what(?:ever)? is needed)\b",
            lowered,
        )
    )

    if not (explicit_director or broad_autonomy or (investigate and follow_through)):
        return None

    objective = re.sub(r"^(?:hey\s+)?jace[\s,:;-]*", "", text, flags=re.IGNORECASE).strip()
    objective = objective or text
    title = _delegation_title(objective, "general")
    return DirectorDelegationPlan(objective=objective, title=title)


def parse_agent_result_followup(message: str) -> AgentResultPlan | None:
    text = " ".join((message or "").strip().split())
    if not text:
        return None
    lowered = text.casefold()
    named = _named_agent(lowered)
    generic = bool(
        re.search(
            r"\b(?:what did (?:the )?agent (?:find|do|return|say|produce|come back with)|"
            r"what has (?:the )?agent (?:found|done|returned|produced)|"
            r"what(?:'s| is) (?:the )?agent(?:'s)? (?:result|output|answer|finding|findings|report)|"
            r"show me (?:the )?agent(?:'s)? (?:result|output|findings|report)|"
            r"give me (?:the )?agent(?:'s)? (?:result|output|findings|report)|"
            r"did (?:the )?agent finish|has (?:the )?agent finished|is (?:the )?agent finished|"
            r"what came back from (?:the )?agent|"
            r"what did (?:the )?background (?:task|job|agent) (?:find|return|produce|say)|"
            r"background (?:task|job|agent) (?:result|output|status|report))\b",
            lowered,
        )
    )
    named_followup = bool(
        named
        and re.search(
            r"\b(?:what did .* agent (?:find|do|return|say|produce)|"
            r"what has .* agent (?:found|done|returned|produced)|"
            r"what(?:'s| is) .* agent(?:'s)? (?:result|output|report|status)|"
            r"did .* agent finish|has .* agent finished|is .* agent finished|"
            r"show .* agent(?:'s)? (?:result|output|report)|check .* agent)\b",
            lowered,
        )
    )
    pronoun = bool(
        re.fullmatch(
            r"(?:what did it (?:find|return|say|produce|come back with)|"
            r"what has it (?:found|returned|done|produced)|what came back|"
            r"what did they (?:find|return|say|produce)|what(?:'s| is) the result|"
            r"what(?:'s| is) the output|and the result|and the output|any result|any update)[?.!]*",
            lowered,
        )
    )
    if not (generic or named_followup or pronoun):
        return None
    return AgentResultPlan(agent_id=named)


def build_forced_director_call(
    message: str,
    *,
    reasoning_mode: str,
    available_tool_names: list[str] | set[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    if "delegate_agent_director" not in set(available_tool_names):
        return None
    plan = parse_director_request(message)
    if plan is None:
        return None
    return {
        "type": "function",
        "function": {
            "name": "delegate_agent_director",
            "arguments": {
                "objective": plan.objective,
                "reasoning_mode": (
                    reasoning_mode if reasoning_mode in {"fast", "balanced", "deep"} else "balanced"
                ),
            },
        },
    }


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
                    reasoning_mode if reasoning_mode in {"fast", "balanced", "deep"} else "balanced"
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
        "function": {"name": "get_latest_agent_result", "arguments": arguments},
    }


def extend_agent_tool_route(
    base_router: Callable[[str], set[str]],
) -> Callable[[str], set[str]]:
    def route(message: str) -> set[str]:
        selected = set(base_router(message))
        text = " ".join((message or "").strip().split())
        lowered = text.casefold()
        if not text:
            return selected
        if re.search(r"\b(?:use|show|list)\s+all\s+tools\b", lowered):
            selected.update(AGENT_TOOL_NAMES)
            return selected
        if parse_director_request(text) is not None:
            selected.add("delegate_agent_director")
        if parse_explicit_delegation(text) is not None:
            selected.add("delegate_agent_task")
        if parse_agent_result_followup(text) is not None:
            selected.add("get_latest_agent_result")
        if re.search(
            r"\b(?:what (?:are|is) (?:the )?agents? doing|"
            r"what(?:'s| is) (?:the )?(?:agent|background) status|"
            r"agent (?:tasks?|jobs?|status)|background (?:tasks?|jobs?|status)|"
            r"show (?:me )?(?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"list (?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"which agents? (?:are )?(?:working|running|busy)|"
            r"finished background|completed background)\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "check_agent_task", "get_latest_agent_result"})
        if re.search(
            r"\b(?:cancel|stop|abort)\b.{0,35}\b(?:agent|background|task|job)\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "cancel_agent_task"})
        return selected

    return route
