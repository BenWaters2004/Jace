"""Conservative Phase C2 cloud chat selection and model catalogue.

No provider network requests; provider IDs and selected routes come from Jace
configuration. Legacy unqualified conversation labels are migrated lazily, only
with an explicit administrator opt-in. Explicit provider routes are preserved.
"""
from __future__ import annotations

from typing import Iterable

_PROVIDER_PREFIXES = frozenset({"ollama", "openai", "anthropic"})
_CLOUD_PREFIXES = frozenset({"openai", "anthropic"})


class ChatCutoverConfigurationError(ValueError):
    pass


def _qualified(value: str) -> tuple[str, str] | None:
    prefix, sep, model = value.strip().partition(":")
    if sep and prefix.lower() in _PROVIDER_PREFIXES:
        if not model.strip():
            raise ChatCutoverConfigurationError("Provider model route is missing a model ID.")
        return prefix.lower(), model.strip()
    return None


def choose_chat_model(
    selected: str | None,
    *,
    cutover_enabled: bool,
    fast_route: str,
    auto_enabled: bool = False,
) -> str:
    """Use a cloud route for legacy selections, never for explicit local routes.

    A saved old model like ``qwen3.5:4b`` is NOT a provider-qualified route.
    An explicit ``ollama:qwen3.5:4b`` remains local even when cutover is on.
    """
    value = (selected or "").strip()
    if not cutover_enabled:
        return value
    target = fast_route.strip()
    resolved = _qualified(target)
    if not resolved or resolved[0] not in _CLOUD_PREFIXES:
        raise ChatCutoverConfigurationError(
            "Cloud chat cutover requires JACE_MODEL_ROUTE_CONVERSATION_FAST="
            "openai:<model-id> or anthropic:<model-id>."
        )
    if value.lower() == "auto" and auto_enabled:
        return "auto"
    if _qualified(value):
        return value
    return target


def configured_cloud_models(
    routes: Iterable[str], *, cloud_egress: bool, openai_enabled: bool,
    anthropic_enabled: bool,
) -> list[str]:
    """List *configured* and enabled model routes; do not imply API availability."""
    if not cloud_egress:
        return []
    found: list[str] = []
    for raw in routes:
        value = (raw or "").strip()
        route = _qualified(value)
        if not route:
            continue
        provider, _ = route
        if provider == "openai" and not openai_enabled:
            continue
        if provider == "anthropic" and not anthropic_enabled:
            continue
        if provider in _CLOUD_PREFIXES and value not in found:
            found.append(value)
    return found
