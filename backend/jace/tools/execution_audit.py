from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from jace.db.models import ExecutionScope


_AGENT_MUTATION_TOOLS = {
    "run_device_command",
    "stop_device_process",
    "open_device_terminal",
    "send_device_terminal_input",
    "close_device_terminal",
}

_DIRECT_UI_TOOLS = {
    "ui_run_device_command",
    "ui_stop_device_process",
    "ui_open_device_terminal",
    "ui_close_device_terminal",
}

_COMMAND_TOOLS = {
    "run_device_command",
    "inspect_device_command",
    "ui_run_device_command",
}

_TERMINAL_INPUT_TOOLS = {
    "send_device_terminal_input",
}


def _string(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def _command_hash(
    command: str,
) -> str:
    return hashlib.sha256(
        command.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def redact_execution_sensitive(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    safe = dict(arguments)

    if (
        tool_name in _COMMAND_TOOLS
        or tool_name == "run_shell_command"
    ):
        command = safe.get("command")

        if isinstance(command, str):
            safe["command"] = {
                "redacted": True,
                "length": len(command),
                "sha256": _command_hash(command),
            }

    if tool_name in _TERMINAL_INPUT_TOOLS:
        data = safe.get("data")

        if isinstance(data, str):
            safe["data"] = (
                "<redacted terminal input: "
                f"{len(data)} characters>"
            )

    return safe


def _classification(
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[str | None, bool | None]:
    if tool_name in {
        "run_device_command",
        "inspect_device_command",
    }:
        try:
            from jace.tools.execution_bridge import (
                command_policy,
                command_session_grant_key,
            )

            decision = command_policy(
                arguments
            )

            grantable = (
                command_session_grant_key(
                    arguments
                )
                is not None
            )

            return (
                str(
                    decision.classification
                ),
                grantable,
            )
        except Exception:
            return (
                "command",
                None,
            )

    mapping = {
        "stop_device_process": (
            "process_termination",
            False,
        ),
        "open_device_terminal": (
            "terminal_open",
            True,
        ),
        "send_device_terminal_input": (
            "terminal_input",
            False,
        ),
        "resize_device_terminal": (
            "terminal_resize",
            False,
        ),
        "close_device_terminal": (
            "terminal_close",
            False,
        ),
        "ui_run_device_command": (
            "explicit_process_launch",
            False,
        ),
        "ui_stop_device_process": (
            "explicit_process_termination",
            False,
        ),
        "ui_open_device_terminal": (
            "explicit_terminal_open",
            False,
        ),
        "ui_close_device_terminal": (
            "explicit_terminal_close",
            False,
        ),
    }

    return mapping.get(
        tool_name,
        (
            None,
            None,
        ),
    )


def _dynamic_floor(
    tool_name: str,
) -> str | None:
    if tool_name in _AGENT_MUTATION_TOOLS:
        return "ask"

    if tool_name in _DIRECT_UI_TOOLS:
        return "explicit_user_action"

    return None


async def execution_policy_context(
    session: AsyncSession,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    configured_permission: str | None,
    effective_permission: str,
    session_grant_used: bool | None,
    session_grant_available: bool | None,
) -> dict[str, Any] | None:
    if (
        tool_name not in _AGENT_MUTATION_TOOLS
        and tool_name not in _DIRECT_UI_TOOLS
        and tool_name not in {
            "inspect_device_command",
            "resize_device_terminal",
        }
    ):
        return None

    classification, grantable = _classification(
        tool_name,
        arguments,
    )

    scope_id = _string(
        arguments.get("scope_id")
    )

    scope: ExecutionScope | None = None

    if scope_id:
        try:
            scope = await session.get(
                ExecutionScope,
                scope_id,
            )
        except Exception:
            scope = None

    context: dict[str, Any] = {
        "version": 1,
        "configured_permission": (
            configured_permission
        ),
        "dynamic_floor": _dynamic_floor(
            tool_name
        ),
        "effective_permission": (
            effective_permission
        ),
        "classification": classification,
        "session_grant_used": (
            session_grant_used
        ),
        "session_grant_available": (
            session_grant_available
        ),
        "grantable": grantable,
        "scope_id": scope_id,
        "scope_label": (
            scope.label
            if scope is not None
            else None
        ),
        "device_id": (
            scope.device_id
            if scope is not None
            else None
        ),
        "workspace_id": (
            scope.workspace_id
            if scope is not None
            else None
        ),
        "shell": _string(
            arguments.get("shell")
        ),
        "relative_cwd": _string(
            arguments.get("relative_cwd")
        ) or ".",
        "mode": _string(
            arguments.get("mode")
        ),
        "provenance": (
            "explicit_runtime_ui"
            if tool_name in _DIRECT_UI_TOOLS
            else "agent_tool"
        ),
    }

    if tool_name in _COMMAND_TOOLS:
        command = arguments.get(
            "command"
        )

        if isinstance(command, str):
            context[
                "command_sha256"
            ] = _command_hash(
                command
            )
            context[
                "command_length"
            ] = len(
                command
            )

    return context
