from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from jace.capabilities.device_policy import is_device_capability_allowed
from jace.database import SessionLocal
from jace.db.models import Device, DeviceCapabilityRequest, utc_now
from jace.devices.connections import device_connections
from jace.devices.service import device_response
from jace.runtime import runtime_events


_FINAL = {"completed", "failed", "timed_out", "cancelled"}


@dataclass(slots=True)
class PendingDeviceCapability:
    request_id: str
    device_id: str
    future: asyncio.Future[dict[str, Any]]


class DeviceCapabilityBroker:
    def __init__(self) -> None:
        self._pending: dict[str, PendingDeviceCapability] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        *,
        user_id: str | None,
        device_id: str,
        capability: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
        project_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> DeviceCapabilityRequest:
        if not is_device_capability_allowed(capability):
            raise PermissionError(
                f"Device capability '{capability}' is not enabled by "
                "the 4B.S6 read-only policy."
            )

        async with SessionLocal() as session:
            if idempotency_key:
                result = await session.execute(
                    select(DeviceCapabilityRequest).where(
                        DeviceCapabilityRequest.idempotency_key == idempotency_key
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    return existing

            result = await session.execute(
                select(Device).where(Device.id == device_id)
            )
            device = result.scalar_one_or_none()

            if device is None:
                raise LookupError("Device not found.")
            if not device.is_active or device.revoked_at is not None:
                raise PermissionError("Device is revoked.")

            if capability not in set(device_response(device).capabilities):
                raise ValueError(
                    f"Device does not advertise capability '{capability}'."
                )

            if not await device_connections.is_connected(device_id):
                raise ConnectionError("Device is not connected.")

            row = DeviceCapabilityRequest(
                user_id=user_id,
                device_id=device_id,
                capability=capability,
                parameters_json=json.dumps(parameters, ensure_ascii=False),
                approval_json=json.dumps(
                    {
                        "decision": "allow",
                        "policy": "4B.S6.read_only_low_risk",
                    }
                ),
                status="pending",
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
                timeout_seconds=timeout_seconds,
                requested_at=utc_now(),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

        future = asyncio.get_running_loop().create_future()

        async with self._lock:
            self._pending[row.id] = PendingDeviceCapability(
                request_id=row.id,
                device_id=device_id,
                future=future,
            )

        await runtime_events.publish(
            "device.capability.requested",
            request_id=row.id,
            device_id=device_id,
            capability=capability,
        )

        sent = await device_connections.send(
            device_id,
            {
                "type": "capability.request",
                "request_id": row.id,
                "capability": capability,
                "parameters": parameters,
                "timeout_seconds": timeout_seconds,
                "context": {
                    "project_id": project_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                },
            },
        )

        if not sent:
            await self._finalise(
                row.id,
                status="failed",
                error="Device disconnected before request delivery.",
            )
            await self._remove_pending(row.id)
            return await self.get_request(row.id)

        await self._mark_running(row.id)

        try:
            await asyncio.wait_for(
                asyncio.shield(future),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            await device_connections.send(
                device_id,
                {
                    "type": "capability.cancel",
                    "request_id": row.id,
                    "reason": "core_timeout",
                },
            )
            await self._finalise(
                row.id,
                status="timed_out",
                error=f"Capability exceeded {timeout_seconds} second timeout.",
            )
        finally:
            await self._remove_pending(row.id)

        return await self.get_request(row.id)

    async def resolve_result(
        self,
        *,
        device_id: str,
        message: dict[str, Any],
    ) -> bool:
        request_id = str(message.get("request_id") or "").strip()
        if not request_id:
            return False

        async with self._lock:
            pending = self._pending.get(request_id)

        if pending is None or pending.device_id != device_id:
            return False

        status = str(message.get("status") or "failed")
        if status not in {"completed", "failed", "cancelled"}:
            status = "failed"

        evidence = message.get("evidence")
        error = message.get("error")

        await self._finalise(
            request_id,
            status=status,
            result=message.get("result"),
            evidence=evidence if isinstance(evidence, dict) else None,
            error=str(error) if error is not None else None,
            cancelled=status == "cancelled",
        )

        await runtime_events.publish(
            f"device.capability.{status}",
            request_id=request_id,
            device_id=device_id,
        )

        if not pending.future.done():
            pending.future.set_result(message)

        return True

    async def cancel(
        self,
        request_id: str,
        *,
        user_id: str | None,
        server_mode: bool,
    ) -> DeviceCapabilityRequest:
        row = await self.get_request(
            request_id,
            user_id=user_id,
            server_mode=server_mode,
        )

        if row.status in _FINAL:
            return row

        await device_connections.send(
            row.device_id,
            {
                "type": "capability.cancel",
                "request_id": row.id,
                "reason": "user_cancelled",
            },
        )

        await self._finalise(
            row.id,
            status="cancelled",
            error="Capability request was cancelled.",
            cancelled=True,
        )

        async with self._lock:
            pending = self._pending.get(row.id)

        if pending is not None and not pending.future.done():
            pending.future.set_result(
                {
                    "type": "capability.result",
                    "request_id": row.id,
                    "status": "cancelled",
                }
            )

        return await self.get_request(
            row.id,
            user_id=user_id,
            server_mode=server_mode,
        )

    async def get_request(
        self,
        request_id: str,
        *,
        user_id: str | None = None,
        server_mode: bool = False,
    ) -> DeviceCapabilityRequest:
        async with SessionLocal() as session:
            statement = select(DeviceCapabilityRequest).where(
                DeviceCapabilityRequest.id == request_id
            )
            if server_mode:
                statement = statement.where(
                    DeviceCapabilityRequest.user_id == user_id
                )

            result = await session.execute(statement)
            row = result.scalar_one_or_none()

            if row is None:
                raise LookupError("Device capability request not found.")

            return row

    async def _mark_running(self, request_id: str) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(DeviceCapabilityRequest).where(
                    DeviceCapabilityRequest.id == request_id
                )
            )
            row = result.scalar_one()
            row.status = "running"
            row.started_at = utc_now()
            await session.commit()

    async def _finalise(
        self,
        request_id: str,
        *,
        status: str,
        result: Any | None = None,
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        async with SessionLocal() as session:
            query = await session.execute(
                select(DeviceCapabilityRequest).where(
                    DeviceCapabilityRequest.id == request_id
                )
            )
            row = query.scalar_one_or_none()

            if row is None or row.status in _FINAL:
                return

            row.status = status
            row.result_json = (
                json.dumps(result, ensure_ascii=False)
                if result is not None
                else None
            )
            row.evidence_json = (
                json.dumps(evidence, ensure_ascii=False)
                if evidence is not None
                else None
            )
            row.error = error
            row.completed_at = utc_now()
            if cancelled:
                row.cancelled_at = utc_now()
            await session.commit()

    async def _remove_pending(self, request_id: str) -> None:
        async with self._lock:
            self._pending.pop(request_id, None)


device_capability_broker = DeviceCapabilityBroker()
