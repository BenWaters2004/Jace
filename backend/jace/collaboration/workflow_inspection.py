"""C4D.2: read-only, owner-scoped workflow inspection from persisted records.

Never re-execute tools, call providers, or expose prompt/source content.
Receipts record model-stage summaries, not full per-claim review provenance.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jace.agents.durable_handoffs import clean_review_metadata
from jace.agents.models import (
    AgentTask, AgentTaskEvent, DirectorHandoffReceipt, DirectorWorkflowCheckpoint,
)
from jace.auth.actor_context import ActorContext
from jace.auth.resource_ownership import ownership_for
from jace.database import SessionLocal
from jace.db.models import Conversation

_WORKFLOW_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_SOURCE_TOOLS = {"read_web_page": "public_web", "read_workspace_file": "workspace_file"}


class WorkflowSourceObservation(BaseModel):
    kind: Literal["public_web", "workspace_file"]
    tool: str
    sha256: str
    digest_scope: Literal["web_excerpt", "workspace_full_file"]
    task_id: str
    # Evidence observed in a successful tool record, not necessarily reviewed.
    provenance: Literal["successful_tool_event"] = "successful_tool_event"


class WorkflowTaskObservation(BaseModel):
    task_id: str
    specialist: str
    status: str
    recorded_model: str | None = None
    manual_review: bool = False


class WorkflowInspection(BaseModel):
    workflow_id: str
    checkpoint_stage: str | None = None
    handoff_status: str | None = None
    handoff_recorded: bool = False
    review_status: str = "not_recorded"
    source_count_reported_by_review: int | None = None
    model_calls_reported_by_review: int | None = None
    excerpt_supported_claims: int | None = None
    unresolved_claims: int | None = None
    external_fact_verification: bool = False
    recorded_synthesis_model: str | None = None
    specialists: list[WorkflowTaskObservation] = Field(default_factory=list)
    available_source_observations: list[WorkflowSourceObservation] = Field(default_factory=list)
    source_observation_limit_reached: bool = False
    provenance_notice: str = (
        "Source observations are successful tool records, not proof of reviewer inspection. "
        "Review counts are persisted aggregate metadata; per-claim verdicts and reviewed-source IDs "
        "were not saved by earlier phases. Model agreement is not independent factual verification."
    )


def _metadata(raw: str | None) -> dict:
    try:
        item = json.loads(raw or "{}")
        return item if isinstance(item, dict) else {}
    except (ValueError, TypeError):
        return {}


def source_observations(events: list[tuple[str, str | None, str]]) -> tuple[list[WorkflowSourceObservation], bool]:
    """Whitelist provenance and digest ONLY. Never expose URL/path/excerpts/arguments."""
    result: list[WorkflowSourceObservation] = []
    seen: set[tuple[str, str]] = set()
    truncated = False
    for task_id, event_type, data_json in events:
        if event_type != "tool_completed":
            continue
        data = _metadata(data_json)
        tool = data.get("tool_name")
        if data.get("success") is not True or tool not in _SOURCE_TOOLS:
            continue
        evidence = data.get("evidence")
        if not isinstance(evidence, dict):
            continue
        sha = evidence.get("sha256")
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            continue
        # Workspace source must identify its file; web source must have the
        # captured timestamp and a redacted URL, but neither is returned.
        if tool == "read_workspace_file" and not (evidence.get("path") and evidence.get("workspace")):
            continue
        if tool == "read_web_page" and not (evidence.get("url") and evidence.get("captured_at")):
            continue
        identity = (tool, sha.lower())
        if identity in seen:
            continue
        seen.add(identity)
        if len(result) >= 12:
            truncated = True
            break
        result.append(WorkflowSourceObservation(
            kind=_SOURCE_TOOLS[tool], tool=tool, sha256=sha.lower(),
            digest_scope="web_excerpt" if tool == "read_web_page" else "workspace_full_file",
            task_id=task_id,
        ))
    return result, truncated


async def load_workflow_inspection(workflow_id: str, actor: ActorContext) -> WorkflowInspection:
    if not _WORKFLOW_ID.fullmatch(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    async with SessionLocal() as session:
        receipt = await session.get(DirectorHandoffReceipt, workflow_id)
        checkpoint = await session.get(DirectorWorkflowCheckpoint, workflow_id)
        if receipt is None and checkpoint is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        # Reject conflicting records instead of disclosing another conversation.
        ids = {r.conversation_id for r in (receipt, checkpoint) if r is not None}
        if len(ids) != 1 or not next(iter(ids)):
            raise HTTPException(status_code=404, detail="Workflow not found")
        conversation_id = next(iter(ids))
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        # In server mode require EXPLICIT ownership. No claiming an existing
        # conversation on demand. Local single-user deployments can read it.
        if actor.server_mode:
            ownership = await ownership_for(session, "conversation", conversation_id)
            if ownership is None or ownership.actor_id != actor.actor_id:
                raise HTTPException(status_code=404, detail="Workflow not found")

        tasks = (await session.execute(
            select(AgentTask).where(AgentTask.conversation_id == conversation_id)
            .order_by(AgentTask.updated_at.desc()).limit(500)
        )).scalars().all()
        selected = [task for task in tasks if
                    _metadata(task.metadata_json).get("director_workflow_id") == workflow_id]
        ids = [task.id for task in selected]
        events = []
        if ids:
            rows = (await session.execute(
                select(AgentTaskEvent.task_id, AgentTaskEvent.event_type, AgentTaskEvent.data_json)
                .where(AgentTaskEvent.task_id.in_(ids), AgentTaskEvent.event_type == "tool_completed")
                .order_by(AgentTaskEvent.created_at.desc()).limit(500)
            )).all()
            events = [(row[0], row[1], row[2]) for row in rows]

        observations, truncated = source_observations(events)
        from_receipt = _metadata(receipt.review_metadata_json) if receipt else {}
        from_checkpoint = _metadata(checkpoint.review_metadata_json) if checkpoint else {}
        review = clean_review_metadata(from_receipt if receipt else from_checkpoint)
        tasks_view = [WorkflowTaskObservation(
            task_id=t.id, specialist=t.agent_id, status=t.status,
            recorded_model=t.model[:120] if t.model else None,
            manual_review=_metadata(t.metadata_json).get("recovery_quarantined") is True,
        ) for t in selected[:30]]
        return WorkflowInspection(
            workflow_id=workflow_id,
            checkpoint_stage=checkpoint.stage if checkpoint else None,
            handoff_status=receipt.status if receipt else None,
            handoff_recorded=bool(receipt and receipt.handoff_message_id),
            review_status=str(review.get("status") or (receipt.review_status if receipt else "not_recorded"))[:60],
            source_count_reported_by_review=review.get("source_count"),
            model_calls_reported_by_review=review.get("model_calls"),
            excerpt_supported_claims=review.get("excerpt_supported_claims"),
            unresolved_claims=review.get("unresolved_claims"),
            external_fact_verification=False,
            recorded_synthesis_model=checkpoint.model[:120] if checkpoint else None,
            specialists=tasks_view,
            available_source_observations=observations,
            source_observation_limit_reached=truncated or len(events) >= 500,
        )
