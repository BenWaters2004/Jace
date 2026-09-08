import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.config import settings
from jace.db.models import ToolAuditLog, ToolPermission
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _audit_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Redact high-volume/private live input before persistent audit storage."""
    safe = dict(arguments)
    if tool_name == "type_control_text" and isinstance(safe.get("text"), str):
        text = safe["text"]
        safe["text"] = f"<redacted interactive text: {len(text)} characters>"
    return safe


async def ensure_tool_permissions(session: AsyncSession) -> None:
    ensure_tools_registered()

    changed = False
    for definition in registry.all():
        existing = await session.get(ToolPermission, definition.name)
        if existing is not None:
            continue

        session.add(
            ToolPermission(
                tool_name=definition.name,
                permission=definition.default_permission,
            )
        )
        changed = True

    if changed:
        await session.commit()


async def permission_map(session: AsyncSession) -> dict[str, str]:
    await ensure_tool_permissions(session)
    result = await session.execute(select(ToolPermission))
    return {row.tool_name: row.permission for row in result.scalars().all()}


async def get_tool_permission(
    session: AsyncSession,
    tool_name: str,
) -> str:
    ensure_tools_registered()

    definition = registry.get(tool_name)
    if definition is None:
        return "deny"

    row = await session.get(ToolPermission, tool_name)
    if row is None:
        row = ToolPermission(
            tool_name=tool_name,
            permission=definition.default_permission,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return row.permission


async def set_tool_permission(
    session: AsyncSession,
    tool_name: str,
    permission: str,
) -> ToolPermission:
    ensure_tools_registered()

    if registry.get(tool_name) is None:
        raise ValueError("Unknown tool.")
    if permission not in {"allow", "ask", "deny"}:
        raise ValueError("Invalid tool permission.")

    row = await session.get(ToolPermission, tool_name)
    if row is None:
        row = ToolPermission(
            tool_name=tool_name,
            permission=permission,
        )
        session.add(row)
    else:
        row.permission = permission
        row.updated_at = utc_now()

    await session.commit()
    await session.refresh(row)
    return row


async def create_tool_audit(
    session: AsyncSession,
    *,
    conversation_id: str | None,
    tool_name: str,
    permission_mode: str,
    arguments: dict[str, Any],
    status: str = "requested",
) -> ToolAuditLog:
    entry = ToolAuditLog(
        conversation_id=conversation_id,
        tool_name=tool_name,
        permission_mode=permission_mode,
        status=status,
        arguments_json=json.dumps(_audit_arguments(tool_name, arguments), ensure_ascii=False, separators=(",", ":")),
    )

    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def update_tool_audit(
    session: AsyncSession,
    audit_id: str,
    *,
    status: str | None = None,
    result_preview: str | None = None,
    error: str | None = None,
    approval_id: str | None = None,
    completed: bool = False,
) -> ToolAuditLog | None:
    entry = await session.get(ToolAuditLog, audit_id)
    if entry is None:
        return None

    if status is not None:
        entry.status = status
    if result_preview is not None:
        entry.result_preview = result_preview[: settings.tool_audit_preview_chars]
    if error is not None:
        entry.error = error[: settings.tool_audit_preview_chars]
    if approval_id is not None:
        entry.approval_id = approval_id
    if completed:
        entry.completed_at = utc_now()

    await session.commit()
    await session.refresh(entry)
    return entry


async def list_tool_audit(
    session: AsyncSession,
    *,
    limit: int = 100,
    tool_name: str | None = None,
) -> list[ToolAuditLog]:
    statement = select(ToolAuditLog)

    if tool_name:
        statement = statement.where(ToolAuditLog.tool_name == tool_name)

    statement = statement.order_by(ToolAuditLog.created_at.desc()).limit(max(1, min(limit, 500)))
    result = await session.execute(statement)
    return list(result.scalars().all())


async def clear_tool_audit(session: AsyncSession) -> int:
    result = await session.execute(delete(ToolAuditLog))
    await session.commit()
    return result.rowcount or 0
