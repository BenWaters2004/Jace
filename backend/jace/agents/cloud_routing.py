"""C5A: explicit, opt-in cloud inference routes for Director and specialists.

This module does not transmit data, alter tool permissions, or prove a provider is
reachable. A model route is pinned into each *new* AgentTask when enabled.
"""
from __future__ import annotations

import re
from typing import Any

from jace.config import settings
from jace.model_gateway import model_gateway


ROLE_CONFIG = {
    "director": "agent_route_director",
    "research": "agent_route_research",
    "code": "agent_route_code",
    "files": "agent_route_files",
    "analyst": "agent_route_analyst",
    "general": "agent_route_general",
}

# Cloud-first is explicitly cloud-only in C5A. Local tasks are still possible
# by disabling the new feature and using the original model/profile behaviour.
_CLOUD_ROUTE = re.compile(r"^(openai|anthropic):([A-Za-z0-9][A-Za-z0-9._+/-]{0,199})$", re.IGNORECASE)


class AgentCloudRoutingError(ValueError):
    """Invalid or unavailable opt-in cloud-agent route, without exposing secrets."""


def resolve_agent_model(
    role: str,
    *,
    requested_model: str | None = None,
    legacy_model: str | None = None,
    config: Any = None,
    gateway: Any = None,
) -> str | None:
    """Return an explicit, validated route or retain original disabled behaviour.

    `requested_model` represents an intentional caller override and must itself
    be cloud-qualified in cloud mode. The legacy assistant profile is *never*
    interpreted as a cloud route while cloud mode is active.

    Resolution does not test network availability or bypass Privacy Gateway.
    """
    config = settings if config is None else config
    gateway = model_gateway if gateway is None else gateway
    if role not in ROLE_CONFIG:
        raise AgentCloudRoutingError("Unsupported agent role for model routing.")

    if not bool(getattr(config, "agent_cloud_routing_enabled", False)):
        return (requested_model or legacy_model or "").strip() or None

    if not (bool(getattr(config, "privacy_enabled", False)) and
            bool(getattr(config, "privacy_cloud_egress_enabled", False))):
        raise AgentCloudRoutingError(
            "Cloud agent routing requires privacy controls and cloud egress enabled."
        )

    setting_name = ROLE_CONFIG[role]
    candidate = (requested_model or getattr(config, setting_name, "") or "").strip()
    if not candidate:
        raise AgentCloudRoutingError(
            f"Missing JACE_{setting_name.upper()} for cloud agent '{role}'."
        )
    if not _CLOUD_ROUTE.fullmatch(candidate):
        raise AgentCloudRoutingError(
            f"Agent '{role}' requires an explicit openai:model or anthropic:model route."
        )

    try:
        selected = gateway.resolve("conversation.fast", requested_model=candidate)
    except Exception as exc:
        # Provider exceptions could include account/request internals. Do not echo.
        raise AgentCloudRoutingError(
            f"Provider configured for agent '{role}' is disabled or unavailable."
        ) from exc
    if selected.local or selected.provider not in {"openai", "anthropic"}:
        raise AgentCloudRoutingError("A cloud agent cannot silently use a local provider.")
    return f"{selected.provider}:{selected.model}"
