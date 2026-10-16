"""C4C.3C: fail-closed evidence of tool/approval activity before task redispatch.

This module does not execute, approve, or replay tools. It inspects durable signals
left before execution by Jace's normal Agent Runner plus its tool audit ledger.
"""
from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.agents.models import AgentTask, AgentTaskEvent
from jace.db.models import ToolAuditLog

# A recorded tool_started happens BEFORE Agent Runner calls _execute_tool().
# An external action can complete while a worker dies before tool_completed.
# Conservatively treat *any* tool/approval activity as a replay risk.
RECOVERY_REVIEW_EVENTS = (
    "approval_required", "approval_granted", "approval_denied",
    "approval_timed_out", "approval_cancelled", "waiting_permission",
)


def metadata_is_quarantined(task: AgentTask) -> bool:
    """Never allow a quarantined task to be automatically or manually retried."""
    try:
        metadata = json.loads(task.metadata_json or "{}")
    except (ValueError, TypeError):
        return True  # Corrupt metadata is not evidence of safety.
    if not isinstance(metadata, dict):
        return True
    return metadata.get("recovery_quarantined") is True


def used_tools_indicate_activity(task: AgentTask) -> bool:
    try:
        used = json.loads(task.used_tools_json or "[]")
    except (ValueError, TypeError):
        return True
    return not isinstance(used, list) or bool(used)


async def has_recorded_action_activity(session: AsyncSession, task: AgentTask) -> bool:
    """Read persisted intent and audit records; do not infer absence from worker prose."""
    if metadata_is_quarantined(task) or used_tools_indicate_activity(task):
        return True

    event_id = await session.scalar(
        select(AgentTaskEvent.id).where(
            AgentTaskEvent.task_id == task.id,
            or_(
                AgentTaskEvent.event_type.like("tool_%"),
                AgentTaskEvent.event_type.like("approval_%"),
                AgentTaskEvent.event_type.in_(RECOVERY_REVIEW_EVENTS),
            ),
        ).limit(1)
    )
    if event_id is not None:
        return True

    # Audit can persist an in-flight call even when a completion event is absent.
    audit_id = await session.scalar(
        select(ToolAuditLog.id).where(
            ToolAuditLog.permission_mode == f"agent:{task.id}"
        ).limit(1)
    )
    return audit_id is not None
