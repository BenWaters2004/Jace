from __future__ import annotations

# JACE_STEP4A3_SCOPE_AWARE_CAPABILITY_REGISTRY

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import unquote

from sqlalchemy.ext.asyncio import AsyncSession

from jace.capabilities.access import ExternalAccessPolicy, external_access_policy
from jace.capabilities.permissions import permission_map as connection_permission_map
from jace.config import settings
from jace.connections.models import ConnectionRecord
from jace.connections.providers import PROVIDERS, ProviderCapability, ProviderDefinition
from jace.connections.service import list_connections
from jace.tools import ensure_tools_registered
from jace.tools.permissions import ensure_tool_permissions, permission_map
from jace.tools.registry import registry as tool_registry

CapabilityState = Literal[
    "ready",
    "blocked",
    "configured",
    "planned",
    "disconnected",
]
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
    provider_capability_id: str | None = None
    connection_id: str | None = None
    connection_status: str | None = None
    account_hint: str | None = None
    tool_name: str | None = None
    permission: str | None = None
    required_scopes: tuple[str, ...] = ()
    granted_scopes: tuple[str, ...] = ()
    missing_scopes: tuple[str, ...] = ()
    availability_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _normalise_scope_values(raw: object) -> tuple[str, ...]:
    values: list[str] = []

    if isinstance(raw, str):
        # OAuth providers commonly return either spaces or commas.
        values.extend(
            item.strip()
            for item in re.split(r"[\s,]+", raw)
            if item.strip()
        )
    elif isinstance(raw, (list, tuple, set)):
        values.extend(
            str(item).strip()
            for item in raw
            if str(item).strip()
        )

    # Preserve provider spelling while deduplicating case-insensitively.
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)

    return tuple(result)


def _connection_scopes(row: ConnectionRecord) -> tuple[str, ...]:
    config = _json_object(row.config_json)
    return _normalise_scope_values(config.get("scopes"))


def _scope_satisfied(
    provider_id: str,
    required_scope: str,
    granted_scopes: tuple[str, ...],
) -> bool:
    required = required_scope.casefold()
    granted = {scope.casefold() for scope in granted_scopes}

    if required in granted:
        return True

    # JACE_STEP4C2_MICROSOFT_SCOPE_NORMALIZATION
    # Microsoft can report Graph delegated scopes as either short
    # names (Mail.Read) or resource-qualified values.
    if provider_id == "microsoft":
        microsoft_granted: set[str] = set()

        for scope in granted_scopes:
            decoded = unquote(scope).strip().casefold()

            if not decoded:
                continue

            microsoft_granted.add(decoded)

            if "/" in decoded:
                microsoft_granted.add(
                    decoded.rsplit("/", 1)[-1]
                )

        if required in microsoft_granted:
            return True

    # GitHub OAuth scopes are hierarchical. A broader scope can satisfy
    # a narrower requirement even when the narrow scope is absent from the
    # token's normalised scope list.
    if provider_id == "github":
        if required in {"read:user", "user:email", "user:follow"} and "user" in granted:
            return True
        if required == "public_repo" and "repo" in granted:
            return True

    return False


def _missing_scopes(
    provider_id: str,
    required_scopes: tuple[str, ...],
    granted_scopes: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        scope
        for scope in required_scopes
        if not _scope_satisfied(provider_id, scope, granted_scopes)
    )


def _provider_binding(
    *,
    provider: ProviderDefinition,
    capability: ProviderCapability,
    row: ConnectionRecord,
    permission: str,
    access: ExternalAccessPolicy,
) -> CapabilityDescriptor:
    granted_scopes = _connection_scopes(row)
    missing_scopes = _missing_scopes(
        provider.id,
        capability.required_scopes,
        granted_scopes,
    )

    tool_available = bool(
        capability.tool_name
        and tool_registry.get(capability.tool_name) is not None
    )

    if row.status == "disconnected":
        state: CapabilityState = "disconnected"
        reason = "connection_disconnected"
    elif row.status == "error":
        state = "blocked"
        reason = "connection_error"
    elif not access.external_services_enabled:
        state = "blocked"
        reason = "external_services_disabled"
    elif not access.providers.get(provider.id, True):
        state = "blocked"
        reason = "provider_disabled"
    elif missing_scopes:
        state = "blocked"
        reason = "missing_scopes"
    elif permission == "deny":
        state = "blocked"
        reason = "permission_denied"
    elif tool_available:
        state = "ready"
        reason = "ready"
    else:
        # The account and OAuth permission are present, but the actual provider
        # operation has not yet been bound to a Jace tool implementation.
        state = "configured"
        reason = "implementation_pending"

    return CapabilityDescriptor(
        id=f"connection.{row.id}.{capability.id}",
        label=capability.label,
        description=capability.description,
        category=capability.category,
        source="connection",
        state=state,
        risk=capability.risk,
        provider_id=provider.id,
        provider_capability_id=capability.id,
        connection_id=row.id,
        connection_status=row.status,
        account_hint=row.account_hint,
        tool_name=capability.tool_name,
        permission=permission,
        required_scopes=capability.required_scopes,
        granted_scopes=granted_scopes,
        missing_scopes=missing_scopes,
        availability_reason=reason,
    )


def _planned_provider_capability(
    provider: ProviderDefinition,
    capability: ProviderCapability,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=f"provider.{provider.id}.{capability.id}",
        label=capability.label,
        description=capability.description,
        category=capability.category,
        source="connection",
        state="planned",
        risk=capability.risk,
        provider_id=provider.id,
        provider_capability_id=capability.id,
        permission=None,
        required_scopes=capability.required_scopes,
        availability_reason="connection_required",
    )


async def snapshot(session: AsyncSession) -> dict:
    ensure_tools_registered()
    await ensure_tool_permissions(session)

    local_permissions = await permission_map(session)
    connection_permissions = await connection_permission_map(session)
    # JACE_STEP4A6_EXTERNAL_ACCESS_POLICY
    access = await external_access_policy(session)

    capabilities: list[CapabilityDescriptor] = []

    # Existing local Jace tools remain part of the same registry.
    for tool in tool_registry.all():
        permission = local_permissions.get(
            tool.name,
            tool.default_permission,
        )

        if not settings.tools_enabled or permission == "deny":
            state: CapabilityState = "blocked"
            reason = (
                "tools_disabled"
                if not settings.tools_enabled
                else "permission_denied"
            )
        else:
            state = "ready"
            reason = "ready"

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
                availability_reason=reason,
            )
        )

    rows = await list_connections(session)

    by_provider: dict[str, list[ConnectionRecord]] = {}

    for row in rows:
        by_provider.setdefault(
            row.provider_id,
            [],
        ).append(row)

    # A capability is a binding to a specific connection, not just a provider.
    # This is important when Ben connects more than one Google/Microsoft/GitHub
    # account later.
    for provider in PROVIDERS:
        provider_rows = by_provider.get(
            provider.id,
            [],
        )

        if not provider_rows:
            for capability in provider.capabilities:
                capabilities.append(
                    _planned_provider_capability(
                        provider,
                        capability,
                    )
                )
            continue

        for row in provider_rows:
            for capability in provider.capabilities:
                permission = connection_permissions.get(
                    (row.id, capability.id),
                    capability.default_permission,
                )

                capabilities.append(
                    _provider_binding(
                        provider=provider,
                        capability=capability,
                        row=row,
                        permission=permission,
                        access=access,
                    )
                )

    counts = {
        "ready": sum(
            item.state == "ready"
            for item in capabilities
        ),
        "blocked": sum(
            item.state == "blocked"
            for item in capabilities
        ),
        "configured": sum(
            item.state == "configured"
            for item in capabilities
        ),
        "planned": sum(
            item.state == "planned"
            for item in capabilities
        ),
        "disconnected": sum(
            item.state == "disconnected"
            for item in capabilities
        ),
        "needs_access": sum(
            item.availability_reason == "missing_scopes"
            for item in capabilities
        ),
        "external_disabled": sum(
            item.availability_reason in {
                "external_services_disabled",
                "provider_disabled",
            }
            for item in capabilities
        ),
    }

    return {
        "capabilities": [
            item.as_dict()
            for item in capabilities
        ],
        "counts": counts,
        "connection_count": len(rows),
    }
