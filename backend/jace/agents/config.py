from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class AgentOrchestrationSettings:
    """
    Phase 11A settings are kept in their own namespace so this upgrade does not
    require replacing Jace's already-large global config.py.

    They can still be overridden through environment variables.
    """

    enabled: bool = _env_bool("JACE_AGENT_ENABLED", True)
    max_parallel_tasks: int = _env_int("JACE_AGENT_MAX_PARALLEL", 2, 1, 8)
    max_tool_steps: int = _env_int("JACE_AGENT_MAX_TOOL_STEPS", 7, 1, 20)
    task_timeout_seconds: int = _env_int("JACE_AGENT_TIMEOUT_SECONDS", 900, 30, 3600)
    conversation_context_messages: int = _env_int(
        "JACE_AGENT_CONTEXT_MESSAGES", 10, 0, 30
    )
    result_max_chars: int = _env_int(
        "JACE_AGENT_RESULT_MAX_CHARS", 30_000, 2_000, 100_000
    )
    event_history_limit: int = _env_int(
        "JACE_AGENT_EVENT_HISTORY_LIMIT", 400, 50, 2_000
    )


agent_settings = AgentOrchestrationSettings()
