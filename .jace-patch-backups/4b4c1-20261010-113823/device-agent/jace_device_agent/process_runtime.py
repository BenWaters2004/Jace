from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import signal
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from jace_device_agent.config import AgentConfig
from jace_device_agent.scope_security import resolve_scoped_cwd


_FINAL = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
}


@dataclass(slots=True)
class ProcessChunk:
    sequence: int
    stream: str
    data: str


@dataclass(slots=True)
class ManagedProcess:
    process_id: str
    shell: str
    command: str
    cwd: str | None
    mode: str
    timeout_seconds: int | None
    process: asyncio.subprocess.Process
    pid: int
    status: str = "running"
    exit_code: int | None = None
    sequence: int = 0
    cancel_requested: bool = False
    timed_out: bool = False
    output_truncated: bool = False
    history_bytes: int = 0
    history: deque[ProcessChunk] = field(
        default_factory=deque
    )
    sequence_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock
    )
    completed_monotonic: float | None = None


class ProcessRuntimeManager:
    """Owns subprocess lifecycles independently of the WebSocket connection."""

    def __init__(
        self,
        config: AgentConfig,
    ) -> None:
        self.config = config
        self._sessions: dict[
            str,
            ManagedProcess,
        ] = {}
        self._websocket = None
        self._lock = asyncio.Lock()
        atexit.register(
            self._kill_managed_sync
        )

    def attach(
        self,
        websocket,
    ) -> None:
        self._websocket = websocket

    async def send_snapshot(self) -> None:
        await self._send(
            self.snapshot_message()
        )

    def snapshot_message(
        self,
    ) -> dict[str, Any]:
        self._prune_completed()

        sessions = []

        for session in self._sessions.values():
            history_start = (
                session.history[0].sequence
                if session.history
                else session.sequence + 1
            )

            sessions.append(
                {
                    "process_id": (
                        session.process_id
                    ),
                    "pid": session.pid,
                    "status": session.status,
                    "exit_code": (
                        session.exit_code
                    ),
                    "last_sequence": (
                        session.sequence
                    ),
                    "history_start_sequence": (
                        history_start
                    ),
                    "output_truncated": (
                        session.output_truncated
                    ),
                }
            )

        return {
            "type": "process.snapshot",
            "sessions": sessions,
        }

    async def handle_message(
        self,
        message: dict[str, Any],
    ) -> bool:
        message_type = str(
            message.get("type")
            or ""
        )

        if message_type == "process.start":
            await self._start(
                message
            )
            return True

        if message_type == "process.terminate":
            await self._terminate_message(
                message
            )
            return True

        if (
            message_type
            == "process.replay.request"
        ):
            await self._replay(
                message
            )
            return True

        return False

    async def _start(
        self,
        message: dict[str, Any],
    ) -> None:
        process_id = str(
            message.get(
                "process_id"
            )
            or ""
        ).strip()

        if not process_id:
            return

        if not self.config.allow_process_execution:
            await self._send(
                {
                    "type": "process.error",
                    "process_id": process_id,
                    "error": (
                        "Process execution is disabled "
                        "in the local Device Agent configuration."
                    ),
                }
            )
            return

        async with self._lock:
            existing = self._sessions.get(
                process_id
            )

            if existing is not None:
                await self._send(
                    {
                        "type": "process.started",
                        "process_id": process_id,
                        "pid": existing.pid,
                    }
                )
                return

            running_count = sum(
                1
                for session
                in self._sessions.values()
                if session.status
                not in _FINAL
            )

            if (
                running_count
                >= self.config.process_max_concurrent
            ):
                await self._send(
                    {
                        "type": "process.error",
                        "process_id": process_id,
                        "error": (
                            "Device Agent concurrent process "
                            "limit reached."
                        ),
                    }
                )
                return

        shell = str(
            message.get("shell")
            or ""
        ).strip().lower()

        command = str(
            message.get("command")
            or ""
        )

        mode = str(
            message.get("mode")
            or "background"
        ).strip().lower()

        cwd_raw = message.get(
            "cwd"
        )

        cwd = (
            str(cwd_raw).strip()
            if cwd_raw is not None
            and str(cwd_raw).strip()
            else None
        )
        scope_root_raw = message.get(
            "scope_root"
        )
        scope_root = (
            str(scope_root_raw).strip()
            if scope_root_raw is not None
            and str(scope_root_raw).strip()
            else None
        )

        timeout_raw = message.get(
            "timeout_seconds"
        )

        timeout_seconds = (
            max(
                1,
                int(timeout_raw),
            )
            if timeout_raw
            is not None
            else None
        )

        try:
            args = self._invocation(
                shell,
                command,
            )

            # JACE_4B3D_DEVICE_PROCESS_SCOPE_ENFORCEMENT
            cwd = resolve_scoped_cwd(
                cwd,
                scope_root,
            )

            kwargs: dict[
                str,
                Any,
            ] = {
                "cwd": cwd,
                "stdin": (
                    asyncio.subprocess.DEVNULL
                ),
                "stdout": (
                    asyncio.subprocess.PIPE
                ),
                "stderr": (
                    asyncio.subprocess.PIPE
                ),
            }

            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess
                    .CREATE_NEW_PROCESS_GROUP
                )
            else:
                kwargs["start_new_session"] = (
                    True
                )

            process = (
                await asyncio.create_subprocess_exec(
                    *args,
                    **kwargs,
                )
            )

            managed = ManagedProcess(
                process_id=process_id,
                shell=shell,
                command=command,
                cwd=cwd,
                mode=mode,
                timeout_seconds=timeout_seconds,
                process=process,
                pid=int(
                    process.pid
                ),
            )

            async with self._lock:
                self._sessions[
                    process_id
                ] = managed

            await self._send(
                {
                    "type": "process.started",
                    "process_id": process_id,
                    "pid": managed.pid,
                }
            )

            asyncio.create_task(
                self._read_stream(
                    managed,
                    "stdout",
                    process.stdout,
                )
            )

            asyncio.create_task(
                self._read_stream(
                    managed,
                    "stderr",
                    process.stderr,
                )
            )

            asyncio.create_task(
                self._wait_for_exit(
                    managed
                )
            )

            if timeout_seconds is not None:
                asyncio.create_task(
                    self._watchdog(
                        managed
                    )
                )

        except Exception as exc:
            await self._send(
                {
                    "type": "process.error",
                    "process_id": process_id,
                    "error": str(
                        exc
                    ),
                }
            )

    def _invocation(
        self,
        shell: str,
        command: str,
    ) -> list[str]:
        if not command.strip():
            raise ValueError(
                "Process command cannot be empty."
            )

        if shell == "powershell":
            executable = (
                shutil.which("pwsh")
                or shutil.which(
                    "powershell.exe"
                )
                or shutil.which(
                    "powershell"
                )
            )

            if executable is None:
                raise RuntimeError(
                    "PowerShell is not available."
                )

            return [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]

        if shell == "cmd":
            executable = (
                shutil.which("cmd.exe")
                or shutil.which("cmd")
            )

            if executable is None:
                raise RuntimeError(
                    "cmd.exe is not available."
                )

            return [
                executable,
                "/d",
                "/s",
                "/c",
                command,
            ]

        if shell == "wsl":
            executable = (
                shutil.which("wsl.exe")
                or shutil.which("wsl")
            )

            if executable is None:
                raise RuntimeError(
                    "WSL is not available."
                )

            return [
                executable,
                "--exec",
                "bash",
                "-lc",
                command,
            ]

        if shell == "bash":
            executable = shutil.which(
                "bash"
            )

            if executable is None:
                raise RuntimeError(
                    "bash is not available."
                )

            return [
                executable,
                "-lc",
                command,
            ]

        raise ValueError(
            f"Unsupported process shell: {shell}"
        )

    async def _read_stream(
        self,
        managed: ManagedProcess,
        stream_name: str,
        stream: asyncio.StreamReader | None,
    ) -> None:
        if stream is None:
            return

        while True:
            chunk = await stream.read(
                4096
            )

            if not chunk:
                return

            text = chunk.decode(
                "utf-8",
                errors="replace",
            )

            async with managed.sequence_lock:
                managed.sequence += 1
                sequence = (
                    managed.sequence
                )

            self._remember(
                managed,
                ProcessChunk(
                    sequence=sequence,
                    stream=stream_name,
                    data=text,
                ),
            )

            await self._send(
                {
                    "type": "process.output",
                    "process_id": (
                        managed.process_id
                    ),
                    "sequence": sequence,
                    "stream": stream_name,
                    "data": text,
                    "replayed": False,
                }
            )

    def _remember(
        self,
        managed: ManagedProcess,
        chunk: ProcessChunk,
    ) -> None:
        encoded_bytes = len(
            chunk.data.encode(
                "utf-8",
                errors="replace",
            )
        )

        managed.history.append(
            chunk
        )
        managed.history_bytes += (
            encoded_bytes
        )

        maximum = max(
            65536,
            int(
                self.config
                .process_history_bytes
            ),
        )

        while (
            managed.history
            and managed.history_bytes
            > maximum
        ):
            removed = managed.history.popleft()
            managed.history_bytes -= len(
                removed.data.encode(
                    "utf-8",
                    errors="replace",
                )
            )
            managed.output_truncated = True

    async def _watchdog(
        self,
        managed: ManagedProcess,
    ) -> None:
        try:
            await asyncio.sleep(
                managed.timeout_seconds
                or 0
            )
        except asyncio.CancelledError:
            return

        if managed.status in _FINAL:
            return

        managed.timed_out = True

        await self._terminate_tree(
            managed,
            force=True,
        )

    async def _terminate_message(
        self,
        message: dict[str, Any],
    ) -> None:
        process_id = str(
            message.get(
                "process_id"
            )
            or ""
        ).strip()

        managed = self._sessions.get(
            process_id
        )

        if managed is None:
            await self._send(
                {
                    "type": "process.error",
                    "process_id": process_id,
                    "error": (
                        "Device Agent does not track this process."
                    ),
                }
            )
            return

        if managed.status in _FINAL:
            await self._send(
                {
                    "type": "process.exited",
                    "process_id": process_id,
                    "status": managed.status,
                    "exit_code": managed.exit_code,
                }
            )
            return

        managed.cancel_requested = True

        await self._terminate_tree(
            managed,
            force=bool(
                message.get("force")
            ),
        )

    async def _terminate_tree(
        self,
        managed: ManagedProcess,
        *,
        force: bool,
    ) -> None:
        await asyncio.to_thread(
            self._terminate_tree_sync,
            managed.pid,
            force,
        )

    @staticmethod
    def _terminate_tree_sync(
        pid: int,
        force: bool,
    ) -> None:
        try:
            parent = psutil.Process(
                pid
            )
        except psutil.Error:
            return

        children = parent.children(
            recursive=True
        )
        processes = (
            children
            + [parent]
        )

        for process in processes:
            try:
                if force:
                    process.kill()
                else:
                    process.terminate()
            except psutil.Error:
                pass

        if not force:
            _gone, alive = (
                psutil.wait_procs(
                    processes,
                    timeout=2.0,
                )
            )

            for process in alive:
                try:
                    process.kill()
                except psutil.Error:
                    pass

    async def _wait_for_exit(
        self,
        managed: ManagedProcess,
    ) -> None:
        exit_code = (
            await managed.process.wait()
        )

        # Give stdout/stderr reader tasks a chance to consume the final pipe
        # bytes before the terminal status is emitted.
        await asyncio.sleep(
            0
        )

        managed.exit_code = int(
            exit_code
        )

        if managed.timed_out:
            managed.status = "timed_out"
        elif managed.cancel_requested:
            managed.status = "cancelled"
        elif exit_code == 0:
            managed.status = "completed"
        else:
            managed.status = "failed"

        managed.completed_monotonic = (
            time.monotonic()
        )

        await self._send(
            {
                "type": "process.exited",
                "process_id": (
                    managed.process_id
                ),
                "status": managed.status,
                "exit_code": (
                    managed.exit_code
                ),
            }
        )

    async def _replay(
        self,
        message: dict[str, Any],
    ) -> None:
        process_id = str(
            message.get(
                "process_id"
            )
            or ""
        ).strip()

        managed = self._sessions.get(
            process_id
        )

        if managed is None:
            return

        try:
            after_sequence = int(
                message.get(
                    "after_sequence"
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            after_sequence = 0

        for chunk in list(
            managed.history
        ):
            if (
                chunk.sequence
                <= after_sequence
            ):
                continue

            await self._send(
                {
                    "type": "process.output",
                    "process_id": (
                        managed.process_id
                    ),
                    "sequence": (
                        chunk.sequence
                    ),
                    "stream": (
                        chunk.stream
                    ),
                    "data": chunk.data,
                    "replayed": True,
                }
            )

    async def _send(
        self,
        message: dict[str, Any],
    ) -> bool:
        websocket = self._websocket

        if websocket is None:
            return False

        try:
            await websocket.send(
                json.dumps(
                    message,
                    ensure_ascii=False,
                )
            )
            return True
        except Exception:
            return False

    def _prune_completed(
        self,
    ) -> None:
        cutoff = (
            time.monotonic()
            - 3600
        )

        completed = [
            process_id
            for process_id, session
            in self._sessions.items()
            if (
                session.status
                in _FINAL
                and session.completed_monotonic
                is not None
                and session.completed_monotonic
                < cutoff
            )
        ]

        for process_id in completed:
            self._sessions.pop(
                process_id,
                None,
            )

    def _kill_managed_sync(
        self,
    ) -> None:
        for session in list(
            self._sessions.values()
        ):
            if session.status in _FINAL:
                continue

            try:
                self._terminate_tree_sync(
                    session.pid,
                    True,
                )
            except Exception:
                pass
