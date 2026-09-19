from __future__ import annotations

import asyncio
import logging
from typing import Any

from jace.config import settings
from jace.runtime.events import RuntimeEventBus, RuntimeSubscriber
from jace.runtime.store import (
    append_runtime_event,
    latest_runtime_event,
    latest_state_event,
    prune_runtime_events,
    replay_runtime_events,
)


logger = logging.getLogger("uvicorn.error")


class DurableRuntimeEventBus(RuntimeEventBus):
    """Durable ledger + low-latency in-process fan-out."""

    def __init__(self) -> None:
        super().__init__()
        self._initialised = False
        self._transient_counter = 0

    async def initialize(self) -> None:
        if self._initialised:
            return

        if settings.runtime_events_persist:
            try:
                await prune_runtime_events()

                latest = await latest_runtime_event()

                if latest is not None:
                    self._sequence = int(
                        latest.get("sequence")
                        or 0
                    )
                    self._last_event = latest

                state_event = await latest_state_event()

                if (
                    state_event is not None
                    and isinstance(
                        state_event.get("state"),
                        str,
                    )
                ):
                    self._state = state_event[
                        "state"
                    ]
            except Exception:
                logger.exception(
                    "Could not initialise durable runtime-event state."
                )

        self._initialised = True


    async def subscribe(self) -> RuntimeSubscriber:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max(
                32,
                int(settings.runtime_event_subscriber_queue),
            )
        )

        async with self._lock:
            self._subscribers.add(queue)

        return RuntimeSubscriber(
            queue=queue
        )

    async def publish(
        self,
        event_type: str,
        *,
        durable: bool = True,
        **payload: Any,
    ) -> dict[str, Any]:
        if (
            event_type == "jace.state.changed"
            and isinstance(
                payload.get("state"),
                str,
            )
        ):
            self._state = payload["state"]

        event: dict[str, Any] | None = None

        if (
            durable
            and settings.runtime_events_persist
        ):
            try:
                event = await append_runtime_event(
                    event_type,
                    payload,
                )
                self._sequence = max(
                    self._sequence,
                    int(
                        event.get("sequence")
                        or 0
                    ),
                )
            except Exception:
                logger.exception(
                    "Could not persist runtime event %s.",
                    event_type,
                )

        if event is None:
            # A persistence outage must not crash the operation which
            # produced the event. Mark it transient and do not advance the
            # durable sequence cursor.
            self._transient_counter += 1

            from datetime import datetime, timezone
            from uuid import uuid4

            event = {
                "type": event_type,
                "event_id": str(uuid4()),
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                "durable": False,
                "transient_sequence": (
                    self._transient_counter
                ),
                **payload,
            }

        self._last_event = event

        async with self._lock:
            subscribers = list(
                self._subscribers
            )

        for queue in subscribers:
            try:
                queue.put_nowait(
                    event
                )
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                try:
                    queue.put_nowait(
                        event
                    )
                except asyncio.QueueFull:
                    pass

        return event

    async def replay(
        self,
        *,
        after_sequence: int = 0,
        through_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not settings.runtime_events_persist:
            return []

        return await replay_runtime_events(
            after_sequence=after_sequence,
            through_sequence=through_sequence,
            limit=limit,
        )

    def snapshot(self) -> dict[str, Any]:
        snapshot = super().snapshot()

        snapshot.update(
            {
                "durable_sequence": (
                    self._sequence
                ),
                "persistence_enabled": (
                    settings.runtime_events_persist
                ),
                "retention_days": (
                    settings.runtime_event_retention_days
                ),
            }
        )

        return snapshot
