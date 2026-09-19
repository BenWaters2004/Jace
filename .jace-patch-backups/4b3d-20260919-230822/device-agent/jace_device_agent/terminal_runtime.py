from __future__ import annotations

import asyncio
import os
import shutil
import signal
import struct
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jace_device_agent.config import AgentConfig


_FINAL = {
    "closed",
    "failed",
}


class _TerminalBackend:
    pid: int
    name: str

    async def read(self) -> str:
        raise NotImplementedError

    async def write(self, data: str) -> None:
        raise NotImplementedError

    async def resize(
        self,
        rows: int,
        cols: int,
    ) -> None:
        raise NotImplementedError

    async def is_alive(self) -> bool:
        raise NotImplementedError

    async def exit_code(self) -> int | None:
        raise NotImplementedError

    async def close(
        self,
        *,
        force: bool,
    ) -> None:
        raise NotImplementedError


class _WindowsTerminalBackend(_TerminalBackend):
    name = "conpty"

    def __init__(
        self,
        process,
    ) -> None:
        self.process = process
        self.pid = int(
            process.pid
        )

    @classmethod
    async def spawn(
        cls,
        *,
        shell: str,
        cwd: str | None,
        rows: int,
        cols: int,
    ):
        try:
            from winpty import PtyProcess
        except ImportError as exc:
            raise RuntimeError(
                "pywinpty is required for interactive "
                "Windows terminals. Re-run device-agent\\install.ps1."
            ) from exc

        argv = _shell_argv(
            shell
        )

        process = await asyncio.to_thread(
            PtyProcess.spawn,
            argv,
            cwd=cwd,
            dimensions=(
                rows,
                cols,
            ),
        )

        return cls(
            process
        )

    async def read(self) -> str:
        return await asyncio.to_thread(
            self.process.read,
            4096,
        )

    async def write(
        self,
        data: str,
    ) -> None:
        await asyncio.to_thread(
            self.process.write,
            data,
        )

    async def resize(
        self,
        rows: int,
        cols: int,
    ) -> None:
        await asyncio.to_thread(
            self.process.setwinsize,
            rows,
            cols,
        )

    async def is_alive(self) -> bool:
        return bool(
            await asyncio.to_thread(
                self.process.isalive
            )
        )

    async def exit_code(
        self,
    ) -> int | None:
        try:
            value = self.process.exitstatus
        except Exception:
            return None

        return (
            int(value)
            if value is not None
            else None
        )

    async def close(
        self,
        *,
        force: bool,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.process.terminate,
                force,
            )
        except Exception:
            pass

        try:
            await asyncio.to_thread(
                self.process.close,
                True,
            )
        except Exception:
            pass


class _PosixTerminalBackend(_TerminalBackend):
    name = "pty"

    def __init__(
        self,
        *,
        process: subprocess.Popen,
        master_fd: int,
    ) -> None:
        self.process = process
        self.master_fd = master_fd
        self.pid = int(
            process.pid
        )

    @classmethod
    async def spawn(
        cls,
        *,
        shell: str,
        cwd: str | None,
        rows: int,
        cols: int,
    ):
        import fcntl
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()

        winsize = struct.pack(
            "HHHH",
            rows,
            cols,
            0,
            0,
        )
        fcntl.ioctl(
            slave_fd,
            termios.TIOCSWINSZ,
            winsize,
        )

        argv = _shell_argv(
            shell
        )

        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            os.close(
                slave_fd
            )

        return cls(
            process=process,
            master_fd=master_fd,
        )

    async def read(self) -> str:
        try:
            data = await asyncio.to_thread(
                os.read,
                self.master_fd,
                4096,
            )
        except OSError:
            raise EOFError

        if not data:
            raise EOFError

        return data.decode(
            "utf-8",
            errors="replace",
        )

    async def write(
        self,
        data: str,
    ) -> None:
        await asyncio.to_thread(
            os.write,
            self.master_fd,
            data.encode(
                "utf-8",
                errors="replace",
            ),
        )

    async def resize(
        self,
        rows: int,
        cols: int,
    ) -> None:
        import fcntl
        import termios

        winsize = struct.pack(
            "HHHH",
            rows,
            cols,
            0,
            0,
        )

        await asyncio.to_thread(
            fcntl.ioctl,
            self.master_fd,
            termios.TIOCSWINSZ,
            winsize,
        )

    async def is_alive(self) -> bool:
        return (
            self.process.poll()
            is None
        )

    async def exit_code(
        self,
    ) -> int | None:
        return (
            int(self.process.returncode)
            if self.process.returncode
            is not None
            else None
        )

    async def close(
        self,
        *,
        force: bool,
    ) -> None:
        try:
            pgid = os.getpgid(
                self.process.pid
            )

            os.killpg(
                pgid,
                (
                    signal.SIGKILL
                    if force
                    else signal.SIGTERM
                ),
            )
        except Exception:
            pass

        try:
            os.close(
                self.master_fd
            )
        except OSError:
            pass


def _shell_argv(
    shell: str,
) -> list[str]:
    shell = shell.strip().lower()

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
            "-l",
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
            "-l",
        ]

    raise ValueError(
        f"Unsupported terminal shell: {shell}"
    )


@dataclass(slots=True)
class TerminalChunk:
    sequence: int
    data: str


@dataclass(slots=True)
class ManagedTerminal:
    terminal_id: str
    shell: str
    cwd: str | None
    cols: int
    rows: int
    backend: _TerminalBackend
    status: str = "running"
    sequence: int = 0
    output_truncated: bool = False
    history_bytes: int = 0
    history: deque[TerminalChunk] = field(
        default_factory=deque
    )
    sequence_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock
    )
    control_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock
    )
    exit_code: int | None = None
    completed_monotonic: float | None = None


class TerminalRuntimeManager:
    def __init__(
        self,
        config: AgentConfig,
    ) -> None:
        self.config = config
        self._sessions: dict[
            str,
            ManagedTerminal,
        ] = {}
        self._websocket = None
        self._lock = asyncio.Lock()

    def attach(
        self,
        websocket,
    ) -> None:
        self._websocket = websocket

    async def send_snapshot(
        self,
    ) -> None:
        await self._send(
            self.snapshot_message()
        )

    def snapshot_message(
        self,
    ) -> dict[str, Any]:
        self._prune_completed()

        return {
            "type": "terminal.snapshot",
            "sessions": [
                {
                    "terminal_id": (
                        session.terminal_id
                    ),
                    "pid": session.backend.pid,
                    "backend": session.backend.name,
                    "status": session.status,
                    "exit_code": session.exit_code,
                    "cols": session.cols,
                    "rows": session.rows,
                    "last_sequence": session.sequence,
                    "history_start_sequence": (
                        session.history[0].sequence
                        if session.history
                        else session.sequence + 1
                    ),
                    "output_truncated": (
                        session.output_truncated
                    ),
                }
                for session
                in self._sessions.values()
            ],
        }

    async def handle_message(
        self,
        message: dict[str, Any],
    ) -> bool:
        message_type = str(
            message.get("type")
            or ""
        )

        if message_type == "terminal.open":
            await self._open(
                message
            )
            return True

        if message_type == "terminal.input":
            await self._input(
                message
            )
            return True

        if message_type == "terminal.resize":
            await self._resize(
                message
            )
            return True

        if message_type == "terminal.close":
            await self._close(
                message
            )
            return True

        if (
            message_type
            == "terminal.replay.request"
        ):
            await self._replay(
                message
            )
            return True

        return False

    async def _open(
        self,
        message: dict[str, Any],
    ) -> None:
        terminal_id = str(
            message.get(
                "terminal_id"
            )
            or ""
        ).strip()

        if not terminal_id:
            return

        if not self.config.allow_terminal_sessions:
            await self._send(
                {
                    "type": "terminal.error",
                    "terminal_id": terminal_id,
                    "error": (
                        "Interactive terminal access is disabled "
                        "in the local Device Agent configuration."
                    ),
                }
            )
            return

        async with self._lock:
            existing = self._sessions.get(
                terminal_id
            )

            if existing is not None:
                await self._send(
                    {
                        "type": "terminal.started",
                        "terminal_id": terminal_id,
                        "pid": existing.backend.pid,
                        "backend": existing.backend.name,
                    }
                )
                return

            active = sum(
                1
                for session
                in self._sessions.values()
                if session.status
                not in _FINAL
            )

            if (
                active
                >= self.config.terminal_max_concurrent
            ):
                await self._send(
                    {
                        "type": "terminal.error",
                        "terminal_id": terminal_id,
                        "error": (
                            "Device Agent concurrent terminal "
                            "limit reached."
                        ),
                    }
                )
                return

        shell = str(
            message.get("shell")
            or ""
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

        rows = max(
            5,
            min(
                int(
                    message.get(
                        "rows"
                    )
                    or 30
                ),
                200,
            ),
        )
        cols = max(
            20,
            min(
                int(
                    message.get(
                        "cols"
                    )
                    or 120
                ),
                400,
            ),
        )

        try:
            if cwd is not None:
                expanded = Path(
                    os.path.expandvars(
                        os.path.expanduser(
                            cwd
                        )
                    )
                ).resolve()

                if not expanded.is_dir():
                    raise ValueError(
                        f"Working directory does not exist: {expanded}"
                    )

                cwd = str(
                    expanded
                )

            if os.name == "nt":
                backend = (
                    await _WindowsTerminalBackend.spawn(
                        shell=shell,
                        cwd=cwd,
                        rows=rows,
                        cols=cols,
                    )
                )
            else:
                backend = (
                    await _PosixTerminalBackend.spawn(
                        shell=shell,
                        cwd=cwd,
                        rows=rows,
                        cols=cols,
                    )
                )

            managed = ManagedTerminal(
                terminal_id=terminal_id,
                shell=shell,
                cwd=cwd,
                cols=cols,
                rows=rows,
                backend=backend,
            )

            async with self._lock:
                self._sessions[
                    terminal_id
                ] = managed

            await self._send(
                {
                    "type": "terminal.started",
                    "terminal_id": terminal_id,
                    "pid": backend.pid,
                    "backend": backend.name,
                }
            )

            asyncio.create_task(
                self._reader(
                    managed
                )
            )
            asyncio.create_task(
                self._monitor(
                    managed
                )
            )

        except Exception as exc:
            await self._send(
                {
                    "type": "terminal.error",
                    "terminal_id": terminal_id,
                    "error": str(
                        exc
                    ),
                }
            )

    async def _input(
        self,
        message: dict[str, Any],
    ) -> None:
        terminal_id = str(
            message.get(
                "terminal_id"
            )
            or ""
        ).strip()

        session = self._sessions.get(
            terminal_id
        )

        if (
            session is None
            or session.status
            != "running"
        ):
            await self._send(
                {
                    "type": "terminal.error",
                    "terminal_id": terminal_id,
                    "error": (
                        "Device Agent does not have a running "
                        "terminal with this ID."
                    ),
                }
            )
            return

        data = str(
            message.get("data")
            or ""
        )

        try:
            async with session.control_lock:
                await session.backend.write(
                    data
                )
        except Exception as exc:
            await self._send(
                {
                    "type": "terminal.error",
                    "terminal_id": terminal_id,
                    "error": str(
                        exc
                    ),
                }
            )

    async def _resize(
        self,
        message: dict[str, Any],
    ) -> None:
        terminal_id = str(
            message.get(
                "terminal_id"
            )
            or ""
        ).strip()

        session = self._sessions.get(
            terminal_id
        )

        if (
            session is None
            or session.status
            != "running"
        ):
            return

        rows = max(
            5,
            min(
                int(
                    message.get(
                        "rows"
                    )
                    or session.rows
                ),
                200,
            ),
        )
        cols = max(
            20,
            min(
                int(
                    message.get(
                        "cols"
                    )
                    or session.cols
                ),
                400,
            ),
        )

        async with session.control_lock:
            await session.backend.resize(
                rows,
                cols,
            )

        session.rows = rows
        session.cols = cols

    async def _close(
        self,
        message: dict[str, Any],
    ) -> None:
        terminal_id = str(
            message.get(
                "terminal_id"
            )
            or ""
        ).strip()

        session = self._sessions.get(
            terminal_id
        )

        if session is None:
            await self._send(
                {
                    "type": "terminal.exited",
                    "terminal_id": terminal_id,
                    "exit_code": None,
                }
            )
            return

        if session.status in _FINAL:
            await self._send(
                {
                    "type": "terminal.exited",
                    "terminal_id": terminal_id,
                    "exit_code": session.exit_code,
                }
            )
            return

        async with session.control_lock:
            await session.backend.close(
                force=bool(
                    message.get("force")
                ),
            )

    async def _reader(
        self,
        session: ManagedTerminal,
    ) -> None:
        while (
            session.status
            == "running"
        ):
            try:
                data = (
                    await session.backend.read()
                )
            except EOFError:
                return
            except Exception:
                if not await session.backend.is_alive():
                    return

                await asyncio.sleep(
                    0.05
                )
                continue

            if not data:
                await asyncio.sleep(
                    0.01
                )
                continue

            async with session.sequence_lock:
                session.sequence += 1
                sequence = (
                    session.sequence
                )

            self._remember(
                session,
                TerminalChunk(
                    sequence=sequence,
                    data=data,
                ),
            )

            await self._send(
                {
                    "type": "terminal.output",
                    "terminal_id": (
                        session.terminal_id
                    ),
                    "sequence": sequence,
                    "data": data,
                    "replayed": False,
                }
            )

    async def _monitor(
        self,
        session: ManagedTerminal,
    ) -> None:
        while (
            session.status
            == "running"
        ):
            if not await session.backend.is_alive():
                break

            await asyncio.sleep(
                0.1
            )

        if session.status in _FINAL:
            return

        session.exit_code = (
            await session.backend.exit_code()
        )
        session.status = "closed"
        session.completed_monotonic = (
            time.monotonic()
        )

        # One extra event-loop turn lets the reader consume final PTY bytes.
        await asyncio.sleep(
            0
        )

        await self._send(
            {
                "type": "terminal.exited",
                "terminal_id": (
                    session.terminal_id
                ),
                "exit_code": (
                    session.exit_code
                ),
            }
        )

    async def _replay(
        self,
        message: dict[str, Any],
    ) -> None:
        terminal_id = str(
            message.get(
                "terminal_id"
            )
            or ""
        ).strip()

        session = self._sessions.get(
            terminal_id
        )

        if session is None:
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
            session.history
        ):
            if (
                chunk.sequence
                <= after_sequence
            ):
                continue

            await self._send(
                {
                    "type": "terminal.output",
                    "terminal_id": (
                        terminal_id
                    ),
                    "sequence": (
                        chunk.sequence
                    ),
                    "data": chunk.data,
                    "replayed": True,
                }
            )

    def _remember(
        self,
        session: ManagedTerminal,
        chunk: TerminalChunk,
    ) -> None:
        chunk_bytes = len(
            chunk.data.encode(
                "utf-8",
                errors="replace",
            )
        )

        session.history.append(
            chunk
        )
        session.history_bytes += (
            chunk_bytes
        )

        maximum = max(
            65536,
            int(
                self.config
                .terminal_history_bytes
            ),
        )

        while (
            session.history
            and session.history_bytes
            > maximum
        ):
            removed = session.history.popleft()

            session.history_bytes -= len(
                removed.data.encode(
                    "utf-8",
                    errors="replace",
                )
            )
            session.output_truncated = True

    async def _send(
        self,
        message: dict[str, Any],
    ) -> bool:
        websocket = self._websocket

        if websocket is None:
            return False

        try:
            import json

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
            terminal_id
            for terminal_id, session
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

        for terminal_id in completed:
            self._sessions.pop(
                terminal_id,
                None,
            )
