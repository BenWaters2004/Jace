"""Phase C3A: deterministic and auditable model tier selection.

Routing is deliberately *not* model inference. This selector performs no I/O,
never runs tools and never bypasses the Model Gateway's privacy policy.
Provider health, retries, budgets and cross-provider verification are later phases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Tier = Literal["fast", "balanced", "deep", "coding", "research"]
_ALLOWED = frozenset({"openai", "anthropic", "ollama"})


class SmartRoutingConfigurationError(ValueError):
    """Configuration is missing or invalid; do not guess a model."""


@dataclass(frozen=True)
class RouteSelection:
    route: str
    tier: Tier
    reason: str
    fallback_to_fast: bool


_CODING = re.compile(
    r"\b(?:debug|refactor|implement|coding|codebase|stack trace|traceback|"
    r"unit tests?|pull request|typescript|javascript|python script|"
    r"fix (?:the|this|a) (?:bug|error|function|code)|"
    r"write (?:a|the|some) code)\b", re.IGNORECASE
)
_RESEARCH = re.compile(
    r"\b(?:research|fact[- ]check|verify (?:the |these )?sources|"
    r"compare sources|investigate current|latest (?:news|research|developments)|"
    r"find sources|citations? for|source[- ]backed)\b", re.IGNORECASE
)
_MULTI = re.compile(
    r"\b(?:step[- ]by[- ]step|detailed plan|deep analysis|trade[- ]offs|"
    r"compare (?:the |these )?(?:approaches|options|alternatives)|"
    r"architecture|multi[- ]step|root cause)\b", re.IGNORECASE
)


def _validated_route(raw: str, name: str) -> str:
    value = (raw or "").strip()
    provider, colon, model = value.partition(":")
    if not colon or provider.strip().lower() not in _ALLOWED or not model.strip():
        raise SmartRoutingConfigurationError(
            f"{name} must be provider:model (openai, anthropic or ollama)."
        )
    return provider.lower().strip() + ":" + model.strip()


def select_tier(message: str, reasoning_mode: str = "fast") -> tuple[Tier, str]:
    """Decide class from user text and their explicit reasoning preference.

    Deep wins over text heuristics. Fast is a speed preference, but an explicit
    research or coding *task* is routed to its configured specialist tier.
    """
    mode = (reasoning_mode or "fast").strip().lower()
    if mode == "deep":
        return "deep", "user_selected_deep"
    if _RESEARCH.search(message):
        return "research", "research_request"
    if _CODING.search(message):
        return "coding", "coding_request"
    if mode == "balanced":
        return "balanced", "user_selected_balanced"
    if _MULTI.search(message) or len(message.strip()) > 650:
        return "balanced", "multi_step_or_long_request"
    return "fast", "short_request"


def select_route(
    *, message: str, reasoning_mode: str,
    fast_route: str, balanced_route: str = "", deep_route: str = "",
    coding_route: str = "", research_route: str = "",
) -> RouteSelection:
    """Choose configured route; unconfigured specialist tiers inherit fast.

    Missing tier routes never invent model IDs; config errors fail closed.
    The returned fallback flag records tier *configuration fallback*, not a
    health-based failover, and no provider calls occur here.
    """
    fast = _validated_route(fast_route, "JACE_MODEL_ROUTE_CONVERSATION_FAST")
    tier, reason = select_tier(message, reasoning_mode)
    overrides = {
        "fast": "",
        "balanced": balanced_route,
        "deep": deep_route,
        "coding": coding_route,
        "research": research_route,
    }
    candidate = (overrides[tier] or "").strip()
    if not candidate:
        return RouteSelection(route=fast, tier=tier, reason=reason,
                              fallback_to_fast=tier != "fast")
    return RouteSelection(route=_validated_route(candidate, f"{tier} route"),
                          tier=tier, reason=reason, fallback_to_fast=False)
