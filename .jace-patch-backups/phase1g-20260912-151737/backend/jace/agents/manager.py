from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from jace.agents.config import agent_settings
from jace.agents.runner import AgentTaskCancelled, execute_agent_task
from jace.agents.service import (
    get_task,
    list_tasks,
    recover_incomplete_tasks,
    recover_task_after_worker_crash,
    request_cancel,
    update_task_state,
)
from jace.database import SessionLocal
from jace.runtime import runtime_events

logger = logging.getLogger("uvicorn.error")


AgentWorkerExecutionState = Literal["idle", "running", "recovering", "offline"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class QueuedDispatch:
    task_id: str
    priority: int
    sequence: int
    generation: int


@dataclass(slots=True)
class AgentWorkerRuntime:
    """Live state for one real asyncio executor in the background-agent pool."""

    id: str
    index: int
    state: AgentWorkerExecutionState
    task_id: str | None
    agent_id: str | None
    task_title: str | None
    dispatch_generation: int | None
    assigned_at: datetime | None
    updated_at: datetime
    restart_count: int = 0
    last_error: str | None = None
    last_exit_at: datetime | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "index": self.index,
            "state": self.state,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "task_title": self.task_title,
            "dispatch_generation": self.dispatch_generation,
            "assigned_at": self.assigned_at,
            "updated_at": self.updated_at,
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "last_exit_at": self.last_exit_at,
        }


class AgentManager:
    """
    Local persistent background-agent worker pool.

    SQLite is authoritative for task state/history. The asyncio priority queue
    is only an in-process dispatch mechanism and is rebuilt from persistent task
    state whenever the manager starts.

    A logical specialist (Research, Code, Files, Analyst, General) is not the
    same thing as an executor slot. The worker runtime map exposes the real
    asyncio executors so the Agent Office can truthfully show what is actually
    running rather than manufacturing visual workers from queued work.

    Queue entries carry a monotonically increasing dispatch generation. This is
    important because asyncio.PriorityQueue cannot remove an arbitrary queued
    item. Cancelling a queued task therefore invalidates that generation; any
    stale item left in the priority queue becomes harmless. Retrying the same
    task receives a fresh generation and can never collide with the stale item.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, str, int]] = (
            asyncio.PriorityQueue()
        )
        self._sequence = itertools.count()
        self._workers: list[asyncio.Task] = []
        self._supervisor_task: asyncio.Task | None = None
        self._worker_states: dict[int, AgentWorkerRuntime] = {}
        self._queued_dispatches: dict[str, QueuedDispatch] = {}
        self._dispatch_generation: dict[str, int] = {}
        self._active_generation: dict[str, int] = {}
        self._cancel_events: dict[tuple[str, int], asyncio.Event] = {}
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

    def worker_snapshots(self) -> list[dict[str, object]]:
        """Return detached snapshots so API callers cannot mutate manager state."""
        return [
            self._worker_states[index].snapshot()
            for index in sorted(self._worker_states)
        ]

    def executor_for_task(self, task_id: str) -> str | None:
        for runtime in self._worker_states.values():
            if runtime.state == "running" and runtime.task_id == task_id:
                return runtime.id
        return None

    def queue_position(self, task_id: str) -> int | None:
        """Return a 1-based position among currently valid queued dispatches."""
        ordered = sorted(
            self._queued_dispatches.values(),
            key=lambda dispatch: (-dispatch.priority, dispatch.sequence),
        )
        for index, dispatch in enumerate(ordered, start=1):
            if dispatch.task_id == task_id:
                return index
        return None

    def _next_generation(self, task_id: str) -> int:
        generation = self._dispatch_generation.get(task_id, 0) + 1
        self._dispatch_generation[task_id] = generation
        return generation

    async def _publish_queue_changed(
        self,
        *,
        reason: str,
        task_id: str | None = None,
    ) -> None:
        await runtime_events.publish(
            "agent.queue.changed",
            reason=reason,
            task_id=task_id,
            queued_count=self.queued_count,
            active_count=self.active_count,
        )

    async def _set_worker_state(
        self,
        worker_index: int,
        *,
        state: AgentWorkerExecutionState,
        task_id: str | None = None,
        agent_id: str | None = None,
        task_title: str | None = None,
        dispatch_generation: int | None = None,
    ) -> None:
        runtime = self._worker_states.get(worker_index)
        if runtime is None:
            return

        now = _utc_now()
        runtime.state = state
        runtime.task_id = task_id
        runtime.agent_id = agent_id
        runtime.task_title = task_title
        runtime.dispatch_generation = dispatch_generation
        runtime.assigned_at = now if state == "running" else None
        runtime.updated_at = now

        # Runtime events are presentation hints. Reconnects always reconcile
        # against /agents/workers plus the persistent task REST endpoints.
        await runtime_events.publish(
            "agent.worker.changed",
            worker_id=runtime.id,
            worker_index=runtime.index,
            worker_state=runtime.state,
            task_id=runtime.task_id,
            agent_id=runtime.agent_id,
            task_title=runtime.task_title,
            dispatch_generation=runtime.dispatch_generation,
            assigned_at=(
                runtime.assigned_at.isoformat()
                if runtime.assigned_at is not None
                else None
            ),
            restart_count=runtime.restart_count,
            last_error=runtime.last_error,
            last_exit_at=(
                runtime.last_exit_at.isoformat()
                if runtime.last_exit_at is not None
                else None
            ),
        )

    async def _release_worker_if_owned(
        self,
        worker_index: int,
        *,
        task_id: str,
        generation: int,
    ) -> None:
        runtime = self._worker_states.get(worker_index)
        if runtime is None:
            return
        if runtime.task_id != task_id or runtime.dispatch_generation != generation:
            return
        await self._set_worker_state(worker_index, state="idle")

    def _spawn_worker(self, worker_index: int) -> asyncio.Task:
        return asyncio.create_task(
            self._worker(worker_index),
            name=f"jace-agent-worker-{worker_index + 1}",
        )

    async def _recover_worker_exit(self, worker_index: int, error: str) -> None:
        runtime = self._worker_states.get(worker_index)
        if runtime is None:
            return

        worker_id = runtime.id
        task_id = runtime.task_id
        generation = runtime.dispatch_generation
        runtime.restart_count += 1
        runtime.last_error = error[:2000]
        runtime.last_exit_at = _utc_now()

        await runtime_events.publish(
            "agent.worker.crashed",
            worker_id=worker_id,
            worker_index=runtime.index,
            task_id=task_id,
            agent_id=runtime.agent_id,
            dispatch_generation=generation,
            restart_count=runtime.restart_count,
            error=runtime.last_error,
        )

        recovered_task = None
        if task_id is not None and generation is not None:
            # The dead coroutine cannot execute this generation again. Release
            # its process-local ownership before preparing a fresh dispatch.
            await self._release_dispatch(task_id, generation)
            async with SessionLocal() as session:
                current = await get_task(session, task_id)
                if current is not None:
                    recovered_task = await recover_task_after_worker_crash(
                        session,
                        current,
                        worker_id=worker_id,
                        error=error,
                    )

        await self._set_worker_state(worker_index, state="recovering")

        if recovered_task is not None:
            await runtime_events.publish(
                "agent.task.changed",
                task_id=recovered_task.id,
                agent_id=recovered_task.agent_id,
                status=recovered_task.status,
                progress=recovered_task.progress,
                progress_message=recovered_task.progress_message,
                conversation_id=recovered_task.conversation_id,
            )
            if recovered_task.status == "queued":
                accepted = await self.enqueue_when_released(
                    recovered_task.id,
                    priority=recovered_task.priority,
                    timeout_seconds=1.5,
                )
                if not accepted:
                    logger.error(
                        "Could not redispatch task %s after %s recovered.",
                        recovered_task.id,
                        worker_id,
                    )

    async def _reconcile_orphaned_queued_tasks(self) -> None:
        """Re-dispatch persistent queued tasks which lost only their in-memory slot."""
        async with SessionLocal() as session:
            queued = await list_tasks(session, status="queued", limit=500)
        for task in queued:
            if task.cancel_requested:
                continue
            if task.id in self._queued_ids or task.id in self._running_ids:
                continue
            await self.enqueue(task.id, priority=task.priority)

    async def _supervise_workers(self) -> None:
        """Restart executor coroutines that exit outside normal manager shutdown."""
        while self._running:
            await asyncio.sleep(0.35)
            for worker_index, worker in enumerate(tuple(self._workers)):
                if not self._running:
                    return
                if not worker.done():
                    continue

                if worker.cancelled():
                    error = "Executor coroutine was cancelled unexpectedly."
                else:
                    try:
                        exception = worker.exception()
                    except asyncio.CancelledError:
                        exception = None
                    error = (
                        f"{type(exception).__name__}: {exception}"
                        if exception is not None
                        else "Executor coroutine exited unexpectedly."
                    )

                logger.error(
                    "Agent executor worker-%s exited unexpectedly: %s",
                    worker_index + 1,
                    error,
                )
                try:
                    await self._recover_worker_exit(worker_index, error)
                except Exception as recovery_error:
                    logger.exception(
                        "Failed to recover agent executor worker-%s: %s",
                        worker_index + 1,
                        recovery_error,
                    )
                    runtime = self._worker_states.get(worker_index)
                    if runtime is not None:
                        runtime.last_error = str(recovery_error)[:2000]
                        runtime.last_exit_at = _utc_now()
                        await self._set_worker_state(worker_index, state="offline")

                if not self._running:
                    return
                runtime = self._worker_states.get(worker_index)
                restart_count = runtime.restart_count if runtime is not None else 1
                await asyncio.sleep(min(2.0, 0.20 * (2 ** min(restart_count - 1, 3))))
                if not self._running:
                    return
                self._workers[worker_index] = self._spawn_worker(worker_index)
                await self._set_worker_state(worker_index, state="idle")
                await self._reconcile_orphaned_queued_tasks()

    def _reset_dispatch_state(self) -> None:
        """Drop all process-local dispatch state before a manager start."""
        self._queue = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._queued_dispatches.clear()
        self._dispatch_generation.clear()
        self._active_generation.clear()
        self._cancel_events.clear()
        self._queued_ids.clear()
        self._running_ids.clear()

    async def start(self) -> None:
        if self._running or not agent_settings.enabled:
            return

        # A stop/start inside the same backend process must not retain stale
        # PriorityQueue entries from the previous worker pool.
        self._reset_dispatch_state()
        self._running = True

        async with SessionLocal() as session:
            recovered = await recover_incomplete_tasks(session)

        now = _utc_now()
        self._worker_states = {
            index: AgentWorkerRuntime(
                id=f"worker-{index + 1}",
                index=index + 1,
                state="idle",
                task_id=None,
                agent_id=None,
                task_title=None,
                dispatch_generation=None,
                assigned_at=None,
                updated_at=now,
            )
            for index in range(agent_settings.max_parallel_tasks)
        }
        self._workers = [
            self._spawn_worker(index)
            for index in range(agent_settings.max_parallel_tasks)
        ]
        self._supervisor_task = asyncio.create_task(
            self._supervise_workers(),
            name="jace-agent-worker-supervisor",
        )

        for task in recovered:
            await self.enqueue(task.id, priority=task.priority)

        # Import lazily to avoid a manager <-> director module cycle.
        from jace.agents.director import resume_director_workflows

        resumed_directors = await resume_director_workflows()
        logger.info(
            "Jace agent manager started with %s worker(s); recovered %s task(s); "
            "resumed %s Director workflow(s).",
            len(self._workers),
            len(recovered),
            resumed_directors,
        )

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False

        from jace.agents.director import stop_director_workflows

        await stop_director_workflows()

        for event in self._cancel_events.values():
            event.set()

        if self._supervisor_task is not None:
            self._supervisor_task.cancel()
            await asyncio.gather(self._supervisor_task, return_exceptions=True)
            self._supervisor_task = None

        for worker in self._workers:
            worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        self._worker_states.clear()
        self._queued_dispatches.clear()
        self._active_generation.clear()
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

            # Always re-read the persistent task, even when a caller supplied a
            # priority. That prevents a cancel/enqueue race from dispatching a
            # task which is no longer actually queued in SQLite.
            async with SessionLocal() as session:
                task = await get_task(session, task_id)
                if task is None or task.status != "queued" or task.cancel_requested:
                    return False

            resolved_priority = int(task.priority if priority is None else priority)
            generation = self._next_generation(task_id)
            sequence = next(self._sequence)
            dispatch = QueuedDispatch(
                task_id=task_id,
                priority=resolved_priority,
                sequence=sequence,
                generation=generation,
            )

            self._queued_dispatches[task_id] = dispatch
            self._queued_ids.add(task_id)
            self._cancel_events[(task_id, generation)] = asyncio.Event()
            await self._queue.put(
                (-resolved_priority, sequence, task_id, generation)
            )

        await runtime_events.publish(
            "agent.task.queued",
            task_id=task_id,
            queue_position=self.queue_position(task_id),
            dispatch_generation=generation,
        )
        await self._publish_queue_changed(reason="enqueued", task_id=task_id)
        return True

    async def enqueue_when_released(
        self,
        task_id: str,
        *,
        priority: int | None = None,
        timeout_seconds: float = 2.0,
    ) -> bool:
        """
        Enqueue a retry once the previous generation has fully released.

        A task can become persistently `cancelled` just before its executor's
        finally block removes the old running generation. A user can therefore
        press Retry during that tiny window. Waiting briefly here makes retry
        deterministic rather than returning a misleading 503.
        """
        if not self._running:
            return False

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout_seconds)
        while self._running:
            if await self.enqueue(task_id, priority=priority):
                return True

            # If another caller already queued the same retry, regard it as
            # accepted. This also makes the method robust to duplicate UI taps.
            if task_id in self._queued_ids:
                return True

            async with SessionLocal() as session:
                task = await get_task(session, task_id)
            if task is None or task.status != "queued" or task.cancel_requested:
                return False

            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.025)

        return False

    async def cancel(self, task_id: str) -> bool:
        async with SessionLocal() as session:
            task = await get_task(session, task_id)
            if task is None:
                return False
            task = await request_cancel(session, task)

        queue_changed = False
        async with self._lock:
            dispatch = self._queued_dispatches.pop(task_id, None)
            if dispatch is not None:
                # PriorityQueue has no arbitrary-remove operation. Invalidate
                # this dispatch generation and leave the stale tuple in the
                # queue; workers will recognise and discard it harmlessly.
                self._queued_ids.discard(task_id)
                self._dispatch_generation[task_id] = max(
                    self._dispatch_generation.get(task_id, 0),
                    dispatch.generation,
                ) + 1
                stale_event = self._cancel_events.pop(
                    (task_id, dispatch.generation),
                    None,
                )
                if stale_event is not None:
                    stale_event.set()
                queue_changed = True

            active_generation = self._active_generation.get(task_id)
            if active_generation is not None:
                active_event = self._cancel_events.get(
                    (task_id, active_generation)
                )
                if active_event is not None:
                    active_event.set()

        await runtime_events.publish(
            "agent.task.changed",
            task_id=task.id,
            agent_id=task.agent_id,
            status=task.status,
            progress=task.progress,
            progress_message=task.progress_message,
            conversation_id=task.conversation_id,
        )
        if queue_changed:
            await self._publish_queue_changed(reason="cancelled", task_id=task_id)
        return True

    async def _claim_dispatch(
        self,
        *,
        task_id: str,
        generation: int,
    ) -> asyncio.Event | None:
        async with self._lock:
            dispatch = self._queued_dispatches.get(task_id)
            if dispatch is None or dispatch.generation != generation:
                return None

            self._queued_dispatches.pop(task_id, None)
            self._queued_ids.discard(task_id)
            self._running_ids.add(task_id)
            self._active_generation[task_id] = generation
            return self._cancel_events.setdefault(
                (task_id, generation),
                asyncio.Event(),
            )

    async def _release_dispatch(self, task_id: str, generation: int) -> None:
        async with self._lock:
            if self._active_generation.get(task_id) == generation:
                self._active_generation.pop(task_id, None)
                self._running_ids.discard(task_id)
            self._cancel_events.pop((task_id, generation), None)

    async def _worker(self, worker_index: int) -> None:
        while self._running:
            try:
                _, _, task_id, generation = await self._queue.get()
            except asyncio.CancelledError:
                break

            claimed = False
            preserve_assignment_for_supervisor = False
            try:
                cancel_event = await self._claim_dispatch(
                    task_id=task_id,
                    generation=generation,
                )
                if cancel_event is None:
                    # Cancelled/retried queue entry from an older generation.
                    continue
                claimed = True
                await self._publish_queue_changed(
                    reason="dispatched",
                    task_id=task_id,
                )

                async with SessionLocal() as session:
                    task = await get_task(session, task_id)
                # A cancellation can land after the queue entry was claimed but
                # before execute_agent_task has transitioned SQLite to running.
                if (
                    task is None
                    or task.status != "queued"
                    or task.cancel_requested
                    or cancel_event.is_set()
                ):
                    continue
                await self._set_worker_state(
                    worker_index,
                    state="running",
                    task_id=task.id,
                    agent_id=task.agent_id,
                    task_title=task.title,
                    dispatch_generation=generation,
                )
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
                    preserve_assignment_for_supervisor = True
                    raise
                except Exception as exc:
                    await self._fail_task(task_id, str(exc))
            except asyncio.CancelledError:
                if self._running:
                    runtime = self._worker_states.get(worker_index)
                    preserve_assignment_for_supervisor = bool(
                        claimed
                        and runtime is not None
                        and runtime.task_id == task_id
                        and runtime.dispatch_generation == generation
                    )
                    raise
                break
            except Exception:
                runtime = self._worker_states.get(worker_index)
                preserve_assignment_for_supervisor = bool(
                    claimed
                    and runtime is not None
                    and runtime.task_id == task_id
                    and runtime.dispatch_generation == generation
                )
                raise
            finally:
                if claimed:
                    await self._release_dispatch(task_id, generation)
                    if not preserve_assignment_for_supervisor:
                        await self._release_worker_if_owned(
                            worker_index,
                            task_id=task_id,
                            generation=generation,
                        )
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
