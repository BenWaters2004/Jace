from __future__ import annotations

import asyncio
import itertools
import logging

from jace.agents.config import agent_settings
from jace.agents.runner import AgentTaskCancelled, execute_agent_task
from jace.agents.service import (
    get_task,
    recover_incomplete_tasks,
    request_cancel,
    update_task_state,
)
from jace.database import SessionLocal
from jace.runtime import runtime_events

logger = logging.getLogger("uvicorn.error")


class AgentManager:
    """
    Small local worker pool.

    Tasks are persistent in SQLite. The asyncio queue is only the in-process
    dispatch mechanism, so a Jace restart can safely recover unfinished work.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] = (
            asyncio.PriorityQueue()
        )
        self._sequence = itertools.count()
        self._workers: list[asyncio.Task] = []
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._queued_ids: set[str] = set()
        self._running_ids: set[str] = set()
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    @property
    def active_count(self) -> int:
        return len(self._running_ids)

    @property
    def queued_count(self) -> int:
        return len(self._queued_ids)

    async def start(self) -> None:
        if self._running or not agent_settings.enabled:
            return

        self._running = True

        async with SessionLocal() as session:
            recovered = await recover_incomplete_tasks(session)

        self._workers = [
            asyncio.create_task(
                self._worker(index),
                name=f"jace-agent-worker-{index + 1}",
            )
            for index in range(agent_settings.max_parallel_tasks)
        ]

        for task in recovered:
            await self.enqueue(task.id, priority=task.priority)

        logger.info(
            "Jace agent manager started with %s worker(s); recovered %s task(s).",
            len(self._workers),
            len(recovered),
        )

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False

        for event in self._cancel_events.values():
            event.set()

        for worker in self._workers:
            worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        self._running_ids.clear()
        self._queued_ids.clear()
        self._cancel_events.clear()

        logger.info("Jace agent manager stopped.")

    async def enqueue(self, task_id: str, *, priority: int | None = None) -> bool:
        if not self._running:
            return False

        async with self._lock:
            if task_id in self._queued_ids or task_id in self._running_ids:
                return False

            if priority is None:
                async with SessionLocal() as session:
                    task = await get_task(session, task_id)
                    if task is None or task.status != "queued":
                        return False
                    priority = task.priority

            self._queued_ids.add(task_id)
            await self._queue.put((-int(priority), next(self._sequence), task_id))
            self._cancel_events.setdefault(task_id, asyncio.Event())

        await runtime_events.publish(
            "agent.task.queued",
            task_id=task_id,
        )
        return True

    async def cancel(self, task_id: str) -> bool:
        async with SessionLocal() as session:
            task = await get_task(session, task_id)
            if task is None:
                return False
            task = await request_cancel(session, task)

        event = self._cancel_events.setdefault(task_id, asyncio.Event())
        event.set()

        await runtime_events.publish(
            "agent.task.changed",
            task_id=task.id,
            agent_id=task.agent_id,
            status=task.status,
            progress=task.progress,
            progress_message=task.progress_message,
            conversation_id=task.conversation_id,
        )
        return True

    async def _worker(self, worker_index: int) -> None:
        while self._running:
            try:
                _, _, task_id = await self._queue.get()
            except asyncio.CancelledError:
                break

            self._queued_ids.discard(task_id)
            self._running_ids.add(task_id)
            cancel_event = self._cancel_events.setdefault(task_id, asyncio.Event())

            try:
                async with SessionLocal() as session:
                    task = await get_task(session, task_id)

                if task is None:
                    continue

                if task.cancel_requested or task.status == "cancelled":
                    continue

                try:
                    await asyncio.wait_for(
                        execute_agent_task(task_id, cancel_event=cancel_event),
                        timeout=agent_settings.task_timeout_seconds,
                    )

                except AgentTaskCancelled:
                    async with SessionLocal() as session:
                        current = await get_task(session, task_id)
                        if current is not None and current.status not in {
                            "completed",
                            "failed",
                            "cancelled",
                        }:
                            current = await update_task_state(
                                session,
                                current,
                                status="cancelled",
                                progress_message="Cancelled",
                                completed=True,
                                event_type="cancelled",
                                event_message="Background agent task cancelled.",
                            )
                            await runtime_events.publish(
                                "agent.task.changed",
                                task_id=current.id,
                                agent_id=current.agent_id,
                                status=current.status,
                                progress=current.progress,
                                progress_message=current.progress_message,
                                conversation_id=current.conversation_id,
                            )

                except asyncio.TimeoutError:
                    await self._fail_task(
                        task_id,
                        (
                            "Background agent exceeded its "
                            f"{agent_settings.task_timeout_seconds}s timeout."
                        ),
                    )

                except asyncio.CancelledError:
                    if not self._running:
                        break
                    raise

                except Exception as exc:
                    await self._fail_task(task_id, str(exc))

            finally:
                self._running_ids.discard(task_id)
                self._cancel_events.pop(task_id, None)
                self._queue.task_done()

    async def _fail_task(self, task_id: str, error: str) -> None:
        async with SessionLocal() as session:
            task = await get_task(session, task_id)
            if task is None or task.status in {"completed", "cancelled"}:
                return

            task = await update_task_state(
                session,
                task,
                status="failed",
                progress_message="Failed",
                error=error,
                completed=True,
                event_type="failed",
                event_message="Background agent task failed.",
                event_data_value={"error": error[:2000]},
            )

        await runtime_events.publish(
            "agent.task.failed",
            task_id=task.id,
            agent_id=task.agent_id,
            status=task.status,
            error=error,
            conversation_id=task.conversation_id,
        )


agent_manager = AgentManager()


async def start_agent_manager() -> None:
    await agent_manager.start()


async def stop_agent_manager() -> None:
    await agent_manager.stop()
