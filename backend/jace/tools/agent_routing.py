from __future__ import annotations

import re
from collections.abc import Callable


AGENT_TOOL_NAMES = {
    "delegate_agent_task",
    "check_agent_task",
    "list_agent_tasks",
    "cancel_agent_task",
}


def extend_agent_tool_route(
    base_router: Callable[[str], set[str]],
) -> Callable[[str], set[str]]:
    """
    Wrap Jace's existing smart tool router without replacing the mature Phase
    5-10 routing rules.

    tools.agent imports route_tool_names into its module namespace. Phase 11B
    installs this wrapper there once during tool registration.
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

        explicit_agent = bool(
            re.search(
                r"\b(?:"
                r"background agent|background task|delegate|delegat(?:e|ion)|"
                r"research agent|code agent|coding agent|file agent|files agent|"
                r"analyst agent|general agent|sub[- ]?agent|specialist agent|"
                r"send (?:this|that|it) to (?:the )?(?:research|code|coding|files?|analyst|general) agent|"
                r"have (?:the )?(?:research|code|coding|files?|analyst|general) agent|"
                r"ask (?:the )?(?:research|code|coding|files?|analyst|general) agent|"
                r"in the background|while (?:we|you|i) (?:continue|carry on)|"
                r"work on .* in the background"
                r")\b",
                lowered,
            )
        )

        if explicit_agent:
            selected.add("delegate_agent_task")

        if re.search(
            r"\b(?:"
            r"what (?:are|is) (?:the )?agents? doing|"
            r"agent (?:tasks?|jobs?|status)|"
            r"background (?:tasks?|jobs?|status)|"
            r"show (?:me )?(?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"list (?:the )?(?:agent|background) (?:tasks?|jobs?)|"
            r"which agents? (?:are )?(?:working|running|busy)|"
            r"finished background|completed background"
            r")\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "check_agent_task"})

        if re.search(
            r"\b(?:"
            r"check (?:on )?(?:the )?(?:agent|background) (?:task|job)|"
            r"what did (?:the )?(?:research|code|coding|file|files|analyst|general) agent (?:find|do|return)|"
            r"agent result|background result|is .* agent .* finished"
            r")\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "check_agent_task"})

        if re.search(
            r"\b(?:cancel|stop|abort)\b.{0,30}\b(?:agent|background)\b",
            lowered,
        ):
            selected.update({"list_agent_tasks", "cancel_agent_task"})

        return selected

    return route
