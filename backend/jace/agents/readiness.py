from __future__ import annotations

# JACE_AGENT_READINESS_PHASE_1E

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jace.agents.config import agent_settings
from jace.agents.definitions import AgentDefinition, get_agent_definition, list_agent_definitions
from jace.ai.engine import get_models
from jace.computer.service import list_workspaces
from jace.database import SessionLocal
from jace.db.settings import get_or_create_assistant_settings
from jace.tools import ensure_tools_registered
from jace.tools.permissions import permission_map
from jace.tools.registry import registry

READINESS_TIMEOUT_SECONDS = 3.5


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_model_name(value: str) -> str:
    name = (value or "").strip().casefold()
    if name.endswith(":latest"):
        name = name[:-7]
    return name


def _model_is_available(model: str, installed_models: list[str]) -> bool:
    target = _normalise_model_name(model)
    return bool(target) and any(_normalise_model_name(item) == target for item in installed_models)


def _issue(code: str, severity: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
    }


def _tool_state(
    *,
    tool_name: str,
    kind: str,
    permissions: dict[str, str],
) -> dict[str, Any]:
    definition = registry.get(tool_name)
    if definition is None:
        return {
            "name": tool_name,
            "label": tool_name,
            "category": "unknown",
            "risk": "unknown",
            "kind": kind,
            "registered": False,
            "permission": "missing",
            "available": False,
            "requires_approval": False,
        }

    permission = permissions.get(tool_name, definition.default_permission)
    available = permission in {"allow", "ask"}
    return {
        "name": tool_name,
        "label": definition.label,
        "category": definition.category,
        "risk": definition.risk,
        "kind": kind,
        "registered": True,
        "permission": permission,
        "available": available,
        "requires_approval": permission == "ask",
    }


def _status_from_issues(issues: list[dict[str, str]]) -> str:
    severities = {item["severity"] for item in issues}
    if "error" in severities:
        return "unavailable"
    if "warning" in severities:
        return "degraded"
    return "ready"


def _summary(status: str, issues: list[dict[str, str]]) -> str:
    if status == "ready":
        return "Ready for work. Required runtime capabilities are available."

    relevant = [
        item["message"]
        for item in issues
        if item["severity"] in ({"error"} if status == "unavailable" else {"warning"})
    ]
    if relevant:
        return relevant[0]
    return "This specialist has limited runtime capability."


def _workspace_exists(root_path: str) -> bool:
    try:
        return Path(root_path).expanduser().is_dir()
    except (OSError, RuntimeError, ValueError):
        return False


def _agent_snapshot(
    definition: AgentDefinition,
    *,
    selected_model: str,
    installed_models: list[str],
    ollama_connected: bool,
    manager_running: bool,
    permissions: dict[str, str],
    readable_workspaces: list[dict[str, str]],
    writable_workspaces: list[dict[str, str]],
    workspace_error: str | None,
) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_name in definition.default_tools:
        tools.append(
            _tool_state(
                tool_name=tool_name,
                kind="default",
                permissions=permissions,
            )
        )
        seen.add(tool_name)
    for tool_name in definition.optional_tools:
        if tool_name in seen:
            continue
        tools.append(
            _tool_state(
                tool_name=tool_name,
                kind="optional",
                permissions=permissions,
            )
        )
        seen.add(tool_name)

    issues: list[dict[str, str]] = []

    if not agent_settings.enabled:
        issues.append(
            _issue(
                "agent_system_disabled",
                "error",
                "Background agents are disabled in Jace configuration.",
            )
        )
    if not manager_running:
        issues.append(
            _issue(
                "manager_offline",
                "error",
                "The background-agent manager is not running.",
            )
        )
    if not ollama_connected:
        issues.append(
            _issue(
                "ollama_offline",
                "error",
                "Ollama is unavailable, so this specialist cannot reason or execute work.",
            )
        )

    model_available = ollama_connected and _model_is_available(selected_model, installed_models)
    if ollama_connected and not model_available:
        issues.append(
            _issue(
                "model_unavailable",
                "error",
                f'The selected model "{selected_model}" is not installed in Ollama.',
            )
        )

    unavailable_default_tools = [
        tool
        for tool in tools
        if tool["kind"] == "default" and not tool["available"]
    ]
    available_default_tools = [
        tool
        for tool in tools
        if tool["kind"] == "default" and tool["available"]
    ]
    if unavailable_default_tools:
        names = ", ".join(tool["name"] for tool in unavailable_default_tools)
        severity = "error" if not available_default_tools else "warning"
        issues.append(
            _issue(
                "default_tools_unavailable",
                severity,
                f"Required/default tools unavailable: {names}.",
            )
        )

    if workspace_error and definition.id in {"code", "files"}:
        issues.append(
            _issue(
                "workspace_check_failed",
                "warning" if definition.id == "code" else "error",
                f"Jace could not verify approved workspaces: {workspace_error}",
            )
        )

    readable_count = len(readable_workspaces)
    writable_count = len(writable_workspaces)
    if definition.id == "code" and readable_count == 0:
        issues.append(
            _issue(
                "no_readable_workspace",
                "warning",
                "No active readable workspace is approved. Code can still plan or reason, but cannot inspect project files.",
            )
        )
    elif definition.id == "files" and readable_count == 0:
        issues.append(
            _issue(
                "no_readable_workspace",
                "error",
                "No active readable workspace is approved, so the File Agent has nothing it is allowed to inspect.",
            )
        )

    if definition.id in {"code", "files"} and writable_count == 0:
        issues.append(
            _issue(
                "no_writable_workspace",
                "info",
                "No active writable workspace is approved. Read-only work remains available, but file changes cannot be completed.",
            )
        )

    # Research without either of its two evidence-gathering tools is not a useful
    # research specialist even though clock/calculator defaults may still exist.
    if definition.id == "research":
        core = {
            tool["name"]: tool
            for tool in tools
            if tool["name"] in {"web_search", "read_web_page"}
        }
        if core and not any(tool["available"] for tool in core.values()):
            issues.append(
                _issue(
                    "research_web_tools_unavailable",
                    "error",
                    "Both core web-research tools are unavailable.",
                )
            )

    status = _status_from_issues(issues)
    return {
        "agent_id": definition.id,
        "agent_name": definition.name,
        "status": status,
        "summary": _summary(status, issues),
        "model": selected_model,
        "model_available": model_available,
        "readable_workspace_count": readable_count,
        "writable_workspace_count": writable_count,
        "issues": issues,
        "tools": tools,
    }


async def build_agent_readiness_snapshot(
    *,
    manager_running: bool,
    model_overrides: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return authoritative runtime capability state for every specialist."""

    ensure_tools_registered()
    model_overrides = model_overrides or {}

    installed_models: list[str] = []
    ollama_connected = False
    ollama_error: str | None = None
    try:
        models = await asyncio.wait_for(get_models(), timeout=READINESS_TIMEOUT_SECONDS)
        installed_models = [model.name for model in models if model.name]
        ollama_connected = True
    except asyncio.TimeoutError:
        ollama_error = (
            f"Ollama model discovery exceeded {READINESS_TIMEOUT_SECONDS:.1f}s."
        )
    except Exception as exc:  # readiness must report health, not fail the endpoint
        ollama_error = str(exc) or exc.__class__.__name__

    permissions: dict[str, str] = {}
    default_model = ""
    readable_workspaces: list[dict[str, str]] = []
    writable_workspaces: list[dict[str, str]] = []
    workspace_error: str | None = None

    async with SessionLocal() as session:
        profile = await get_or_create_assistant_settings(session)
        default_model = profile.default_model
        permissions = await permission_map(session)
        try:
            workspaces = await list_workspaces(session, active_only=True)
            for workspace in workspaces:
                if not _workspace_exists(workspace.root_path):
                    continue
                item = {
                    "id": workspace.id,
                    "label": workspace.label,
                    "root_path": workspace.root_path,
                }
                if workspace.read_enabled:
                    readable_workspaces.append(item)
                if workspace.write_enabled:
                    writable_workspaces.append(item)
        except Exception as exc:  # surfaced as specialist readiness rather than 500
            workspace_error = str(exc) or exc.__class__.__name__

    agents = []
    for definition in list_agent_definitions():
        selected_model = (model_overrides.get(definition.id) or default_model).strip()
        agents.append(
            _agent_snapshot(
                definition,
                selected_model=selected_model,
                installed_models=installed_models,
                ollama_connected=ollama_connected,
                manager_running=manager_running,
                permissions=permissions,
                readable_workspaces=readable_workspaces,
                writable_workspaces=writable_workspaces,
                workspace_error=workspace_error,
            )
        )

    return {
        "generated_at": _utc_iso(),
        "manager_running": manager_running,
        "agent_system_enabled": agent_settings.enabled,
        "ollama_connected": ollama_connected,
        "ollama_error": ollama_error,
        "default_model": default_model,
        "installed_models": installed_models,
        "readable_workspaces": readable_workspaces,
        "writable_workspaces": writable_workspaces,
        "agents": agents,
    }


async def get_agent_readiness(
    agent_id: str,
    *,
    manager_running: bool,
    model_override: str | None = None,
) -> dict[str, Any]:
    if get_agent_definition(agent_id) is None:
        raise ValueError(f"Unknown agent: {agent_id}")

    snapshot = await build_agent_readiness_snapshot(
        manager_running=manager_running,
        model_overrides={agent_id: model_override},
    )
    for item in snapshot["agents"]:
        if item["agent_id"] == agent_id:
            return item
    raise ValueError(f"Unknown agent: {agent_id}")
