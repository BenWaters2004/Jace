from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket


@dataclass(slots=True)
class DeviceConnection:
    device_id: str
    owner_user_id: str | None
    websocket: WebSocket
    connection_id: str = field(default_factory=lambda: str(uuid4()))
    connected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DeviceConnectionManager:
    """Ephemeral registry for authenticated outbound Device Agent sessions.

    Persistent identity/ownership remains in the database. A connection is
    published here only after the WebSocket token and protocol hello have both
    been accepted.
    """

    def __init__(self) -> None:
        self._connections: dict[str, DeviceConnection] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        device_id: str,
        owner_user_id: str | None,
        websocket: WebSocket,
    ) -> DeviceConnection:
        connection = DeviceConnection(
            device_id=device_id,
            owner_user_id=owner_user_id,
            websocket=websocket,
        )
        previous: DeviceConnection | None = None

        async with self._lock:
            previous = self._connections.get(device_id)
            self._connections[device_id] = connection

        if previous is not None and previous.websocket is not websocket:
            try:
                await previous.websocket.close(
                    code=4001,
                    reason="Replaced by a newer Device Agent connection.",
                )
            except Exception:
                pass

        return connection

    async def unregister(
        self,
        device_id: str,
        websocket: WebSocket | None = None,
    ) -> bool:
        async with self._lock:
            current = self._connections.get(device_id)

            if current is None:
                return False

            if websocket is not None and current.websocket is not websocket:
                return False

            self._connections.pop(device_id, None)
            return True

    async def is_connected(
        self,
        device_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        async with self._lock:
            current = self._connections.get(device_id)

            if current is None:
                return False

            if (
                owner_user_id is not None
                and current.owner_user_id != owner_user_id
            ):
                return False

            return True

    async def connected_device_ids(self) -> list[str]:
        async with self._lock:
            return sorted(self._connections)

    async def connection_id(self, device_id: str) -> str | None:
        async with self._lock:
            current = self._connections.get(device_id)
            return current.connection_id if current is not None else None

    async def send(
        self,
        device_id: str,
        message: dict[str, Any],
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        async with self._lock:
            connection = self._connections.get(device_id)

        if connection is None:
            return False

        if (
            owner_user_id is not None
            and connection.owner_user_id != owner_user_id
        ):
            return False

        try:
            async with connection.send_lock:
                await connection.websocket.send_json(message)
            return True
        except Exception:
            await self.unregister(device_id, connection.websocket)
            return False

    async def disconnect(
        self,
        device_id: str,
        *,
        code: int = 4003,
        reason: str = "Device connection closed by Jace Core.",
    ) -> bool:
        async with self._lock:
            connection = self._connections.pop(device_id, None)

        if connection is None:
            return False

        try:
            await connection.websocket.close(
                code=code,
                reason=reason[:120],
            )
        except Exception:
            pass

        return True


device_connections = DeviceConnectionManager()
