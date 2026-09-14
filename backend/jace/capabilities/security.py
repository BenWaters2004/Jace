from __future__ import annotations

# JACE_STEP4A5_EXTERNAL_BINDING_REVALIDATION

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from jace.capabilities.registry import snapshot


async def validate_external_tool_binding(
    session: AsyncSession,
    definition,
    binding: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    capability_id = getattr(definition, "capability_id", None)

    if capability_id is None:
        return binding, None

    provider_id = getattr(definition, "provider_id", None)

    if not binding:
        return None, (
            "External tool execution was blocked because Jace did not supply "
            "a connection binding."
        )

    connection_id = str(binding.get("connection_id") or "")
    bound_capability = str(binding.get("capability_id") or "")
    bound_provider = str(binding.get("provider_id") or "")

    if not connection_id:
        return None, "External tool execution was blocked because no connection was selected."

    if bound_capability != capability_id:
        return None, "External tool execution was blocked because the capability binding changed."

    if provider_id and bound_provider != provider_id:
        return None, "External tool execution was blocked because the provider binding changed."

    current = await snapshot(session)

    match = next(
        (
            row
            for row in current.get("capabilities", [])
            if row.get("source") == "connection"
            and row.get("connection_id") == connection_id
            and row.get("provider_capability_id") == capability_id
            and (
                provider_id is None
                or row.get("provider_id") == provider_id
            )
        ),
        None,
    )

    if match is None:
        return None, (
            "The selected external account or capability no longer exists. "
            "Reconnect or select another account."
        )

    state = str(match.get("state") or "")
    reason = str(match.get("availability_reason") or "")

    if state != "ready":
        messages = {
            "missing_scopes": (
                "The connected account no longer has the provider access "
                "required for this capability."
            ),
            "permission_denied": (
                "This external capability is currently denied by Jace's "
                "permission policy."
            ),
            "connection_error": (
                "The connected account is in an error state and must be "
                "verified or reconnected."
            ),
            "connection_disconnected": (
                "The selected account has been disconnected."
            ),
            "tools_disabled": (
                "External tool execution is disabled by Jace's global tool setting."
            ),
            "implementation_pending": (
                "This external capability no longer has an executable tool implementation."
            ),
        }
        return None, messages.get(
            reason,
            "This external capability is no longer available.",
        )

    if match.get("tool_name") != definition.name:
        return None, (
            "External tool execution was blocked because the registered tool "
            "no longer matches the resolved capability."
        )

    validated = dict(binding)
    validated.update(
        {
            "provider_id": match.get("provider_id"),
            "connection_id": match.get("connection_id"),
            "capability_id": match.get("provider_capability_id"),
            "account_hint": match.get("account_hint"),
            "permission": match.get("permission") or "ask",
        }
    )

    return validated, None
