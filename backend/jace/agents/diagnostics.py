from __future__ import annotations
# JACE_AGENT_DIAGNOSTICS_PHASE_1F

from datetime import datetime, timezone
from typing import Any

from jace.agents.definitions import get_agent_definition, list_agent_definitions
from jace.agents.models import AgentTask
from jace.agents.service import create_task, event_data, list_events, list_tasks, task_metadata
from jace.database import SessionLocal

DIAGNOSTIC_VERSION = 1
DIAGNOSTIC_ACTIVE_STATUSES = {
    "queued",
    "running",
    "thinking",
    "using_tool",
    "waiting_permission",
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _tool_available(readiness: dict[str, Any], tool_name: str) -> bool:
    for tool in readiness.get("tools") or []:
        if tool.get("name") == tool_name:
            return bool(tool.get("available"))
    return False


def _diagnostic_spec(agent_id: str, readiness: dict[str, Any]) -> dict[str, Any]:
    """Return one non-destructive end-to-end self-test for a specialist."""
    if readiness.get("status") == "unavailable":
        return {
            "testable": False,
            "blocked_reason": readiness.get("summary") or "Specialist is unavailable.",
        }

    if agent_id == "research":
        if _tool_available(readiness, "web_search"):
            return {
                "testable": True,
                "label": "Public web research",
                "tools": ["web_search"],
                "required_all": ["web_search"],
                "instruction": (
                    "Jace specialist self-test. This is a non-destructive diagnostic. "
                    "You MUST call web_search once for: Python programming language official website. "
                    "After the tool returns, report the title and URL of one relevant result. "
                    "Do not invent a result and do not use any capability other than the supplied tool."
                ),
            }
        if _tool_available(readiness, "read_web_page"):
            return {
                "testable": True,
                "label": "Public web page read",
                "tools": ["read_web_page"],
                "required_all": ["read_web_page"],
                "instruction": (
                    "Jace specialist self-test. This is a non-destructive diagnostic. "
                    "You MUST call read_web_page once for https://www.python.org/ and then report the page title "
                    "or a short verified fact from the returned page. Do not invent page content."
                ),
            }
        return {
            "testable": False,
            "blocked_reason": "Neither web_search nor read_web_page is currently available for a safe Research test.",
        }

    if agent_id in {"code", "files"}:
        if int(readiness.get("readable_workspace_count") or 0) <= 0:
            return {
                "testable": False,
                "blocked_reason": "A readable approved workspace is required for the end-to-end workspace self-test.",
            }
        required = ["list_computer_workspaces", "list_workspace_files"]
        missing = [name for name in required if not _tool_available(readiness, name)]
        if missing:
            return {
                "testable": False,
                "blocked_reason": "Safe workspace diagnostic tools are unavailable: " + ", ".join(missing) + ".",
            }
        noun = "Code" if agent_id == "code" else "File"
        return {
            "testable": True,
            "label": "Approved workspace read",
            "tools": required,
            "required_all": required,
            "instruction": (
                f"Jace {noun} Agent self-test. This test MUST remain read-only. "
                "First call list_computer_workspaces. Select one active readable workspace returned by that tool. "
                "Then call list_workspace_files for that workspace at its root. "
                "Report the workspace label and one real entry from the listing. "
                "Do not write, move, delete, create, replace, or execute anything."
            ),
        }

    if agent_id == "analyst":
        if not _tool_available(readiness, "calculator"):
            return {
                "testable": False,
                "blocked_reason": "calculator is unavailable, so the deterministic Analyst self-test cannot run.",
            }
        return {
            "testable": True,
            "label": "Deterministic calculation",
            "tools": ["calculator"],
            "required_all": ["calculator"],
            "instruction": (
                "Jace Analyst Agent self-test. You MUST call calculator to evaluate 17 * 19. "
                "Verify the tool result and report it. Do not calculate silently without the tool."
            ),
        }

    if agent_id == "general":
        if _tool_available(readiness, "current_datetime"):
            selected = "current_datetime"
            instruction = (
                "Jace General Agent self-test. You MUST call current_datetime exactly once, then report the date/time "
                "returned by the tool. Do not guess the current time."
            )
        elif _tool_available(readiness, "calculator"):
            selected = "calculator"
            instruction = (
                "Jace General Agent self-test. You MUST call calculator to evaluate 41 + 1, then report the returned result."
            )
        else:
            return {
                "testable": False,
                "blocked_reason": "No harmless runtime tool is available for the General Agent self-test.",
            }
        return {
            "testable": True,
            "label": "General tool execution",
            "tools": [selected],
            "required_all": [selected],
            "instruction": instruction,
        }

    return {
        "testable": False,
        "blocked_reason": f"No self-test is defined for specialist {agent_id!r}.",
    }


def _is_diagnostic(task: AgentTask) -> bool:
    return task_metadata(task).get("agent_self_test") is True


def _duration_ms(task: AgentTask) -> int | None:
    start = task.started_at or task.created_at
    end = task.completed_at
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _task_snapshot(
    task: AgentTask | None,
    readiness: dict[str, Any],
    *,
    successful_tools: list[str] | None = None,
) -> dict[str, Any]:
    agent_id = str(readiness.get("agent_id") or "")
    spec = _diagnostic_spec(agent_id, readiness)
    base: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_name": readiness.get("agent_name") or agent_id,
        "testable": bool(spec.get("testable")),
        "blocked_reason": spec.get("blocked_reason"),
        "test_label": spec.get("label"),
        "status": "untested",
        "summary": "No end-to-end specialist self-test has been run yet.",
        "task_id": None,
        "task_status": None,
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "expected_tools": list(spec.get("required_all") or []),
        "used_tools": [],
        "result_preview": None,
        "error": None,
        "diagnostic_version": DIAGNOSTIC_VERSION,
    }
    if task is None:
        if not base["testable"]:
            base["status"] = "blocked"
            base["summary"] = base["blocked_reason"] or "This self-test is currently blocked."
        return base

    metadata = task_metadata(task)
    used_tools = list(dict.fromkeys(successful_tools or []))
    expected_tools = [
        str(name)
        for name in metadata.get("diagnostic_required_tools_all", [])
        if isinstance(name, str)
    ]
    base.update(
        {
            "task_id": task.id,
            "task_status": task.status,
            "created_at": _iso(task.created_at),
            "started_at": _iso(task.started_at),
            "completed_at": _iso(task.completed_at),
            "duration_ms": _duration_ms(task),
            "expected_tools": expected_tools or base["expected_tools"],
            "used_tools": used_tools,
            "result_preview": (task.result or "")[:800] or None,
            "error": task.error,
            "diagnostic_version": metadata.get("diagnostic_version", DIAGNOSTIC_VERSION),
            "test_label": metadata.get("diagnostic_label") or base["test_label"],
        }
    )

    if task.status in DIAGNOSTIC_ACTIVE_STATUSES:
        base["status"] = "running"
        base["summary"] = task.progress_message or "Self-test is running through the real agent executor."
        return base

    if task.status == "completed":
        missing = [name for name in base["expected_tools"] if name not in used_tools]
        if missing:
            base["status"] = "failed"
            base["summary"] = (
                "The task completed, but it did not prove the required capability. "
                "Missing successful tool evidence: " + ", ".join(missing) + "."
            )
        elif not (task.result or "").strip():
            base["status"] = "failed"
            base["summary"] = "The self-test completed without a usable handoff result."
        else:
            base["status"] = "passed"
            base["summary"] = "End-to-end test passed through the real model, executor and required tool path."
        return base

    base["status"] = "failed"
    if task.status == "cancelled":
        base["summary"] = "The specialist self-test was cancelled before it completed."
    else:
        base["summary"] = task.error or "The specialist self-test failed."
    return base


async def _latest_diagnostic_tasks() -> tuple[dict[str, AgentTask], dict[str, list[str]]]:
    latest: dict[str, AgentTask] = {}
    successful_tools_by_task: dict[str, list[str]] = {}
    async with SessionLocal() as session:
        rows = await list_tasks(session, limit=500)
        for task in rows:
            if task.agent_id in latest or not _is_diagnostic(task):
                continue
            latest[task.agent_id] = task
            events = await list_events(session, task.id, limit=500)
            successful_tools: list[str] = []
            for event in events:
                if event.event_type != "tool_completed":
                    continue
                data = event_data(event)
                if data.get("success") is not True:
                    continue
                tool_name = str(data.get("tool_name") or "").strip()
                if tool_name and tool_name not in successful_tools:
                    successful_tools.append(tool_name)
            successful_tools_by_task[task.id] = successful_tools
    return latest, successful_tools_by_task


async def build_agent_diagnostics_snapshot(
    *,
    readiness_snapshot: dict[str, Any],
) -> dict[str, Any]:
    latest, successful_tools_by_task = await _latest_diagnostic_tasks()
    readiness_by_agent = {
        str(item.get("agent_id")): item
        for item in readiness_snapshot.get("agents") or []
        if isinstance(item, dict)
    }
    agents: list[dict[str, Any]] = []
    for definition in list_agent_definitions():
        readiness = readiness_by_agent.get(definition.id) or {
            "agent_id": definition.id,
            "agent_name": definition.name,
            "status": "unavailable",
            "summary": "Readiness information is unavailable.",
            "tools": [],
            "readable_workspace_count": 0,
        }
        latest_task = latest.get(definition.id)
        agents.append(
            _task_snapshot(
                latest_task,
                readiness,
                successful_tools=(successful_tools_by_task.get(latest_task.id, []) if latest_task else []),
            )
        )
    counts = {"untested": 0, "blocked": 0, "running": 0, "passed": 0, "failed": 0}
    for item in agents:
        status = str(item.get("status") or "untested")
        if status in counts:
            counts[status] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "agents": agents,
    }


async def find_active_agent_diagnostic(agent_id: str) -> AgentTask | None:
    async with SessionLocal() as session:
        rows = await list_tasks(session, agent_id=agent_id, limit=50)
    for task in rows:
        if _is_diagnostic(task) and task.status in DIAGNOSTIC_ACTIVE_STATUSES:
            return task
    return None


async def create_agent_diagnostic_task(
    *,
    agent_id: str,
    readiness: dict[str, Any],
) -> tuple[AgentTask | None, str | None, bool]:
    definition = get_agent_definition(agent_id)
    if definition is None:
        raise ValueError(f"Unknown agent: {agent_id}")

    existing = await find_active_agent_diagnostic(agent_id)
    if existing is not None:
        return existing, None, True

    spec = _diagnostic_spec(agent_id, readiness)
    if not spec.get("testable"):
        return None, str(spec.get("blocked_reason") or "Self-test is currently blocked."), False

    metadata = {
        "source": "agent_diagnostics",
        "agent_self_test": True,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "diagnostic_label": spec.get("label"),
        "diagnostic_required_tools_all": list(spec.get("required_all") or []),
        "suppress_chat_handoff": True,
        "suppress_memory_extraction": True,
    }
    async with SessionLocal() as session:
        task = await create_task(
            session,
            agent_id=agent_id,
            title=f"Self-test: {definition.name}",
            instruction=str(spec["instruction"]),
            priority=-5,
            model=str(readiness.get("model") or "").strip() or None,
            reasoning_mode="fast",
            allowed_tools=list(spec.get("tools") or []),
            metadata=metadata,
        )
    return task, None, False
