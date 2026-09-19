from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import select

from jace.config import settings
from jace.database import SessionLocal
from jace.db.models import (
    Device,
    ProcessOutputChunk,
    ProcessRun,
    utc_now,
)
from jace.devices.connections import device_connections
from jace.devices.service import device_response
from jace.privacy.transform import PrivacyTransform
from jace.runtime import runtime_events


_FINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "lost",
}

_ACTIVE_STATUSES = {
    "starting",
    "running",
    "cancel_requested",
}

_ALLOWED_MODES = {
    "foreground",
    "background",
}

_ALLOWED_SHELLS = {
    "powershell",
    "cmd",
    "wsl",
    "bash",
}


def _preview_command(command: str) -> str:
    transformer = PrivacyTransform()
    return transformer.protect_text(command)[:500]


def _row_to_dict(row: ProcessRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "device_id": row.device_id,
        "mode": row.mode,
        "shell": row.shell,
        "command_preview": row.command_preview,
        "command_sha256": row.command_sha256,
        "cwd": row.cwd,
        "status": row.status,
        "pid": row.pid,
        "exit_code": row.exit_code,
        "timeout_seconds": row.timeout_seconds,
        "output_bytes": row.output_bytes,
        "output_truncated": bool(row.output_truncated),
        "last_agent_sequence": row.last_agent_sequence,
        "error": row.error,
        "project_id": row.project_id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "cancel_requested_at": row.cancel_requested_at,
        "lost_at": row.lost_at,
    }


class ProcessRuntimeService:
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

    async def start_process(
        self,
        *,
        user_id: str | None,
        device_id: str,
        shell: str,
        command: str,
        cwd: str | None,
        mode: str,
        timeout_seconds: int | None,
        project_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        scope_root: str | None = None,
        wait_for_start: bool = True,
    ) -> ProcessRun:
        shell = shell.strip().lower()
        mode = mode.strip().lower()
        command = command.strip()

        if not settings.process_runtime_enabled:
            raise PermissionError(
                "Jace process runtime is disabled."
            )

        if shell not in _ALLOWED_SHELLS:
            raise ValueError(
                f"Unsupported process shell: {shell}"
            )

        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"Unsupported process mode: {mode}"
            )

        if not command:
            raise ValueError(
                "Process command cannot be empty."
            )

        if len(command) > settings.process_command_max_chars:
            raise ValueError(
                "Process command exceeds the configured size limit."
            )

        if timeout_seconds is not None:
            timeout_seconds = max(
                1,
                min(
                    int(timeout_seconds),
                    settings.process_max_timeout_seconds,
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

            if "process.runtime" not in capabilities:
                raise PermissionError(
                    "Device Agent process execution is not enabled "
                    "on this device."
                )

            if not await device_connections.is_connected(
                device_id
            ):
                raise ConnectionError(
                    "Device is not connected."
                )

            row = ProcessRun(
                user_id=user_id,
                device_id=device_id,
                mode=mode,
                shell=shell,
                command_preview=_preview_command(
                    command
                ),
                command_sha256=hashlib.sha256(
                    command.encode("utf-8")
                ).hexdigest(),
                cwd=(
                    cwd.strip()
                    if isinstance(cwd, str)
                    and cwd.strip()
                    else None
                ),
                status="starting",
                timeout_seconds=timeout_seconds,
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
            "process.created",
            process_id=row.id,
            device_id=row.device_id,
            mode=row.mode,
            shell=row.shell,
            command_preview=row.command_preview,
            cwd=row.cwd,
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        sent = await device_connections.send(
            device_id,
            {
                "type": "process.start",
                "process_id": row.id,
                "shell": shell,
                "command": command,
                "cwd": row.cwd,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
                # JACE_4B3D_PROCESS_SCOPE_ROOT
                "scope_root": scope_root,
            },
        )

        if not sent:
            await self._mark_failed(
                row.id,
                "Device disconnected before process start.",
            )
            await self._resolve_start_waiter(
                row.id
            )
            return await self.get_process(
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
                        .process_start_ack_timeout_seconds
                    ),
                )
            except asyncio.TimeoutError:
                await self._mark_failed(
                    row.id,
                    "Device Agent did not acknowledge process "
                    "start within the configured timeout.",
                )

                await device_connections.send(
                    device_id,
                    {
                        "type": "process.terminate",
                        "process_id": row.id,
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

        return await self.get_process(
            row.id,
            user_id=user_id,
            server_mode=False,
        )

    async def terminate_process(
        self,
        process_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        force: bool = False,
    ) -> ProcessRun:
        row = await self.get_process(
            process_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status in _FINAL_STATUSES:
            return row

        async with SessionLocal() as session:
            result = await session.execute(
                select(ProcessRun).where(
                    ProcessRun.id
                    == process_id
                )
            )
            current = result.scalar_one()

            if (
                current.status
                not in _FINAL_STATUSES
            ):
                current.status = (
                    "cancel_requested"
                )
                current.cancel_requested_at = (
                    utc_now()
                )
                await session.commit()

        sent = await device_connections.send(
            row.device_id,
            {
                "type": "process.terminate",
                "process_id": row.id,
                "force": bool(force),
                "reason": "user_requested",
            },
        )

        if not sent:
            await self._mark_lost(
                row.id,
                "Device disconnected while termination "
                "was requested.",
            )

        await runtime_events.publish(
            "process.cancel_requested",
            process_id=row.id,
            device_id=row.device_id,
            force=bool(force),
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
        )

        return await self.get_process(
            process_id,
            user_id=user_id,
            server_mode=server_mode,
        )

    async def wait_for_exit(
        self,
        process_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        timeout_seconds: float,
    ) -> ProcessRun:
        row = await self.get_process(
            process_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status in _FINAL_STATUSES:
            return row

        future = (
            asyncio.get_running_loop()
            .create_future()
        )

        async with self._lock:
            self._exit_waiters[
                process_id
            ] = future

        try:
            # Re-check after waiter registration to close the race.
            row = await self.get_process(
                process_id,
                user_id=user_id,
                server_mode=server_mode,
            )

            if row.status in _FINAL_STATUSES:
                return row

            await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(
                    0.1,
                    float(timeout_seconds),
                ),
            )
        except asyncio.TimeoutError:
            pass
        finally:
            async with self._lock:
                self._exit_waiters.pop(
                    process_id,
                    None,
                )

        return await self.get_process(
            process_id,
            user_id=user_id,
            server_mode=server_mode,
        )

    async def get_process(
        self,
        process_id: str,
        *,
        user_id: str | None = None,
        server_mode: bool = False,
    ) -> ProcessRun:
        async with SessionLocal() as session:
            statement = select(
                ProcessRun
            ).where(
                ProcessRun.id == process_id
            )

            if server_mode:
                statement = statement.where(
                    ProcessRun.user_id
                    == user_id
                )

            result = await session.execute(
                statement
            )
            row = result.scalar_one_or_none()

            if row is None:
                raise LookupError(
                    "Process not found."
                )

            return row

    async def list_processes(
        self,
        *,
        user_id: str | None,
        server_mode: bool,
        device_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ProcessRun]:
        statement = (
            select(ProcessRun)
            .order_by(
                ProcessRun.created_at.desc()
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
                ProcessRun.user_id
                == user_id
            )

        if device_id:
            statement = statement.where(
                ProcessRun.device_id
                == device_id
            )

        if status:
            statement = statement.where(
                ProcessRun.status
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
        process_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[ProcessOutputChunk]:
        await self.get_process(
            process_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        statement = (
            select(ProcessOutputChunk)
            .where(
                ProcessOutputChunk.process_id
                == process_id,
                ProcessOutputChunk.sequence
                > max(
                    0,
                    int(after_sequence),
                ),
            )
            .order_by(
                ProcessOutputChunk.sequence.asc()
            )
            .limit(
                max(
                    1,
                    min(
                        int(limit),
                        2000,
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

        process_id = str(
            message.get("process_id")
            or ""
        ).strip()

        if (
            not message_type.startswith(
                "process."
            )
            or not process_id
            and message_type
            != "process.snapshot"
        ):
            return False

        if message_type == "process.started":
            await self._handle_started(
                device_id,
                process_id,
                message,
            )
            return True

        if message_type == "process.output":
            await self._handle_output(
                device_id,
                process_id,
                message,
            )
            return True

        if message_type == "process.exited":
            await self._handle_exited(
                device_id,
                process_id,
                message,
            )
            return True

        if message_type == "process.error":
            await self._handle_error(
                device_id,
                process_id,
                message,
            )
            return True

        if message_type == "process.snapshot":
            await self._handle_snapshot(
                device_id,
                message,
            )
            return True

        return False

    async def _handle_started(
        self,
        device_id: str,
        process_id: str,
        message: dict[str, Any],
    ) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ProcessRun).where(
                    ProcessRun.id
                    == process_id,
                    ProcessRun.device_id
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
            row.started_at = utc_now()
            await session.commit()

        await self._resolve_start_waiter(
            process_id
        )

        await runtime_events.publish(
            "process.started",
            process_id=process_id,
            device_id=device_id,
            pid=message.get("pid"),
        )

    async def _handle_output(
        self,
        device_id: str,
        process_id: str,
        message: dict[str, Any],
    ) -> None:
        try:
            agent_sequence = int(
                message.get("sequence")
                or 0
            )
        except (TypeError, ValueError):
            return

        if agent_sequence <= 0:
            return

        stream = str(
            message.get("stream")
            or "stdout"
        )[:16]

        if stream not in {
            "stdout",
            "stderr",
            "system",
        }:
            stream = "system"

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
                select(ProcessRun).where(
                    ProcessRun.id
                    == process_id,
                    ProcessRun.device_id
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
                settings.process_output_max_bytes
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
                        ProcessOutputChunk(
                            process_id=process_id,
                            agent_sequence=(
                                agent_sequence
                            ),
                            stream=stream,
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

        # Output is retained in the dedicated process-output table. Keep the
        # shared runtime-event ledger small by making the live delta transient.
        await runtime_events.publish(
            "process.output",
            durable=False,
            process_id=process_id,
            device_id=device_id,
            sequence=agent_sequence,
            stream=stream,
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
        process_id: str,
        message: dict[str, Any],
    ) -> None:
        status = str(
            message.get("status")
            or ""
        )

        if status not in {
            "completed",
            "failed",
            "cancelled",
            "timed_out",
        }:
            status = "failed"

        async with SessionLocal() as session:
            result = await session.execute(
                select(ProcessRun).where(
                    ProcessRun.id
                    == process_id,
                    ProcessRun.device_id
                    == device_id,
                )
            )
            row = result.scalar_one_or_none()

            if row is None:
                return

            row.status = status
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

            error = message.get(
                "error"
            )

            if error is not None:
                row.error = str(
                    error
                )[:4000]

            await session.commit()

        await self._resolve_start_waiter(
            process_id
        )
        await self._resolve_exit_waiter(
            process_id
        )

        await runtime_events.publish(
            f"process.{status}",
            process_id=process_id,
            device_id=device_id,
            exit_code=message.get(
                "exit_code"
            ),
            error=message.get(
                "error"
            ),
        )

    async def _handle_error(
        self,
        device_id: str,
        process_id: str,
        message: dict[str, Any],
    ) -> None:
        await self._mark_failed(
            process_id,
            str(
                message.get(
                    "error"
                )
                or "Device Agent process runtime error."
            ),
            device_id=device_id,
        )

        await self._resolve_start_waiter(
            process_id
        )
        await self._resolve_exit_waiter(
            process_id
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

            process_id = str(
                item.get(
                    "process_id"
                )
                or ""
            ).strip()

            if not process_id:
                continue

            snapshot_ids.add(
                process_id
            )

            try:
                row = await self.get_process(
                    process_id
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
                snapshot_status
                in _FINAL_STATUSES
                and row.status
                not in _FINAL_STATUSES
            ):
                await self._handle_exited(
                    device_id,
                    process_id,
                    {
                        "status": (
                            snapshot_status
                        ),
                        "exit_code": item.get(
                            "exit_code"
                        ),
                    },
                )

            elif (
                snapshot_status
                == "running"
                and row.status
                in {
                    "starting",
                    "running",
                }
            ):
                await self._handle_started(
                    device_id,
                    process_id,
                    {
                        "pid": item.get(
                            "pid"
                        )
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
                            "process.replay.request"
                        ),
                        "process_id": (
                            process_id
                        ),
                        "after_sequence": (
                            row.last_agent_sequence
                        ),
                    },
                )

        async with SessionLocal() as session:
            result = await session.execute(
                select(ProcessRun).where(
                    ProcessRun.device_id
                    == device_id,
                    ProcessRun.status.in_(
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
                    "Device Agent no longer tracks this process "
                    "after reconnect.",
                    device_id=device_id,
                )

    async def _mark_failed(
        self,
        process_id: str,
        error: str,
        *,
        device_id: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            statement = select(
                ProcessRun
            ).where(
                ProcessRun.id
                == process_id
            )

            if device_id is not None:
                statement = statement.where(
                    ProcessRun.device_id
                    == device_id
                )

            result = await session.execute(
                statement
            )
            row = result.scalar_one_or_none()

            if row is None:
                return

            if row.status in _FINAL_STATUSES:
                return

            row.status = "failed"
            row.error = error[:4000]
            row.completed_at = utc_now()
            await session.commit()

        await runtime_events.publish(
            "process.failed",
            process_id=process_id,
            device_id=(
                device_id
                if device_id is not None
                else row.device_id
            ),
            error=error[:1000],
        )

    async def _mark_lost(
        self,
        process_id: str,
        error: str,
        *,
        device_id: str | None = None,
    ) -> None:
        async with SessionLocal() as session:
            statement = select(
                ProcessRun
            ).where(
                ProcessRun.id
                == process_id
            )

            if device_id is not None:
                statement = statement.where(
                    ProcessRun.device_id
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
            process_id
        )
        await self._resolve_exit_waiter(
            process_id
        )

        await runtime_events.publish(
            "process.lost",
            process_id=process_id,
            device_id=(
                device_id
                if device_id is not None
                else row.device_id
            ),
            error=error[:1000],
        )

    async def _resolve_start_waiter(
        self,
        process_id: str,
    ) -> None:
        async with self._lock:
            future = self._start_waiters.get(
                process_id
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
        process_id: str,
    ) -> None:
        async with self._lock:
            future = self._exit_waiters.get(
                process_id
            )

        if (
            future is not None
            and not future.done()
        ):
            future.set_result(
                None
            )


process_runtime = ProcessRuntimeService()
