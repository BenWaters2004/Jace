from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RuntimeSubscriber:
    queue: asyncio.Queue[dict[str, Any]]


class RuntimeEventBus:
    """Small in-process event bus used by the desktop command center.

    This intentionally carries presentation/runtime events only. Persistent
    state remains authoritative in SQLite and the existing REST APIs.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._state = "offline"
        self._last_event: dict[str, Any] | None = None

    @property
    def state(self) -> str:
        return self._state

    async def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        if event_type == "jace.state.changed" and isinstance(payload.get("state"), str):
            self._state = payload["state"]

        self._sequence += 1
        event = {
            "type": event_type,
            "sequence": self._sequence,
            "timestamp": _utc_iso(),
            **payload,
        }
        self._last_event = event

        async with self._lock:
            subscribers = list(self._subscribers)

        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Presentation events are lossy by design. Drop the oldest
                # event rather than blocking chat/tool execution.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        return event

    async def subscribe(self) -> RuntimeSubscriber:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
        async with self._lock:
            self._subscribers.add(queue)
        return RuntimeSubscriber(queue=queue)

    async def unsubscribe(self, subscriber: RuntimeSubscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber.queue)

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "sequence": self._sequence,
            "last_event": self._last_event,
            "timestamp": _utc_iso(),
        }


runtime_events = RuntimeEventBus()
