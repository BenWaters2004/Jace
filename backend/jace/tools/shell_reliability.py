from __future__ import annotations

# JACE_STEP4B2_V4_WINDOWS_SHELL_SUBPROCESS_FIX

import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
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
        description="Shell to use: powershell, cmd, bash, or wsl.",
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

    # Normal shell/module discovery values, not credentials.
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


def _terminate_process_tree_sync(
    process: subprocess.Popen[bytes],
) -> None:
    if process.poll() is not None:
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
                subprocess.run(
                    [
                        taskkill,
                        "/PID",
                        str(
                            process.pid
                        ),
                        "/T",
                        "/F",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except Exception:
                pass

        if process.poll() is None:
            try:
                process.kill()
            except OSError:
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
            except OSError:
                pass

    try:
        process.wait(
            timeout=10
        )
    except Exception:
        pass


def _start_process(
    executable: str,
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    creationflags = 0
    start_new_session = False

    if os.name == "nt":
        creationflags |= getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        )
        creationflags |= getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        start_new_session = True

    return subprocess.Popen(
        [
            executable,
            *arguments,
        ],
        cwd=str(
            cwd
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        shell=False,
        creationflags=creationflags,
        start_new_session=start_new_session,
    )


def _communicate_process(
    process: subprocess.Popen[bytes],
    timeout_seconds: int,
) -> tuple[
    bytes,
    bytes,
]:
    return process.communicate(
        timeout=timeout_seconds
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

    started = time.perf_counter()

    try:
        process = await asyncio.to_thread(
            _start_process,
            executable,
            arguments,
            cwd=cwd,
            env=_shell_environment(),
        )
    except Exception as exc:
        raise ToolError(
            "Could not start shell command. "
            f"Shell={payload.shell}; executable={executable!r}; "
            f"cwd={str(cwd)!r}; OS error={type(exc).__name__}: {exc}"
        ) from exc

    communicate_task = asyncio.create_task(
        asyncio.to_thread(
            _communicate_process,
            process,
            payload.timeout_seconds,
        )
    )

    try:
        stdout_raw, stderr_raw = await asyncio.shield(
            communicate_task
        )
    except subprocess.TimeoutExpired as exc:
        await asyncio.to_thread(
            _terminate_process_tree_sync,
            process,
        )

        raise ToolError(
            f"Shell command timed out after {payload.timeout_seconds} seconds. "
            "The process tree was terminated."
        ) from exc
    except asyncio.CancelledError:
        await asyncio.to_thread(
            _terminate_process_tree_sync,
            process,
        )

        # Let the worker-side communicate() return after process termination.
        try:
            await asyncio.wait_for(
                asyncio.shield(
                    communicate_task
                ),
                timeout=10,
            )
        except Exception:
            pass

        raise
    except Exception as exc:
        await asyncio.to_thread(
            _terminate_process_tree_sync,
            process,
        )

        raise ToolError(
            "Shell process communication failed. "
            f"Shell={payload.shell}; executable={executable!r}; "
            f"cwd={str(cwd)!r}; error={type(exc).__name__}: {exc}"
        ) from exc

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
        "execution_backend":
            "subprocess.Popen via asyncio.to_thread",
        "event_loop_type":
            type(
                asyncio.get_running_loop()
            ).__name__,
    }

    if process.returncode != 0:
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
        display=(
            f"Ran {payload.shell} command using {executable} "
            f"(exit {process.returncode}, {duration_ms} ms)."
        ),
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
                True,
            "execution_backend":
                "subprocess.Popen via asyncio.to_thread",
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
                "execution. Uses an event-loop-independent Windows subprocess "
                "backend so it works even when FastAPI/Uvicorn is running a "
                "SelectorEventLoop."
            ),
            category="Computer",
            risk="execute",
            default_permission="ask",
            input_model=ShellCommandInput,
            handler=run_shell_command_tool,
        ),
        replace=True,
    )
