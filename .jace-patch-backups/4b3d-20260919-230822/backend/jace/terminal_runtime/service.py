from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from jace.config import settings
from jace.database import SessionLocal
from jace.db.models import (
    Device,
    TerminalOutputChunk,
    TerminalSession,
    utc_now,
)
from jace.devices.connections import device_connections
from jace.devices.service import device_response
from jace.runtime import runtime_events


_FINAL_STATUSES = {
    "closed",
    "failed",
    "lost",
}

_ACTIVE_STATUSES = {
    "starting",
    "running",
    "close_requested",
}

_ALLOWED_SHELLS = {
    "powershell",
    "cmd",
    "wsl",
    "bash",
}


class TerminalRuntimeService:
    def __init__(self) -> None:
        self._start_waiters: dict[
            str,
            asyncio.Future[None],
        ] = {}
        self._exit_waiters: dict[
            str,
            asyncio.Future[None],
        ] = {}
        self._lock = asyncio.Lock()

    async def open_terminal(
        self,
        *,
        user_id: str | None,
        device_id: str,
        shell: str,
        cwd: str | None,
        cols: int,
        rows: int,
        project_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        wait_for_start: bool = True,
    ) -> TerminalSession:
        if not settings.terminal_runtime_enabled:
            raise PermissionError(
                "Jace terminal runtime is disabled."
            )

        shell = shell.strip().lower()

        if shell not in _ALLOWED_SHELLS:
            raise ValueError(
                f"Unsupported terminal shell: {shell}"
            )

        cols = max(
            20,
            min(
                int(cols),
                400,
            ),
        )
        rows = max(
            5,
            min(
                int(rows),
                200,
            ),
        )

        async with SessionLocal() as session:
            result = await session.execute(
                select(Device).where(
                    Device.id == device_id
                )
            )
            device = result.scalar_one_or_none()

            if device is None:
                raise LookupError(
                    "Device not found."
                )

            if (
                not device.is_active
                or device.revoked_at is not None
            ):
                raise PermissionError(
                    "Device is revoked."
                )

            capabilities = set(
                device_response(device).capabilities
            )

            if "terminal.runtime" not in capabilities:
                raise PermissionError(
                    "Interactive terminal access is not enabled "
                    "on this device."
                )

            if not await device_connections.is_connected(
                device_id
            ):
                raise ConnectionError(
                    "Device is not connected."
                )

            row = TerminalSession(
                user_id=user_id,
                device_id=device_id,
                shell=shell,
                cwd=(
                    cwd.strip()
                    if isinstance(cwd, str)
                    and cwd.strip()
                    else None
                ),
                cols=cols,
                rows=rows,
                status="starting",
                output_bytes=0,
                output_truncated=0,
                last_agent_sequence=0,
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                created_at=utc_now(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

        start_future: asyncio.Future[None] | None = None

        if wait_for_start:
            start_future = (
                asyncio.get_running_loop()
                .create_future()
            )

            async with self._lock:
                self._start_waiters[
                    row.id
                ] = start_future

        await runtime_events.publish(
            "terminal.created",
            terminal_id=row.id,
            device_id=row.device_id,
            shell=row.shell,
            cwd=row.cwd,
            cols=row.cols,
            rows=row.rows,
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        sent = await device_connections.send(
            device_id,
            {
                "type": "terminal.open",
                "terminal_id": row.id,
                "shell": row.shell,
                "cwd": row.cwd,
                "cols": row.cols,
                "rows": row.rows,
            },
        )

        if not sent:
            await self._mark_failed(
                row.id,
                "Device disconnected before terminal start.",
            )
            await self._resolve_start_waiter(
                row.id
            )

            return await self.get_terminal(
                row.id,
                user_id=user_id,
                server_mode=False,
            )

        if (
            wait_for_start
            and start_future is not None
        ):
            try:
                await asyncio.wait_for(
                    asyncio.shield(
                        start_future
                    ),
                    timeout=(
                        settings
                        .terminal_start_ack_timeout_seconds
                    ),
                )
            except asyncio.TimeoutError:
                await self._mark_failed(
                    row.id,
                    "Device Agent did not acknowledge terminal "
                    "start within the configured timeout.",
                )

                await device_connections.send(
                    device_id,
                    {
                        "type": "terminal.close",
                        "terminal_id": row.id,
                        "force": True,
                        "reason": "start_ack_timeout",
                    },
                )
            finally:
                async with self._lock:
                    self._start_waiters.pop(
                        row.id,
                        None,
                    )

        return await self.get_terminal(
            row.id,
            user_id=user_id,
            server_mode=False,
        )

    async def write_input(
        self,
        terminal_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        data: str,
    ) -> TerminalSession:
        row = await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status != "running":
            raise RuntimeError(
                "Terminal is not running."
            )

        if len(data) > settings.terminal_input_max_chars:
            raise ValueError(
                "Terminal input exceeds the configured limit."
            )

        sent = await device_connections.send(
            row.device_id,
            {
                "type": "terminal.input",
                "terminal_id": row.id,
                "data": data,
            },
        )

        if not sent:
            await self._mark_lost(
                row.id,
                "Device disconnected while terminal input "
                "was being sent.",
            )
            raise ConnectionError(
                "Device is not connected."
            )

        # Never persist the actual terminal input. The metadata event only
        # records byte length for observability.
        await runtime_events.publish(
            "terminal.input.sent",
            terminal_id=row.id,
            device_id=row.device_id,
            input_bytes=len(
                data.encode(
                    "utf-8",
                    errors="replace",
                )
            ),
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        return row

    async def resize_terminal(
        self,
        terminal_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        cols: int,
        rows: int,
    ) -> TerminalSession:
        row = await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status != "running":
            raise RuntimeError(
                "Terminal is not running."
            )

        cols = max(
            20,
            min(
                int(cols),
                400,
            ),
        )
        rows = max(
            5,
            min(
                int(rows),
                200,
            ),
        )

        sent = await device_connections.send(
            row.device_id,
            {
                "type": "terminal.resize",
                "terminal_id": row.id,
                "cols": cols,
                "rows": rows,
            },
        )

        if not sent:
            await self._mark_lost(
                row.id,
                "Device disconnected while terminal resize "
                "was being sent.",
            )
            raise ConnectionError(
                "Device is not connected."
            )

        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.id
                    == terminal_id
                )
            )
            current = result.scalar_one()
            current.cols = cols
            current.rows = rows
            await session.commit()

        await runtime_events.publish(
            "terminal.resized",
            terminal_id=row.id,
            device_id=row.device_id,
            cols=cols,
            rows=rows,
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        return await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

    async def close_terminal(
        self,
        terminal_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        force: bool = False,
    ) -> TerminalSession:
        row = await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status in _FINAL_STATUSES:
            return row

        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.id
                    == terminal_id
                )
            )
            current = result.scalar_one()

            if current.status not in _FINAL_STATUSES:
                current.status = (
                    "close_requested"
                )
                current.close_requested_at = (
                    utc_now()
                )
                await session.commit()

        sent = await device_connections.send(
            row.device_id,
            {
                "type": "terminal.close",
                "terminal_id": row.id,
                "force": bool(force),
                "reason": "user_requested",
            },
        )

        if not sent:
            await self._mark_lost(
                row.id,
                "Device disconnected while terminal close "
                "was requested.",
            )

        await runtime_events.publish(
            "terminal.close_requested",
            terminal_id=row.id,
            device_id=row.device_id,
            force=bool(force),
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        return await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

    async def get_terminal(
        self,
        terminal_id: str,
        *,
        user_id: str | None = None,
        server_mode: bool = False,
    ) -> TerminalSession:
        async with SessionLocal() as session:
            statement = select(
                TerminalSession
            ).where(
                TerminalSession.id
                == terminal_id
            )

            if server_mode:
                statement = statement.where(
                    TerminalSession.user_id
                    == user_id
                )

            result = await session.execute(
                statement
            )
            row = result.scalar_one_or_none()

            if row is None:
                raise LookupError(
                    "Terminal session not found."
                )

            return row

    async def list_terminals(
        self,
        *,
        user_id: str | None,
        server_mode: bool,
        device_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TerminalSession]:
        statement = (
            select(TerminalSession)
            .order_by(
                TerminalSession.created_at.desc()
            )
            .limit(
                max(
                    1,
                    min(
                        int(limit),
                        500,
                    ),
                )
            )
        )

        if server_mode:
            statement = statement.where(
                TerminalSession.user_id
                == user_id
            )

        if device_id:
            statement = statement.where(
                TerminalSession.device_id
                == device_id
            )

        if status:
            statement = statement.where(
                TerminalSession.status
                == status
            )

        async with SessionLocal() as session:
            result = await session.execute(
                statement
            )
            return list(
                result.scalars().all()
            )

    async def output(
        self,
        terminal_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[TerminalOutputChunk]:
        await self.get_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        statement = (
            select(TerminalOutputChunk)
            .where(
                TerminalOutputChunk.terminal_id
                == terminal_id,
                TerminalOutputChunk.sequence
                > max(
                    0,
                    int(after_sequence),
                ),
            )
            .order_by(
                TerminalOutputChunk.sequence.asc()
            )
            .limit(
                max(
                    1,
                    min(
                        int(limit),
                        4000,
                    ),
                )
            )
        )

        async with SessionLocal() as session:
            result = await session.execute(
                statement
            )
            return list(
                result.scalars().all()
            )

    async def handle_device_message(
        self,
        *,
        device_id: str,
        message: dict[str, Any],
    ) -> bool:
        message_type = str(
            message.get("type")
            or ""
        )

        terminal_id = str(
            message.get("terminal_id")
            or ""
        ).strip()

        if (
            not message_type.startswith(
                "terminal."
            )
            or (
                not terminal_id
                and message_type
                != "terminal.snapshot"
            )
        ):
            return False

        if message_type == "terminal.started":
            await self._handle_started(
                device_id,
                terminal_id,
                message,
            )
            return True

        if message_type == "terminal.output":
            await self._handle_output(
                device_id,
                terminal_id,
                message,
            )
            return True

        if message_type == "terminal.exited":
            await self._handle_exited(
                device_id,
                terminal_id,
                message,
            )
            return True

        if message_type == "terminal.error":
            await self._mark_failed(
                terminal_id,
                str(
                    message.get("error")
                    or "Device Agent terminal runtime error."
                ),
                device_id=device_id,
            )
            await self._resolve_start_waiter(
                terminal_id
            )
            await self._resolve_exit_waiter(
                terminal_id
            )
            return True

        if message_type == "terminal.snapshot":
            await self._handle_snapshot(
                device_id,
                message,
            )
            return True

        return False

    async def _handle_started(
        self,
        device_id: str,
        terminal_id: str,
        message: dict[str, Any],
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.id
                    == terminal_id,
                    TerminalSession.device_id
                    == device_id,
                )
            )
            row = result.scalar_one_or_none()

            if (
                row is None
                or row.status
                in _FINAL_STATUSES
            ):
                return

            row.status = "running"
            row.pid = (
                int(message["pid"])
                if message.get("pid")
                is not None
                else None
            )
            row.backend = str(
                message.get("backend")
                or ""
            )[:32] or None
            row.started_at = utc_now()
            await session.commit()

        await self._resolve_start_waiter(
            terminal_id
        )

        await runtime_events.publish(
            "terminal.started",
            terminal_id=terminal_id,
            device_id=device_id,
            pid=message.get("pid"),
            backend=message.get("backend"),
        )

    async def _handle_output(
        self,
        device_id: str,
        terminal_id: str,
        message: dict[str, Any],
    ) -> None:
        try:
            agent_sequence = int(
                message.get("sequence")
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            return

        if agent_sequence <= 0:
            return

        text = str(
            message.get("data")
            or ""
        )

        if not text:
            return

        stored_text = ""
        stored_bytes = 0
        created_at = utc_now()

        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.id
                    == terminal_id,
                    TerminalSession.device_id
                    == device_id,
                )
            )
            row = result.scalar_one_or_none()

            if row is None:
                return

            if (
                agent_sequence
                <= row.last_agent_sequence
            ):
                return

            row.last_agent_sequence = (
                agent_sequence
            )

            encoded = text.encode(
                "utf-8",
                errors="replace",
            )
            remaining = max(
                0,
                settings.terminal_output_max_bytes
                - row.output_bytes,
            )

            if remaining > 0:
                stored = encoded[
                    :remaining
                ]
                stored_text = stored.decode(
                    "utf-8",
                    errors="ignore",
                )
                stored_bytes = len(
                    stored_text.encode(
                        "utf-8"
                    )
                )

                if stored_text:
                    session.add(
                        TerminalOutputChunk(
                            terminal_id=terminal_id,
                            agent_sequence=agent_sequence,
                            text=stored_text,
                            byte_count=stored_bytes,
                            created_at=created_at,
                        )
                    )
                    row.output_bytes += (
                        stored_bytes
                    )

            if len(encoded) > remaining:
                row.output_truncated = 1

            await session.commit()

        await runtime_events.publish(
            "terminal.output",
            durable=False,
            terminal_id=terminal_id,
            device_id=device_id,
            sequence=agent_sequence,
            data=text,
            replayed=bool(
                message.get("replayed")
            ),
            persisted=bool(
                stored_text
            ),
        )

    async def _handle_exited(
        self,
        device_id: str,
        terminal_id: str,
        message: dict[str, Any],
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.id
                    == terminal_id,
                    TerminalSession.device_id
                    == device_id,
                )
            )
            row = result.scalar_one_or_none()

            if row is None:
                return

            row.status = "closed"
            row.exit_code = (
                int(
                    message["exit_code"]
                )
                if message.get(
                    "exit_code"
                )
                is not None
                else None
            )
            row.completed_at = utc_now()
            await session.commit()

        await self._resolve_start_waiter(
            terminal_id
        )
        await self._resolve_exit_waiter(
            terminal_id
        )

        await runtime_events.publish(
            "terminal.closed",
            terminal_id=terminal_id,
            device_id=device_id,
            exit_code=message.get(
                "exit_code"
            ),
        )

    async def _handle_snapshot(
        self,
        device_id: str,
        message: dict[str, Any],
    ) -> None:
        sessions = message.get(
            "sessions"
        )

        if not isinstance(
            sessions,
            list,
        ):
            sessions = []

        snapshot_ids: set[str] = set()

        for item in sessions:
            if not isinstance(
                item,
                dict,
            ):
                continue

            terminal_id = str(
                item.get(
                    "terminal_id"
                )
                or ""
            ).strip()

            if not terminal_id:
                continue

            snapshot_ids.add(
                terminal_id
            )

            try:
                row = await self.get_terminal(
                    terminal_id
                )
            except LookupError:
                continue

            if row.device_id != device_id:
                continue

            snapshot_status = str(
                item.get("status")
                or ""
            )

            if (
                snapshot_status == "closed"
                and row.status
                not in _FINAL_STATUSES
            ):
                await self._handle_exited(
                    device_id,
                    terminal_id,
                    {
                        "exit_code": item.get(
                            "exit_code"
                        )
                    },
                )

            elif (
                snapshot_status == "running"
                and row.status
                in {
                    "starting",
                    "running",
                }
            ):
                await self._handle_started(
                    device_id,
                    terminal_id,
                    {
                        "pid": item.get(
                            "pid"
                        ),
                        "backend": item.get(
                            "backend"
                        ),
                    },
                )

            try:
                last_sequence = int(
                    item.get(
                        "last_sequence"
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                last_sequence = 0

            if (
                last_sequence
                > row.last_agent_sequence
            ):
                await device_connections.send(
                    device_id,
                    {
                        "type": (
                            "terminal.replay.request"
                        ),
                        "terminal_id": (
                            terminal_id
                        ),
                        "after_sequence": (
                            row.last_agent_sequence
                        ),
                    },
                )

        async with SessionLocal() as session:
            result = await session.execute(
                select(TerminalSession).where(
                    TerminalSession.device_id
                    == device_id,
                    TerminalSession.status.in_(
                        list(
                            _ACTIVE_STATUSES
                        )
                    ),
                )
            )
            active_rows = list(
                result.scalars().all()
            )

        for row in active_rows:
            if row.id not in snapshot_ids:
                await self._mark_lost(
                    row.id,
                    "Device Agent no longer tracks this terminal "
                    "after reconnect.",
                    device_id=device_id,
                )

    async def _mark_failed(
        self,
        terminal_id: str,
        error: str,
        *,
        device_id: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            statement = select(
                TerminalSession
            ).where(
                TerminalSession.id
                == terminal_id
            )

            if device_id is not None:
                statement = statement.where(
                    TerminalSession.device_id
                    == device_id
                )

            result = await session.execute(
                statement
            )
            row = result.scalar_one_or_none()

            if (
                row is None
                or row.status
                in _FINAL_STATUSES
            ):
                return

            row.status = "failed"
            row.error = error[:4000]
            row.completed_at = utc_now()
            await session.commit()

        await runtime_events.publish(
            "terminal.failed",
            terminal_id=terminal_id,
            device_id=(
                device_id
                if device_id is not None
                else row.device_id
            ),
            error=error[:1000],
        )

    async def _mark_lost(
        self,
        terminal_id: str,
        error: str,
        *,
        device_id: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            statement = select(
                TerminalSession
            ).where(
                TerminalSession.id
                == terminal_id
            )

            if device_id is not None:
                statement = statement.where(
                    TerminalSession.device_id
                    == device_id
                )

            result = await session.execute(
                statement
            )
            row = result.scalar_one_or_none()

            if (
                row is None
                or row.status
                in _FINAL_STATUSES
            ):
                return

            row.status = "lost"
            row.error = error[:4000]
            row.lost_at = utc_now()
            row.completed_at = utc_now()
            await session.commit()

        await self._resolve_start_waiter(
            terminal_id
        )
        await self._resolve_exit_waiter(
            terminal_id
        )

        await runtime_events.publish(
            "terminal.lost",
            terminal_id=terminal_id,
            device_id=(
                device_id
                if device_id is not None
                else row.device_id
            ),
            error=error[:1000],
        )

    async def _resolve_start_waiter(
        self,
        terminal_id: str,
    ) -> None:
        async with self._lock:
            future = self._start_waiters.get(
                terminal_id
            )

        if (
            future is not None
            and not future.done()
        ):
            future.set_result(
                None
            )

    async def _resolve_exit_waiter(
        self,
        terminal_id: str,
    ) -> None:
        async with self._lock:
            future = self._exit_waiters.get(
                terminal_id
            )

        if (
            future is not None
            and not future.done()
        ):
            future.set_result(
                None
            )


terminal_runtime = TerminalRuntimeService()
