from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from jace.config import settings
from jace.db.models import Device
from jace.devices.connections import device_connections
from jace.devices.service import device_response
from jace.process_runtime import process_runtime
from jace.terminal_runtime import terminal_runtime
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
    ToolPolicyDecision,
)
from jace.tools.registry import registry


ShellName = Literal[
    "powershell",
    "cmd",
    "wsl",
    "bash",
]


def _require_local_execution_mode() -> None:
    # 4B.3C is deliberately fail-closed in server mode until authenticated
    # actor identity is threaded through ToolContext. Direct authenticated
    # process/terminal APIs continue to exist independently.
    if settings.mode == "server":
        raise ToolError(
            "Agent execution tools are temporarily disabled in server mode "
            "until authenticated actor identity is available in ToolContext."
        )


def _device_payload(
    device: Device,
    *,
    connected: bool,
) -> dict:
    response = device_response(
        device
    )

    capabilities = list(
        response.capabilities
    )

    return {
        "id": device.id,
        "name": device.name,
        "hostname": device.hostname,
        "platform": device.platform,
        "architecture": device.architecture,
        "connected": connected,
        "process_runtime": (
            "process.runtime"
            in capabilities
        ),
        "terminal_runtime": (
            "terminal.runtime"
            in capabilities
        ),
        "shells": sorted(
            capability.removeprefix(
                "terminal."
            )
            for capability
            in capabilities
            if capability
            in {
                "terminal.powershell",
                "terminal.cmd",
                "terminal.wsl",
                "terminal.bash",
            }
        ),
    }


async def _require_device_capability(
    context: ToolContext,
    *,
    device_id: str,
    capability: str,
) -> Device:
    result = await context.session.execute(
        select(Device).where(
            Device.id == device_id
        )
    )
    device = result.scalar_one_or_none()

    if device is None:
        raise ToolError(
            "The requested device does not exist."
        )

    if (
        not device.is_active
        or device.revoked_at is not None
    ):
        raise ToolError(
            "The requested device is revoked."
        )

    capabilities = set(
        device_response(
            device
        ).capabilities
    )

    if capability not in capabilities:
        raise ToolError(
            f"The requested device does not advertise {capability}."
        )

    if not await device_connections.is_connected(
        device_id
    ):
        raise ToolError(
            "The requested device is not currently connected."
        )

    return device


def _process_dict(
    row,
) -> dict:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "mode": row.mode,
        "shell": row.shell,
        "command_preview": row.command_preview,
        "cwd": row.cwd,
        "status": row.status,
        "pid": row.pid,
        "exit_code": row.exit_code,
        "timeout_seconds": row.timeout_seconds,
        "output_bytes": row.output_bytes,
        "output_truncated": bool(
            row.output_truncated
        ),
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "started_at": (
            row.started_at.isoformat()
            if row.started_at
            else None
        ),
        "completed_at": (
            row.completed_at.isoformat()
            if row.completed_at
            else None
        ),
    }


def _terminal_dict(
    row,
) -> dict:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "shell": row.shell,
        "cwd": row.cwd,
        "cols": row.cols,
        "rows": row.rows,
        "status": row.status,
        "pid": row.pid,
        "backend": row.backend,
        "exit_code": row.exit_code,
        "output_bytes": row.output_bytes,
        "output_truncated": bool(
            row.output_truncated
        ),
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "started_at": (
            row.started_at.isoformat()
            if row.started_at
            else None
        ),
        "completed_at": (
            row.completed_at.isoformat()
            if row.completed_at
            else None
        ),
    }


def _chunks_text(
    chunks,
    *,
    limit_chars: int = 12000,
) -> str:
    text = "".join(
        str(
            getattr(
                chunk,
                "text",
                "",
            )
            or ""
        )
        for chunk in chunks
    )

    if len(text) > limit_chars:
        text = (
            text[:limit_chars]
            + "\n<output truncated for tool result>"
        )

    return text


class ListExecutionDevicesInput(BaseModel):
    capability: Literal[
        "any",
        "process",
        "terminal",
    ] = "any"


class InspectDeviceCommandInput(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Exact device ID returned by list_execution_devices."
        ),
    )
    shell: ShellName
    command: str = Field(
        min_length=1,
        max_length=4000,
        description=(
            "A read-only inspection command. Chaining, redirection, "
            "mutation and elevation are rejected."
        ),
    )
    cwd: str | None = Field(
        default=None,
        max_length=2000,
    )
    timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=60,
    )


class RunDeviceCommandInput(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Exact device ID returned by list_execution_devices."
        ),
    )
    shell: ShellName
    command: str = Field(
        min_length=1,
        max_length=50000,
    )
    cwd: str | None = Field(
        default=None,
        max_length=2000,
    )
    mode: Literal[
        "foreground",
        "background",
    ] = "foreground"
    timeout_seconds: int | None = Field(
        default=120,
        ge=1,
        le=86400,
    )
    wait_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=120,
    )


class ProcessIdInput(BaseModel):
    process_id: str = Field(
        min_length=1,
        max_length=64,
    )


class ReadProcessOutputInput(
    ProcessIdInput
):
    after_sequence: int = Field(
        default=0,
        ge=0,
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=2000,
    )


class StopProcessInput(
    ProcessIdInput
):
    force: bool = False


class OpenTerminalInput(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=64,
    )
    shell: ShellName
    cwd: str | None = Field(
        default=None,
        max_length=2000,
    )
    cols: int = Field(
        default=120,
        ge=20,
        le=400,
    )
    rows: int = Field(
        default=30,
        ge=5,
        le=200,
    )


class TerminalIdInput(BaseModel):
    terminal_id: str = Field(
        min_length=1,
        max_length=64,
    )


class ReadTerminalOutputInput(
    TerminalIdInput
):
    after_sequence: int = Field(
        default=0,
        ge=0,
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=4000,
    )


class SendTerminalInputInput(
    TerminalIdInput
):
    data: str = Field(
        min_length=1,
        max_length=20000,
        description=(
            "Exact text/keystrokes to send to the live terminal."
        ),
    )


class ResizeTerminalInput(
    TerminalIdInput
):
    cols: int = Field(
        ge=20,
        le=400,
    )
    rows: int = Field(
        ge=5,
        le=200,
    )


class CloseTerminalInput(
    TerminalIdInput
):
    force: bool = False


_CHAINING_RE = re.compile(
    r"(?:&&|\|\||[|;<>])"
)

_POWERSHELL_READ_ONLY = (
    "get-location",
    "pwd",
    "get-childitem",
    "gci",
    "dir",
    "ls",
    "get-process",
    "gps",
    "get-service",
    "get-computerinfo",
    "get-ciminstance",
    "get-date",
    "get-command",
    "get-item",
    "get-childitem",
    "test-path",
    "resolve-path",
    "git status",
    "git diff",
    "git log",
    "git branch",
    "git rev-parse",
)

_CMD_READ_ONLY = (
    "cd",
    "dir",
    "where",
    "whoami",
    "tasklist",
    "sc query",
    "git status",
    "git diff",
    "git log",
    "git branch",
    "git rev-parse",
)

_POSIX_READ_ONLY = (
    "pwd",
    "ls",
    "find",
    "which",
    "whoami",
    "uname",
    "ps",
    "df",
    "du",
    "free",
    "git status",
    "git diff",
    "git log",
    "git branch",
    "git rev-parse",
)


def _normal_command(
    command: str,
) -> str:
    return " ".join(
        command.strip().split()
    ).casefold()


def validate_inspection_command(
    shell: str,
    command: str,
) -> None:
    normal = _normal_command(
        command
    )

    if not normal:
        raise ToolError(
            "Inspection command cannot be empty."
        )

    if _CHAINING_RE.search(
        command
    ):
        raise ToolError(
            "Read-only inspection commands cannot contain shell "
            "chaining, pipes or redirection."
        )

    if shell == "powershell":
        allowed = _POWERSHELL_READ_ONLY
    elif shell == "cmd":
        allowed = _CMD_READ_ONLY
    else:
        allowed = _POSIX_READ_ONLY

    if not any(
        normal == prefix
        or normal.startswith(
            prefix + " "
        )
        for prefix
        in allowed
    ):
        raise ToolError(
            "This command is not on Jace's conservative read-only "
            "inspection allowlist. Use run_device_command instead."
        )


_ELEVATED_PATTERNS = [
    re.compile(
        r"\bsudo\b",
        re.I,
    ),
    re.compile(
        r"\bsu\s+-",
        re.I,
    ),
    re.compile(
        r"\bstart-process\b.*\b-verb\s+runas\b",
        re.I,
    ),
    re.compile(
        r"\brunas(?:\.exe)?\b",
        re.I,
    ),
]

_DESTRUCTIVE_PATTERNS = [
    re.compile(
        r"\bremove-item\b",
        re.I,
    ),
    re.compile(
        r"\b(?:del|erase|rmdir|rd)\b",
        re.I,
    ),
    re.compile(
        r"(^|[\s;&|])rm\s+(?:-[a-z]*[rf][a-z]*\s+|--recursive\b|--force\b)",
        re.I,
    ),
    re.compile(
        r"\b(?:format-volume|clear-disk|initialize-disk|diskpart|mkfs(?:\.\w+)?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:shutdown|restart-computer|stop-computer|reboot|poweroff)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:reg\s+(?:add|delete)|set-itemproperty|new-itemproperty|remove-itemproperty)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:sc\s+(?:delete|config|stop)|stop-service|disable-service)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:net\s+user|net\s+localgroup|useradd|userdel|usermod)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:takeown|icacls|chmod|chown)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:kill|pkill|taskkill|stop-process)\b",
        re.I,
    ),
]


def command_policy(
    arguments: dict,
) -> ToolPolicyDecision:
    command = str(
        arguments.get("command")
        or ""
    )

    if any(
        pattern.search(
            command
        )
        for pattern
        in _ELEVATED_PATTERNS
    ):
        return ToolPolicyDecision(
            minimum_permission="ask",
            classification="elevated",
            risk="execute",
            reason=(
                "The command requests privilege elevation. "
                "Explicit approval is required."
            ),
        )

    if any(
        pattern.search(
            command
        )
        for pattern
        in _DESTRUCTIVE_PATTERNS
    ):
        return ToolPolicyDecision(
            minimum_permission="ask",
            classification="destructive",
            risk="execute",
            reason=(
                "The command may delete data, terminate processes or "
                "change system/security configuration. Explicit approval "
                "is required."
            ),
        )

    return ToolPolicyDecision(
        minimum_permission="allow",
        classification="standard_execute",
        risk="execute",
        reason=(
            "Ordinary command execution follows the configured tool "
            "permission."
        ),
    )


def always_ask_policy(
    classification: str,
    reason: str,
):
    def resolve(
        arguments: dict,
    ) -> ToolPolicyDecision:
        del arguments

        return ToolPolicyDecision(
            minimum_permission="ask",
            classification=classification,
            risk="execute",
            reason=reason,
        )

    return resolve


async def list_execution_devices_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        ListExecutionDevicesInput,
    )

    result = await context.session.execute(
        select(Device)
        .where(
            Device.is_active.is_(True),
            Device.revoked_at.is_(None),
        )
        .order_by(
            Device.name.asc()
        )
    )

    devices = []

    for device in result.scalars().all():
        connected = (
            await device_connections.is_connected(
                device.id
            )
        )

        item = _device_payload(
            device,
            connected=connected,
        )

        if (
            payload.capability == "process"
            and not item["process_runtime"]
        ):
            continue

        if (
            payload.capability == "terminal"
            and not item["terminal_runtime"]
        ):
            continue

        devices.append(
            item
        )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "devices": devices,
            },
            ensure_ascii=False,
        ),
        display=(
            f"Found {len(devices)} execution-capable "
            f"device{'s' if len(devices) != 1 else ''}."
        ),
    )


async def _run_command(
    payload,
    context: ToolContext,
    *,
    inspection_only: bool,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    await _require_device_capability(
        context,
        device_id=payload.device_id,
        capability="process.runtime",
    )

    if inspection_only:
        validate_inspection_command(
            payload.shell,
            payload.command,
        )
        mode = "foreground"
        timeout_seconds = (
            payload.timeout_seconds
        )
        wait_timeout_seconds = min(
            60.0,
            float(
                payload.timeout_seconds
            )
            + 5.0,
        )
    else:
        mode = payload.mode
        timeout_seconds = (
            payload.timeout_seconds
        )
        wait_timeout_seconds = (
            payload.wait_timeout_seconds
        )

    row = await process_runtime.start_process(
        user_id=None,
        device_id=payload.device_id,
        shell=payload.shell,
        command=payload.command,
        cwd=payload.cwd,
        mode=mode,
        timeout_seconds=timeout_seconds,
        conversation_id=(
            context.conversation_id
        ),
        wait_for_start=True,
    )

    if (
        mode == "foreground"
        and row.status
        not in {
            "completed",
            "failed",
            "cancelled",
            "timed_out",
            "lost",
        }
    ):
        row = await process_runtime.wait_for_exit(
            row.id,
            user_id=None,
            server_mode=False,
            timeout_seconds=(
                wait_timeout_seconds
            ),
        )

    chunks = await process_runtime.output(
        row.id,
        user_id=None,
        server_mode=False,
        after_sequence=0,
        limit=500,
    )

    output = _chunks_text(
        chunks
    )
    result = {
        "process": _process_dict(
            row
        ),
        "output": output,
    }

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Process {row.status}"
            + (
                f" with exit code {row.exit_code}."
                if row.exit_code
                is not None
                else "."
            )
        ),
        metadata={
            "process_id": row.id,
            "status": row.status,
        },
    )


async def inspect_device_command_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        InspectDeviceCommandInput,
    )

    return await _run_command(
        payload,
        context,
        inspection_only=True,
    )


async def run_device_command_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        RunDeviceCommandInput,
    )

    return await _run_command(
        payload,
        context,
        inspection_only=False,
    )


async def get_device_process_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        ProcessIdInput,
    )

    try:
        row = await process_runtime.get_process(
            payload.process_id,
            user_id=None,
            server_mode=False,
        )
    except LookupError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    return ToolExecutionResult(
        content=json.dumps(
            _process_dict(
                row
            ),
            ensure_ascii=False,
        ),
        display=(
            f"Process {row.id} is {row.status}."
        ),
    )


async def read_device_process_output_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        ReadProcessOutputInput,
    )

    try:
        chunks = await process_runtime.output(
            payload.process_id,
            user_id=None,
            server_mode=False,
            after_sequence=(
                payload.after_sequence
            ),
            limit=payload.limit,
        )
    except LookupError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    output = _chunks_text(
        chunks
    )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "process_id": (
                    payload.process_id
                ),
                "output": output,
                "count": len(
                    chunks
                ),
                "next_sequence": (
                    chunks[-1].sequence
                    if chunks
                    else payload.after_sequence
                ),
            },
            ensure_ascii=False,
        ),
        display=(
            f"Read {len(chunks)} process output "
            f"chunk{'s' if len(chunks) != 1 else ''}."
        ),
    )


async def stop_device_process_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        StopProcessInput,
    )

    try:
        row = await process_runtime.terminate_process(
            payload.process_id,
            user_id=None,
            server_mode=False,
            force=payload.force,
        )
    except LookupError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    return ToolExecutionResult(
        content=json.dumps(
            _process_dict(
                row
            ),
            ensure_ascii=False,
        ),
        display=(
            f"Termination requested for process {row.id}."
        ),
    )


async def open_device_terminal_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        OpenTerminalInput,
    )

    await _require_device_capability(
        context,
        device_id=payload.device_id,
        capability="terminal.runtime",
    )

    row = await terminal_runtime.open_terminal(
        user_id=None,
        device_id=payload.device_id,
        shell=payload.shell,
        cwd=payload.cwd,
        cols=payload.cols,
        rows=payload.rows,
        conversation_id=(
            context.conversation_id
        ),
        wait_for_start=True,
    )

    return ToolExecutionResult(
        content=json.dumps(
            _terminal_dict(
                row
            ),
            ensure_ascii=False,
        ),
        display=(
            f"Opened {payload.shell} terminal {row.id} "
            f"with status {row.status}."
        ),
        metadata={
            "terminal_id": row.id,
            "status": row.status,
        },
    )


async def read_device_terminal_output_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        ReadTerminalOutputInput,
    )

    try:
        chunks = await terminal_runtime.output(
            payload.terminal_id,
            user_id=None,
            server_mode=False,
            after_sequence=(
                payload.after_sequence
            ),
            limit=payload.limit,
        )
    except LookupError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    output = _chunks_text(
        chunks
    )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "terminal_id": (
                    payload.terminal_id
                ),
                "output": output,
                "count": len(
                    chunks
                ),
                "next_sequence": (
                    chunks[-1].sequence
                    if chunks
                    else payload.after_sequence
                ),
            },
            ensure_ascii=False,
        ),
        display=(
            f"Read {len(chunks)} terminal output "
            f"chunk{'s' if len(chunks) != 1 else ''}."
        ),
    )


async def send_device_terminal_input_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        SendTerminalInputInput,
    )

    try:
        row = await terminal_runtime.write_input(
            payload.terminal_id,
            user_id=None,
            server_mode=False,
            data=payload.data,
        )
    except (
        LookupError,
        RuntimeError,
        ConnectionError,
    ) as exc:
        raise ToolError(
            str(exc)
        ) from exc

    return ToolExecutionResult(
        content=json.dumps(
            {
                "terminal_id": row.id,
                "status": row.status,
                "input_bytes": len(
                    payload.data.encode(
                        "utf-8",
                        errors="replace",
                    )
                ),
            }
        ),
        display=(
            f"Sent input to terminal {row.id}."
        ),
    )


async def resize_device_terminal_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        ResizeTerminalInput,
    )

    try:
        row = await terminal_runtime.resize_terminal(
            payload.terminal_id,
            user_id=None,
            server_mode=False,
            cols=payload.cols,
            rows=payload.rows,
        )
    except (
        LookupError,
        RuntimeError,
        ConnectionError,
    ) as exc:
        raise ToolError(
            str(exc)
        ) from exc

    return ToolExecutionResult(
        content=json.dumps(
            _terminal_dict(
                row
            ),
            ensure_ascii=False,
        ),
        display=(
            f"Resized terminal {row.id} to "
            f"{row.cols}x{row.rows}."
        ),
    )


async def close_device_terminal_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    _require_local_execution_mode()

    payload = data
    assert isinstance(
        payload,
        CloseTerminalInput,
    )

    try:
        row = await terminal_runtime.close_terminal(
            payload.terminal_id,
            user_id=None,
            server_mode=False,
            force=payload.force,
        )
    except LookupError as exc:
        raise ToolError(
            str(exc)
        ) from exc

    return ToolExecutionResult(
        content=json.dumps(
            _terminal_dict(
                row
            ),
            ensure_ascii=False,
        ),
        display=(
            f"Close requested for terminal {row.id}."
        ),
    )


def register_execution_bridge_tools() -> None:
    definitions = [
        ToolDefinition(
            name="list_execution_devices",
            label="List execution devices",
            description=(
                "List connected Jace Device Agents and show whether each "
                "supports persistent process execution and interactive terminals. "
                "Use this before choosing a device ID."
            ),
            category="Device execution",
            risk="read",
            default_permission="allow",
            input_model=(
                ListExecutionDevicesInput
            ),
            handler=(
                list_execution_devices_tool
            ),
        ),
        ToolDefinition(
            name="inspect_device_command",
            label="Inspect with command",
            description=(
                "Run one strictly read-only inspection command on a paired "
                "device. Only a conservative command allowlist is accepted; "
                "pipes, chaining, redirection, writes and elevation are rejected."
            ),
            category="Device execution",
            risk="read",
            default_permission="allow",
            input_model=(
                InspectDeviceCommandInput
            ),
            handler=(
                inspect_device_command_tool
            ),
        ),
        ToolDefinition(
            name="run_device_command",
            label="Run device command",
            description=(
                "Run an arbitrary PowerShell, cmd, WSL or bash command under "
                "the Device Agent OS user. Use inspect_device_command for "
                "read-only inspection when possible."
            ),
            category="Device execution",
            risk="execute",
            default_permission="ask",
            input_model=(
                RunDeviceCommandInput
            ),
            handler=(
                run_device_command_tool
            ),
            policy_resolver=command_policy,
        ),
        ToolDefinition(
            name="get_device_process",
            label="Get process status",
            description=(
                "Get the durable status, PID and exit code for a Jace-managed "
                "device process by process ID."
            ),
            category="Device execution",
            risk="read",
            default_permission="allow",
            input_model=ProcessIdInput,
            handler=get_device_process_tool,
        ),
        ToolDefinition(
            name="read_device_process_output",
            label="Read process output",
            description=(
                "Read persisted stdout/stderr from a Jace-managed device process."
            ),
            category="Device execution",
            risk="read",
            default_permission="allow",
            input_model=(
                ReadProcessOutputInput
            ),
            handler=(
                read_device_process_output_tool
            ),
        ),
        ToolDefinition(
            name="stop_device_process",
            label="Stop device process",
            description=(
                "Terminate a Jace-managed device process tree."
            ),
            category="Device execution",
            risk="execute",
            default_permission="ask",
            input_model=StopProcessInput,
            handler=stop_device_process_tool,
            policy_resolver=(
                always_ask_policy(
                    "process_termination",
                    "Terminating a process tree requires explicit approval.",
                )
            ),
        ),
        ToolDefinition(
            name="open_device_terminal",
            label="Open device terminal",
            description=(
                "Open a persistent PTY/ConPTY shell session on a paired device."
            ),
            category="Device execution",
            risk="execute",
            default_permission="ask",
            input_model=OpenTerminalInput,
            handler=open_device_terminal_tool,
            policy_resolver=(
                always_ask_policy(
                    "interactive_terminal",
                    "Opening an interactive terminal requires explicit approval.",
                )
            ),
        ),
        ToolDefinition(
            name="read_device_terminal_output",
            label="Read terminal output",
            description=(
                "Read persisted output/scrollback from an existing Jace terminal."
            ),
            category="Device execution",
            risk="read",
            default_permission="allow",
            input_model=(
                ReadTerminalOutputInput
            ),
            handler=(
                read_device_terminal_output_tool
            ),
        ),
        ToolDefinition(
            name="send_device_terminal_input",
            label="Send terminal input",
            description=(
                "Send exact text or keystrokes to an existing interactive "
                "terminal. The input itself is not stored in the persistent "
                "tool audit."
            ),
            category="Device execution",
            risk="execute",
            default_permission="ask",
            input_model=(
                SendTerminalInputInput
            ),
            handler=(
                send_device_terminal_input_tool
            ),
            policy_resolver=(
                always_ask_policy(
                    "interactive_input",
                    "Interactive terminal input always requires explicit approval.",
                )
            ),
        ),
        ToolDefinition(
            name="resize_device_terminal",
            label="Resize device terminal",
            description=(
                "Resize an existing PTY/ConPTY terminal."
            ),
            category="Device execution",
            risk="write",
            default_permission="allow",
            input_model=(
                ResizeTerminalInput
            ),
            handler=(
                resize_device_terminal_tool
            ),
        ),
        ToolDefinition(
            name="close_device_terminal",
            label="Close device terminal",
            description=(
                "Close an existing Jace-managed interactive terminal."
            ),
            category="Device execution",
            risk="execute",
            default_permission="ask",
            input_model=(
                CloseTerminalInput
            ),
            handler=(
                close_device_terminal_tool
            ),
            policy_resolver=(
                always_ask_policy(
                    "terminal_close",
                    "Closing an interactive terminal requires explicit approval.",
                )
            ),
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
