"""C4C.3B Agent Director checkpoints, local DB only.

Checkpoints permit resumable planning and completed model-stage reuse. They DO NOT
make in-flight provider calls or external side effects exactly-once. The
existing Tool Approval Manager remains the authority for actions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from jace.agents.models import AgentTask, AgentTaskEvent, DirectorWorkflowCheckpoint
from jace.database import SessionLocal
from jace.db.models import utc_now
from jace.agents.durable_handoffs import clean_review_metadata

MAX_OBJECTIVE = 100000
MAX_PLAN = 28000
MAX_RESULT = 75000
STAGES = {"planned": 1, "synthesized": 2, "reviewed": 3, "completed": 4}


@dataclass(frozen=True)
class Checkpoint:
    workflow_id: str
    conversation_id: str | None
    objective: str
    plan: dict[str, Any]
    model: str
    temperature: float
    reasoning_mode: str
    stage: str
    synthesis: str | None
    final_result: str | None
    review_metadata: dict[str, Any]


def _bounded(value: str, maximum: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"Invalid {label} checkpoint length")
    return value


def _snapshot(row: DirectorWorkflowCheckpoint) -> Checkpoint:
    plan = json.loads(row.plan_json)
    meta = json.loads(row.review_metadata_json or "{}")
    if not isinstance(plan, dict) or not isinstance(meta, dict):
        raise ValueError("Corrupt Director checkpoint JSON")
    if row.stage not in STAGES:
        raise ValueError("Invalid Director checkpoint stage")
    return Checkpoint(
        workflow_id=row.workflow_id, conversation_id=row.conversation_id,
        objective=row.objective, plan=plan, model=row.model,
        temperature=row.temperature, reasoning_mode=row.reasoning_mode,
        stage=row.stage, synthesis=row.synthesis, final_result=row.final_result,
        review_metadata=clean_review_metadata(meta),
    )


async def load_checkpoint(workflow_id: str) -> Checkpoint | None:
    async with SessionLocal() as session:
        row = await session.get(DirectorWorkflowCheckpoint, workflow_id)
        return _snapshot(row) if row else None


async def save_plan(
    *, workflow_id: str, conversation_id: str | None, objective: str,
    plan: dict[str, Any], model: str, temperature: float, reasoning_mode: str,
) -> Checkpoint:
    if not workflow_id or len(workflow_id) > 36:
        raise ValueError("Invalid workflow ID")
    objective = _bounded(objective, MAX_OBJECTIVE, "objective")
    model = _bounded(model, 200, "model")
    if reasoning_mode not in {"fast", "balanced", "deep"}:
        raise ValueError("Invalid reasoning mode")
    if type(temperature) not in {int, float} or not (0 <= temperature <= 2):
        raise ValueError("Invalid model temperature")
    plan_json = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
    _bounded(plan_json, MAX_PLAN, "plan")
    async with SessionLocal() as session:
        existing = await session.get(DirectorWorkflowCheckpoint, workflow_id)
        if existing:
            return _snapshot(existing)
        row = DirectorWorkflowCheckpoint(
            workflow_id=workflow_id, conversation_id=conversation_id,
            objective=objective, plan_json=plan_json,
            model=model, temperature=float(temperature),
            reasoning_mode=reasoning_mode, stage="planned", updated_at=utc_now(),
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.get(DirectorWorkflowCheckpoint, workflow_id)
            if existing is None:
                raise
            return _snapshot(existing)
        return _snapshot(row)


async def save_stage(
    workflow_id: str, stage: str, *, synthesis: str | None = None,
    final_result: str | None = None, review_metadata: dict[str, Any] | None = None,
) -> Checkpoint:
    if stage not in {"synthesized", "reviewed", "completed"}:
        raise ValueError("Invalid checkpoint stage transition")
    async with SessionLocal() as session:
        row = await session.get(DirectorWorkflowCheckpoint, workflow_id)
        if row is None:
            raise ValueError("Workflow plan checkpoint is missing")
        if STAGES[row.stage] >= STAGES[stage]:
            return _snapshot(row)
        allowed = {"planned": "synthesized", "synthesized": "reviewed", "reviewed": "completed"}
        if allowed.get(row.stage) != stage:
            raise ValueError("Checkpoint stages must progress in order")
        if stage == "synthesized":
            row.synthesis = _bounded(synthesis, MAX_RESULT, "synthesis")
            if not row.synthesis.strip():
                raise ValueError("Cannot checkpoint an empty synthesis")
        elif stage == "reviewed":
            row.final_result = _bounded(final_result, MAX_RESULT, "reviewed handoff")
            if not row.final_result.strip():
                raise ValueError("Cannot checkpoint an empty handoff")
            row.review_metadata_json = json.dumps(
                clean_review_metadata(review_metadata), separators=(",", ":")
            )
        row.stage = stage
        row.updated_at = utc_now()
        await session.commit()
        return _snapshot(row)


async def incomplete_checkpoints(limit: int = 500) -> list[Checkpoint]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(DirectorWorkflowCheckpoint)
            .where(DirectorWorkflowCheckpoint.stage != "completed")
            .order_by(DirectorWorkflowCheckpoint.updated_at.asc())
            .limit(min(max(1, limit), 500))
        )
        snapshots: list[Checkpoint] = []
        for row in result.scalars():
            try:
                snapshots.append(_snapshot(row))
            except (ValueError, TypeError, json.JSONDecodeError):
                # Corrupt checkpoints need manual inspection, never guessed recovery.
                continue
        return snapshots


async def existing_task_requires_manual_review(task_id: str) -> bool:
    """Unsafe after restart if a nonterminal worker attempted a tool/approval.

    This check is deliberately conservative; it cannot prove no external
    side effect occurred if the worker crashed before recording an event.
    """
    async with SessionLocal() as session:
        task = await session.get(AgentTask, task_id)
        if task is None:
            return True
        if task.status in {"completed", "failed", "cancelled"}:
            return False
        try:
            used = json.loads(task.used_tools_json or "[]")
        except (ValueError, TypeError):
            return True
        if not isinstance(used, list) or bool(used):
            return True
        result = await session.execute(
            select(AgentTaskEvent.id).where(
                AgentTaskEvent.task_id == task_id,
                or_(
                    AgentTaskEvent.event_type.ilike("%tool%"),
                    AgentTaskEvent.event_type.ilike("%approval%"),
                ),
            ).limit(1)
        )
        return result.first() is not None
