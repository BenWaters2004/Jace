"""C3B: process-local cloud reliability and estimated-cost observation.

Privacy transformation MUST occur before these wrappers. No prompts, replies,
headers, secrets, or raw exception strings are retained in telemetry.

A stream is retried only when zero chunks were emitted to its consumer.
Provider operations are *inference requests*, never Jace tool executions.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar


class ProviderReliabilityError(RuntimeError):
    """Non-sensitive infrastructure guardrail failure."""


@dataclass(frozen=True)
class ReliabilityPolicy:
    enabled: bool = False
    retries: int = 1
    failure_threshold: int = 3
    cooldown_seconds: float = 45.0
    requests_per_minute: int = 0  # 0 means no rate limit.
    observed_cost_limit_usd: float = 0.0  # 0 means no spend guard.
    pricing_json: str = "{}"

    @classmethod
    def from_settings(cls, settings: Any) -> "ReliabilityPolicy":
        return cls(
            enabled=bool(getattr(settings, "cloud_reliability_enabled", False)),
            retries=max(0, min(3, int(getattr(settings, "cloud_retry_count", 1)))),
            failure_threshold=max(1, int(getattr(settings, "cloud_circuit_failure_threshold", 3))),
            cooldown_seconds=max(1.0, float(getattr(settings, "cloud_circuit_cooldown_seconds", 45.0))),
            requests_per_minute=max(0, int(getattr(settings, "cloud_requests_per_minute", 0))),
            observed_cost_limit_usd=max(0.0, float(getattr(settings, "cloud_observed_cost_limit_usd", 0.0))),
            pricing_json=str(getattr(settings, "cloud_pricing_json", "{}")),
        )


def transient_error(exc: BaseException) -> bool:
    """Retry only a known transient cloud transport status (never arbitrary errors)."""
    message = str(exc).casefold()
    # CloudProviderError messages are sanitized by the provider adapter.
    return any(s in message for s in (
        "http 429", "http 500", "http 502", "http 503", "http 504",
        "request timed out", "network request failed",
    ))


def _cost_rates(policy: ReliabilityPolicy) -> dict[str, dict[str, float]]:
    try:
        value = json.loads(policy.pricing_json)
    except (ValueError, TypeError) as exc:
        raise ProviderReliabilityError("JACE_CLOUD_PRICING_JSON must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ProviderReliabilityError("JACE_CLOUD_PRICING_JSON must be a JSON object.")
    result: dict[str, dict[str, float]] = {}
    for route, rates in value.items():
        if not isinstance(route, str) or route.count(":") < 1 or not isinstance(rates, dict):
            raise ProviderReliabilityError("Cloud pricing entry format is invalid.")
        if not {"input_per_million", "output_per_million"}.issubset(rates):
            raise ProviderReliabilityError("Cloud pricing requires both input/output rates.")
        try:
            iv, ov = float(rates["input_per_million"]), float(rates["output_per_million"])
        except (ValueError, TypeError) as exc:
            raise ProviderReliabilityError("Cloud prices must be numeric.") from exc
        if not all(math.isfinite(v) and v >= 0 for v in (iv, ov)):
            raise ProviderReliabilityError("Cloud prices must be finite and non-negative.")
        result[route] = {"input_per_million": iv, "output_per_million": ov}
    return result


@dataclass
class _RouteState:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    active: int = 0
    consecutive_transient_failures: int = 0
    open_until: float = 0.0
    last_latency_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usage_samples: int = 0
    observed_cost_usd: float = 0.0
    unpriced_usage_samples: int = 0
    last_error_category: str | None = None
    timestamps: deque[float] = field(default_factory=deque)


class ProviderReliability:
    """Single-process telemetry; not a distributed billing or quota authority."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._states: dict[str, _RouteState] = {}
        self._global_observed_cost_usd = 0.0

    def _state(self, route_id: str) -> _RouteState:
        return self._states.setdefault(route_id, _RouteState())

    def circuit_open(self, route_id: str) -> bool:
        return self._state(route_id).open_until > self._clock()

    def _request_slot(self, route_id: str, policy: ReliabilityPolicy) -> float:
        state = self._state(route_id)
        now = self._clock()
        if self.circuit_open(route_id):
            raise ProviderReliabilityError("Cloud model route is temporarily unavailable (circuit open).")
        rates = _cost_rates(policy)
        if policy.observed_cost_limit_usd > 0 and (
            route_id not in rates or not any(rates[route_id].values())
        ):
            raise ProviderReliabilityError("Cloud spend guard requires nonzero verified prices for the selected model route.")
        if (policy.observed_cost_limit_usd > 0
                and self._global_observed_cost_usd >= policy.observed_cost_limit_usd):
            raise ProviderReliabilityError("Observed cloud spend limit reached in this Jace process.")
        if policy.requests_per_minute:
            # Count all attempts (including retries). Rolling 60-second window.
            while state.timestamps and state.timestamps[0] <= now - 60.0:
                state.timestamps.popleft()
            if len(state.timestamps) >= policy.requests_per_minute:
                raise ProviderReliabilityError("Cloud route request-per-minute guard reached.")
            state.timestamps.append(now)
        state.attempts += 1
        state.active += 1
        return now

    def _end(self, route_id: str, started: float, *, success: bool,
             transient: bool = False, usage: dict[str, Any] | None = None,
             policy: ReliabilityPolicy | None = None) -> None:
        state = self._state(route_id)
        state.active = max(0, state.active - 1)
        state.last_latency_ms = round(max(0, self._clock() - started) * 1000, 2)
        if success:
            state.successes += 1
            state.consecutive_transient_failures = 0
            state.last_error_category = None
            state.open_until = 0.0
            if usage is not None and policy is not None:
                # Only terminal provider usage is billed/estimated. No prompt data.
                inp = max(0, int(usage.get("prompt_eval_count") or 0))
                out = max(0, int(usage.get("eval_count") or 0))
                if inp or out:
                    state.usage_samples += 1
                    state.input_tokens += inp
                    state.output_tokens += out
                    rate = _cost_rates(policy).get(route_id)
                    if rate:
                        charge = (inp * rate["input_per_million"] + out * rate["output_per_million"]) / 1_000_000
                        state.observed_cost_usd += charge
                        self._global_observed_cost_usd += charge
                    else:
                        state.unpriced_usage_samples += 1
        else:
            state.failures += 1
            state.last_error_category = "transient_transport" if transient else "non_retryable"
            if transient:
                state.consecutive_transient_failures += 1
                if policy and state.consecutive_transient_failures >= policy.failure_threshold:
                    state.open_until = self._clock() + policy.cooldown_seconds
            else:
                # Bad credentials, policy rejections, invalid models: don't trip transient circuit.
                state.consecutive_transient_failures = 0

    def _cancel(self, route_id: str, started: float) -> None:
        """Free an abandoned/cancelled request without blaming the provider."""
        state = self._state(route_id)
        state.active = max(0, state.active - 1)

    def snapshot(self, policy: ReliabilityPolicy) -> dict[str, Any]:
        """Pure aggregate metadata; no live network health probes or billing claims."""
        now = self._clock()
        routes = []
        for route_id, state in sorted(self._states.items()):
            routes.append({
                "route_id": route_id,
                "status": "circuit_open" if state.open_until > now else (
                    "observed_failure" if state.last_error_category else
                    "observed_success" if state.successes else "unknown"),
                "circuit_seconds_remaining": round(max(0.0, state.open_until - now), 1),
                "attempts": state.attempts,
                "successes": state.successes,
                "failures": state.failures,
                "active": state.active,
                "consecutive_transient_failures": state.consecutive_transient_failures,
                "last_latency_ms": state.last_latency_ms,
                "input_tokens": state.input_tokens,
                "output_tokens": state.output_tokens,
                "usage_samples": state.usage_samples,
                "estimated_cost_usd": round(state.observed_cost_usd, 6),
                "unpriced_usage_samples": state.unpriced_usage_samples,
                "last_error_category": state.last_error_category,
            })
        return {
            "enabled": policy.enabled,
            "scope": "in_process_only",
            "live_probes": False,
            "estimated_cost_only": True,
            "observed_cost_usd": round(self._global_observed_cost_usd, 6),
            "observed_cost_limit_usd": policy.observed_cost_limit_usd,
            "retry_count": policy.retries,
            "requests_per_minute": policy.requests_per_minute,
            "routes": routes,
        }


T = TypeVar("T")


async def guarded_stream(
    *, route_id: str, cloud: bool, policy: ReliabilityPolicy,
    monitor: ProviderReliability,
    factory: Callable[[], AsyncIterator[dict[str, Any]]],
) -> AsyncIterator[dict[str, Any]]:
    if not (cloud and policy.enabled):
        async for chunk in factory():
            yield chunk
        return
    for attempt in range(policy.retries + 1):
        started = monitor._request_slot(route_id, policy)
        visible = False
        complete: dict[str, Any] | None = None
        closed = False
        try:
            async for chunk in factory():
                # Never retry a stream after ANY chunk has escaped this wrapper.
                visible = True
                if chunk.get("done"):
                    complete = chunk
                yield chunk
            if complete is None:
                raise ProviderReliabilityError("Cloud stream ended without a completion marker.")
            monitor._end(route_id, started, success=True, usage=complete, policy=policy)
            closed = True
            return
        except Exception as exc:
            transient = transient_error(exc)
            monitor._end(route_id, started, success=False, transient=transient, policy=policy)
            closed = True
            if visible or not transient or attempt >= policy.retries:
                raise
            # A failed attempt is counted; a newly open circuit blocks the next attempt.
            await asyncio.sleep(min(1.0, 0.2 * (2 ** attempt)))
        finally:
            if not closed:
                # Generator closed / task cancelled. Not counted as provider failure.
                monitor._cancel(route_id, started)


async def guarded_call(
    *, route_id: str, cloud: bool, policy: ReliabilityPolicy,
    monitor: ProviderReliability, factory: Callable[[], Awaitable[T]],
) -> T:
    if not (cloud and policy.enabled):
        return await factory()
    for attempt in range(policy.retries + 1):
        started = monitor._request_slot(route_id, policy)
        closed = False
        try:
            result = await factory()
            monitor._end(route_id, started, success=True, policy=policy)
            closed = True
            return result
        except Exception as exc:
            transient = transient_error(exc)
            monitor._end(route_id, started, success=False, transient=transient, policy=policy)
            closed = True
            if not transient or attempt >= policy.retries:
                raise
            await asyncio.sleep(min(1.0, 0.2 * (2 ** attempt)))
        finally:
            if not closed:
                monitor._cancel(route_id, started)
    raise ProviderReliabilityError("Cloud retry limit reached.")


provider_reliability = ProviderReliability()
