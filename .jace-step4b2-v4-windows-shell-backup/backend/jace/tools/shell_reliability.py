from __future__ import annotations

# JACE_STEP4B2_V3_SHELL_RELIABILITY

import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from jace.computer.host_access import (
    HostPathError,
    expand_host_path,
)
from jace.config import settings
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.computer import _command_environment
from jace.tools.registry import registry


ShellName = Literal[
    "powershell",
    "cmd",
    "bash",
    "wsl",
]


class ShellCommandInput(BaseModel):
    shell: ShellName = Field(
        default="powershell",
        description=(
            "Shell to use: powershell, cmd, bash, or wsl."
        ),
    )
    command: str = Field(
        min_length=1,
        max_length=50_000,
        description=(
            "Exact command/script to run. This exact text is shown to the "
            "user for approval before execution."
        ),
    )
    cwd: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Optional host working directory. Defaults to the current user's home."
        ),
    )
    timeout_seconds: int = Field(
        default=120,
        ge=1,
        le=900,
    )


def _existing(
    *candidates: str | Path | None,
) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue

        value = Path(
            str(candidate)
        )

        try:
            if value.is_file():
                return str(
                    value
                )
        except OSError:
            continue

    return None


def _windows_powershell() -> str:
    system_root = (
        os.environ.get(
            "SystemRoot"
        )
        or os.environ.get(
            "WINDIR"
        )
        or r"C:\Windows"
    )

    executable = _existing(
        shutil.which(
            "pwsh.exe"
        ),
        shutil.which(
            "pwsh"
        ),
        shutil.which(
            "powershell.exe"
        ),
        Path(
            system_root
        )
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe",
    )

    if not executable:
        raise ToolError(
            "PowerShell executable was not found. Checked pwsh.exe, "
            "powershell.exe, and the standard Windows PowerShell location."
        )

    return executable


def _windows_cmd() -> str:
    system_root = (
        os.environ.get(
            "SystemRoot"
        )
        or os.environ.get(
            "WINDIR"
        )
        or r"C:\Windows"
    )

    executable = _existing(
        os.environ.get(
            "COMSPEC"
        ),
        shutil.which(
            "cmd.exe"
        ),
        Path(
            system_root
        )
        / "System32"
        / "cmd.exe",
    )

    if not executable:
        raise ToolError(
            "cmd.exe was not found."
        )

    return executable


def _shell_invocation(
    shell: ShellName,
    command: str,
) -> tuple[
    str,
    list[str],
]:
    if os.name == "nt":
        if shell == "powershell":
            executable = _windows_powershell()

            # Force predictable UTF-8 stdout/stderr without changing the
            # command text shown in the approval modal.
            wrapped = (
                "[Console]::OutputEncoding = "
                "[System.Text.Encoding]::UTF8; "
                "$OutputEncoding = [System.Text.Encoding]::UTF8; "
                + command
            )

            return (
                executable,
                [
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    wrapped,
                ],
            )

        if shell == "cmd":
            executable = _windows_cmd()
            return (
                executable,
                [
                    "/d",
                    "/s",
                    "/c",
                    command,
                ],
            )

        if shell == "wsl":
            executable = (
                shutil.which(
                    "wsl.exe"
                )
                or shutil.which(
                    "wsl"
                )
            )

            if not executable:
                raise ToolError(
                    "wsl.exe was not found."
                )

            return (
                executable,
                [
                    "--",
                    "bash",
                    "-lc",
                    command,
                ],
            )

        executable = (
            shutil.which(
                "bash.exe"
            )
            or shutil.which(
                "bash"
            )
        )

        if not executable:
            raise ToolError(
                "bash was not found."
            )

        return (
            executable,
            [
                "-lc",
                command,
            ],
        )

    if shell == "powershell":
        executable = shutil.which(
            "pwsh"
        )

        if not executable:
            raise ToolError(
                "pwsh was not found."
            )

        return (
            executable,
            [
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
        )

    if shell == "cmd":
        raise ToolError(
            "cmd is available only on Windows."
        )

    if shell == "wsl":
        raise ToolError(
            "WSL is available only on Windows."
        )

    executable = shutil.which(
        "bash"
    )

    if not executable:
        raise ToolError(
            "bash was not found."
        )

    return (
        executable,
        [
            "-lc",
            command,
        ],
    )


def _shell_environment() -> dict[str, str]:
    env = _command_environment()

    # These are needed by normal shell/module discovery and are not secrets.
    for key in (
        "HOME",
        "USERNAME",
        "USERDOMAIN",
        "PSModulePath",
        "OneDrive",
        "OneDriveConsumer",
        "OneDriveCommercial",
    ):
        value = os.environ.get(
            key
        )

        if value:
            env[
                key
            ] = value

    return env


async def _kill_process_tree(
    process: asyncio.subprocess.Process,
) -> None:
    if process.returncode is not None:
        return

    if os.name == "nt":
        taskkill = (
            shutil.which(
                "taskkill.exe"
            )
            or shutil.which(
                "taskkill"
            )
        )

        if taskkill:
            try:
                killer = await asyncio.create_subprocess_exec(
                    taskkill,
                    "/PID",
                    str(
                        process.pid
                    ),
                    "/T",
                    "/F",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(
                    killer.communicate(),
                    timeout=10,
                )
            except Exception:
                pass

        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    else:
        try:
            os.killpg(
                process.pid,
                signal.SIGKILL,
            )
        except Exception:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    try:
        await process.communicate()
    except Exception:
        pass


def _decode(
    raw: bytes,
) -> str:
    for encoding in (
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "cp850",
    ):
        try:
            return raw.decode(
                encoding
            )
        except UnicodeDecodeError:
            continue

    return raw.decode(
        "utf-8",
        errors="replace",
    )


def _truncate(
    value: str,
) -> tuple[
    str,
    bool,
]:
    limit = max(
        2000,
        settings.computer_command_output_chars,
    )

    if len(
        value
    ) <= limit:
        return (
            value,
            False,
        )

    return (
        value[
            :limit
        ]
        + "\n…[output truncated]",
        True,
    )


async def run_shell_command_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        ShellCommandInput,
    )

    try:
        cwd = (
            expand_host_path(
                payload.cwd,
                must_exist=True,
            )
            if payload.cwd
            else Path.home().resolve(
                strict=True
            )
        )
    except (
        HostPathError,
        OSError,
    ) as exc:
        raise ToolError(
            f"Invalid shell working directory: {exc}"
        ) from exc

    if not cwd.is_dir():
        raise ToolError(
            "Shell working directory must be a directory."
        )

    executable, arguments = _shell_invocation(
        payload.shell,
        payload.command,
    )

    creation_kwargs: dict[
        str,
        Any,
    ] = {}

    if os.name != "nt":
        creation_kwargs[
            "start_new_session"
        ] = True

    started = time.perf_counter()

    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            cwd=str(
                cwd
            ),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_shell_environment(),
            **creation_kwargs,
        )
    except Exception as exc:
        raise ToolError(
            "Could not start shell command. "
            f"Shell={payload.shell}; executable={executable!r}; "
            f"cwd={str(cwd)!r}; OS error={type(exc).__name__}: {exc}"
        ) from exc

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            process.communicate(),
            timeout=payload.timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        await _kill_process_tree(
            process
        )
        raise ToolError(
            f"Shell command timed out after {payload.timeout_seconds} seconds. "
            "The process tree was terminated."
        ) from exc
    except asyncio.CancelledError:
        await _kill_process_tree(
            process
        )
        raise

    duration_ms = int(
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    stdout, stdout_truncated = _truncate(
        _decode(
            stdout_raw
        )
    )
    stderr, stderr_truncated = _truncate(
        _decode(
            stderr_raw
        )
    )

    result = {
        "status":
            (
                "succeeded"
                if process.returncode == 0
                else "failed"
            ),
        "shell":
            payload.shell,
        "resolved_executable":
            executable,
        "command":
            payload.command,
        "cwd":
            str(
                cwd
            ),
        "exit_code":
            process.returncode,
        "duration_ms":
            duration_ms,
        "stdout":
            stdout,
        "stderr":
            stderr,
        "stdout_truncated":
            stdout_truncated,
        "stderr_truncated":
            stderr_truncated,
    }

    summary = (
        f"Ran {payload.shell} command using {executable} "
        f"(exit {process.returncode}, {duration_ms} ms)."
    )

    if process.returncode != 0:
        # Surface a real tool failure to the agent. Include both output channels
        # so Jace can report the exact failure instead of saying the command is
        # still processing or merely "hit a wall".
        raise ToolError(
            "Shell command failed. "
            + json.dumps(
                result,
                ensure_ascii=False,
            )
        )

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=summary,
        metadata={
            "shell":
                payload.shell,
            "resolved_executable":
                executable,
            "cwd":
                str(
                    cwd
                ),
            "exit_code":
                process.returncode,
            "duration_ms":
                duration_ms,
            "success":
                process.returncode
                == 0,
        },
    )


def register_shell_reliability_tool() -> None:
    if not settings.computer_enabled:
        return

    registry.register(
        ToolDefinition(
            name="run_shell_command",
            label="Run shell command",
            description=(
                "Run an arbitrary PowerShell, cmd, Bash or WSL command under "
                "the same OS user as Jace. The exact shell, command and working "
                "directory are shown for mandatory user approval before every "
                "execution. Return the real exit code, stdout and stderr. If a "
                "command fails, report the returned error exactly rather than "
                "claiming that it is still processing."
            ),
            category="Computer",
            risk="execute",
            default_permission="ask",
            input_model=ShellCommandInput,
            handler=run_shell_command_tool,
        ),
        replace=True,
    )
