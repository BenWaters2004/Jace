"""C4C.3: transactionally idempotent Agent Director handoffs.

No extra model calls or tool permissions. A unique workflow receipt and its final
chat message are committed together, so recovery does not duplicate that message.

This is not an exactly-once execution guarantee for upstream model/tool actions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from jace.agents.models import AgentTask, AgentTaskEvent, DirectorHandoffReceipt
from jace.database import SessionLocal
from jace.db.models import Conversation, Message, utc_now


@dataclass(frozen=True)
class HandoffSave:
    message_id: str | None
    created: bool
    status: str


# Only non-sensitive scalar counters/statuses may be persisted in the receipt.
_REVIEW_FIELDS = {
    "status", "source_count", "model_calls", "excerpt_supported_claims",
    "unresolved_claims", "external_fact_verification",
}


def clean_review_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    value = metadata or {}
    result: dict[str, Any] = {}
    for key in _REVIEW_FIELDS:
        v = value.get(key)
        if key in {"status"} and isinstance(v, str):
            result[key] = v[:60] if v.replace("_", "").isalnum() else "unknown"
        elif key == "external_fact_verification" and isinstance(v, bool):
            result[key] = v
        elif key not in {"status", "external_fact_verification"} and (
            v is None or (type(v) is int and 0 <= v <= 100000)
        ):
            result[key] = v
    return result


async def existing_receipt(workflow_id: str) -> HandoffSave | None:
    async with SessionLocal() as session:
        row = await session.get(DirectorHandoffReceipt, workflow_id)
        if row is None:
            return None
        return HandoffSave(message_id=row.handoff_message_id, created=False, status=row.status)


async def save_handoff_once(
    *, workflow_id: str, conversation_id: str | None, objective: str,
    result: str, review_metadata: dict[str, Any] | None = None,
) -> HandoffSave:
    """Atomically insert a workflow receipt and (when possible) its one chat message.

    Races across processes resolve via the receipt's workflow_id primary key.
    The unsuccessful transaction rolls back its newly created message as well.
    """
    if not workflow_id or len(workflow_id) > 36:
        raise ValueError("Invalid Director workflow ID")
    reviewed = clean_review_metadata(review_metadata)
    async with SessionLocal() as session:
        existing = await session.get(DirectorHandoffReceipt, workflow_id)
        if existing is not None:
            return HandoffSave(existing.handoff_message_id, False, existing.status)
        conversation = await session.get(Conversation, conversation_id) if conversation_id else None
        row = DirectorHandoffReceipt(
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            handoff_message_id=None,
            status="completed" if conversation is not None else "no_conversation",
            result_sha256=hashlib.sha256(result.encode("utf-8")).hexdigest(),
            review_status=reviewed.get("status", "disabled"),
            review_metadata_json=json.dumps(reviewed, ensure_ascii=False, separators=(",", ":")),
        )
        session.add(row)
        if conversation is not None:
            title = " ".join((objective or "").split()).strip(" .,:;-")[:92] or "Directed agent workflow"
            message = Message(
                conversation=conversation,
                role="assistant",
                content=f"Agent Director completed “{title}”.\n\n{result}".strip(),
                status="complete",
                model="agent:director",
            )
            session.add(message)
            conversation.updated_at = utc_now()
            await session.flush()
            row.handoff_message_id = message.id
        try:
            await session.commit()
        except IntegrityError:
            # Another worker committed this workflow's receipt first.
            await session.rollback()
            winner = await session.get(DirectorHandoffReceipt, workflow_id)
            if winner is None:
                raise
            return HandoffSave(winner.handoff_message_id, False, winner.status)
        return HandoffSave(row.handoff_message_id, True, row.status)


async def failed_task_is_retry_safe(task_id: str) -> bool:
    """Fail closed if any tool or approval attempt was recorded for this task.

    A failed worker may have executed a side effect before its final exception.
    Never resubmit it automatically when there is any evidence of a tool attempt.
    """
    async with SessionLocal() as session:
        task = await session.get(AgentTask, task_id)
        if task is None or task.status != "failed":
            return False
        try:
            used = json.loads(task.used_tools_json or "[]")
        except (TypeError, ValueError):
            return False
        if not isinstance(used, list) or used:
            return False
        record = await session.execute(
            select(AgentTaskEvent.id).where(
                AgentTaskEvent.task_id == task_id,
                or_(
                    AgentTaskEvent.event_type.ilike("%tool%"),
                    AgentTaskEvent.event_type.ilike("%approval%"),
                ),
            ).limit(1)
        )
        return record.first() is None
