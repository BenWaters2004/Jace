from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.connections.models import CapabilityPermissionRecord, ConnectionRecord
from jace.connections.providers import get_provider
from jace.db.models import utc_now

VALID_MODES = {"allow", "ask", "deny"}
DEFAULT_MODE = "ask"


def binding_id(connection_id: str, capability_id: str) -> str:
    return f"{connection_id}:{capability_id}"


async def permission_map(session: AsyncSession) -> dict[tuple[str, str], str]:
    rows = (await session.execute(select(CapabilityPermissionRecord))).scalars().all()
    return {(row.connection_id, row.capability_id): row.permission for row in rows}


async def set_permission(
    session: AsyncSession,
    connection_id: str,
    capability_id: str,
    permission: str,
) -> CapabilityPermissionRecord:
    if permission not in VALID_MODES:
        raise ValueError("Capability permission must be allow, ask, or deny.")
    connection = await session.get(ConnectionRecord, connection_id)
    if connection is None:
        raise ValueError("Connection not found.")
    provider = get_provider(connection.provider_id)
    if provider is None:
        raise ValueError("Connection provider is not registered.")
    if capability_id not in {item.id for item in provider.capabilities}:
        raise ValueError(f"{provider.name} does not declare capability {capability_id}.")
    key = binding_id(connection_id, capability_id)
    row = await session.get(CapabilityPermissionRecord, key)
    if row is None:
        row = CapabilityPermissionRecord(
            id=key,
            connection_id=connection_id,
            capability_id=capability_id,
            permission=permission,
            updated_at=utc_now(),
        )
        session.add(row)
    else:
        row.permission = permission
        row.updated_at = utc_now()
    await session.commit()
    await session.refresh(row)
    return row
