from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from jace.config import settings
from jace.connections.providers import PROVIDERS
from jace.connections.service import list_connections
from jace.tools import ensure_tools_registered
from jace.tools.permissions import ensure_tool_permissions, permission_map
from jace.tools.registry import registry as tool_registry

CapabilityState = Literal["ready", "blocked", "configured", "planned", "disconnected"]
CapabilitySource = Literal["local_tool", "connection"]


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    label: str
    description: str
    category: str
    source: CapabilitySource
    state: CapabilityState
    risk: str
    provider_id: str | None = None
    connection_id: str | None = None
    tool_name: str | None = None
    permission: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


async def snapshot(session: AsyncSession) -> dict:
    ensure_tools_registered()
    await ensure_tool_permissions(session)
    permissions = await permission_map(session)

    capabilities: list[CapabilityDescriptor] = []
    for tool in tool_registry.all():
        permission = permissions.get(tool.name, tool.default_permission)
        if not settings.tools_enabled or permission == "deny":
            state: CapabilityState = "blocked"
        else:
            state = "ready"
        capabilities.append(
            CapabilityDescriptor(
                id=f"tool.{tool.name}",
                label=tool.label,
                description=tool.description,
                category=tool.category,
                source="local_tool",
                state=state,
                risk=tool.risk,
                tool_name=tool.name,
                permission=permission,
            )
        )

    rows = await list_connections(session)
    by_provider: dict[str, list] = {}
    for row in rows:
        by_provider.setdefault(row.provider_id, []).append(row)

    for provider in PROVIDERS:
        provider_rows = by_provider.get(provider.id, [])
        active = next((row for row in provider_rows if row.status == "configured"), None)
        disconnected = next((row for row in provider_rows if row.status == "disconnected"), None)
        for capability in provider.capabilities:
            if provider.setup_state == "oauth_pending":
                state = "planned"
                connection_id = None
            elif active is not None:
                # 4A.1 intentionally stops at configuration. A guarded request executor is not yet registered.
                state = "configured"
                connection_id = active.id
            elif disconnected is not None:
                state = "disconnected"
                connection_id = disconnected.id
            else:
                state = "planned"
                connection_id = None
            capabilities.append(
                CapabilityDescriptor(
                    id=f"{provider.id}.{capability.id}",
                    label=capability.label,
                    description=capability.description,
                    category=capability.category,
                    source="connection",
                    state=state,
                    risk=capability.risk,
                    provider_id=provider.id,
                    connection_id=connection_id,
                )
            )

    counts = {
        "ready": sum(item.state == "ready" for item in capabilities),
        "blocked": sum(item.state == "blocked" for item in capabilities),
        "configured": sum(item.state == "configured" for item in capabilities),
        "planned": sum(item.state == "planned" for item in capabilities),
        "disconnected": sum(item.state == "disconnected" for item in capabilities),
    }
    return {
        "capabilities": [item.as_dict() for item in capabilities],
        "counts": counts,
        "connection_count": len(rows),
    }
