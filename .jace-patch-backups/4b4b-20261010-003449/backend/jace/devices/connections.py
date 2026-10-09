from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class DeviceConnectionManager:
    """In-memory registry of live outbound Device Agent WebSocket connections.

    Persistent device identity remains in the database. This registry only
    represents current transport availability and is intentionally ephemeral.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, device_id: str, websocket: WebSocket) -> None:
        previous: WebSocket | None = None

        async with self._lock:
            previous = self._connections.get(device_id)
            self._connections[device_id] = websocket

        if previous is not None and previous is not websocket:
            try:
                await previous.close(
                    code=4001,
                    reason="Replaced by a newer Device Agent connection.",
                )
            except Exception:
                pass

    async def unregister(
        self,
        device_id: str,
        websocket: WebSocket | None = None,
    ) -> bool:
        async with self._lock:
            current = self._connections.get(device_id)

            if current is None:
                return False

            if websocket is not None and current is not websocket:
                return False

            self._connections.pop(device_id, None)
            return True

    async def is_connected(self, device_id: str) -> bool:
        async with self._lock:
            return device_id in self._connections

    async def connected_device_ids(self) -> list[str]:
        async with self._lock:
            return sorted(self._connections)

    async def send(
        self,
        device_id: str,
        message: dict[str, Any],
    ) -> bool:
        async with self._lock:
            websocket = self._connections.get(device_id)

        if websocket is None:
            return False

        try:
            await websocket.send_json(message)
            return True
        except Exception:
            await self.unregister(device_id, websocket)
            return False


device_connections = DeviceConnectionManager()
