from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from jace.config import settings
from jace.model_gateway.provider import ModelProvider
from jace.model_gateway.reliability import (
    ReliabilityPolicy, guarded_stream, guarded_call, provider_reliability,
)
from jace.model_gateway.providers import OllamaProvider, OpenAIProvider, AnthropicProvider
from jace.model_gateway.types import ModelRoute, ProviderInfo
from jace.model_gateway.receipts import traced_stream, traced_call  # JACE_C5B1_PROVIDER_RECEIPTS


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ModelGatewayError(RuntimeError):
    pass


class ModelRouteError(ModelGatewayError):
    pass


class ModelProviderUnavailableError(ModelGatewayError):
    pass


class ModelGateway:
    """Provider-neutral model routing for Jace Core."""

    def __init__(
        self,
        *,
        providers: list[ModelProvider] | None = None,
        route_overrides: dict[str, str] | None = None,
    ) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._route_overrides = dict(route_overrides or {})

        for provider in providers or [OllamaProvider(), OpenAIProvider(), AnthropicProvider()]:
            self.register(provider)

    def register(self, provider: ModelProvider) -> None:
        provider_id = provider.provider_id.strip().lower()

        if not provider_id:
            raise ValueError("Model provider ID cannot be empty.")

        self._providers[provider_id] = provider

    def providers(self) -> list[ProviderInfo]:
        return [
            provider.info()
            for _, provider in sorted(self._providers.items())
        ]

    def _default_model(self, capability: str) -> str:
        defaults = {
            "conversation.fast": settings.default_model,
            "reasoning.high": settings.default_model,
            "coding.high": settings.default_model,
            "vision": settings.vision_model or settings.default_model,
            "research.high": settings.default_model,
            "local.private": settings.default_model,
            "memory.extract": settings.memory_extraction_model,
            "embedding": settings.embedding_model,
            "reranking": settings.default_model,
        }

        model = defaults.get(capability)

        if not model:
            raise ModelRouteError(
                f"No default model is configured for '{capability}'."
            )

        return model

    def _configured_route(self, capability: str) -> str:
        setting_names = {
            "conversation.fast": "model_route_conversation_fast",
            "reasoning.high": "model_route_reasoning_high",
            "coding.high": "model_route_coding_high",
            "vision": "model_route_vision",
            "research.high": "model_route_research_high",
            "local.private": "model_route_local_private",
            "memory.extract": "model_route_memory_extract",
            "embedding": "model_route_embedding",
            "reranking": "model_route_reranking",
        }

        if capability in self._route_overrides:
            return self._route_overrides[capability].strip()

        setting_name = setting_names.get(capability)

        if setting_name is None:
            raise ModelRouteError(
                f"Unknown model capability class: {capability}"
            )

        return str(getattr(settings, setting_name, "") or "").strip()

    def _parse_route(
        self,
        route: str,
        *,
        capability: str,
        explicit_model: bool,
    ) -> ModelRoute:
        route = route.strip()

        if ":" not in route:
            raise ModelRouteError(
                "Model routes must use provider:model syntax."
            )

        provider_id, model = route.split(":", 1)
        provider_id = provider_id.strip().lower()
        model = model.strip()

        if not provider_id or not model:
            raise ModelRouteError(
                "Model routes require both provider and model."
            )

        provider = self._providers.get(provider_id)

        if provider is None or not provider.enabled:
            raise ModelProviderUnavailableError(
                f"Model provider '{provider_id}' is not registered/enabled."
            )

        if capability == "local.private" and not provider.local:
            raise ModelRouteError(
                "local.private may only resolve to a local model provider."
            )

        return ModelRoute(
            capability=capability,
            provider=provider_id,
            model=model,
            local=provider.local,
            explicit_model=explicit_model,
        )

    def resolve(
        self,
        capability: str,
        *,
        requested_model: str | None = None,
        local_only: bool = False,
    ) -> ModelRoute:
        if requested_model and requested_model.strip():
            requested = requested_model.strip()

            if ":" in requested and requested.split(":", 1)[0].lower() in self._providers:
                route = self._parse_route(
                    requested,
                    capability=capability,
                    explicit_model=True,
                )
            else:
                provider_id = settings.model_gateway_default_provider.strip().lower()
                route = self._parse_route(
                    f"{provider_id}:{requested}",
                    capability=capability,
                    explicit_model=True,
                )
        else:
            configured = self._configured_route(capability)

            if configured:
                route = self._parse_route(
                    configured,
                    capability=capability,
                    explicit_model=False,
                )
            else:
                provider_id = settings.model_gateway_default_provider.strip().lower()

                if capability == "local.private":
                    provider_id = "ollama"

                route = self._parse_route(
                    f"{provider_id}:{self._default_model(capability)}",
                    capability=capability,
                    explicit_model=False,
                )

        if local_only and not route.local:
            raise ModelRouteError(
                f"Capability '{capability}' requires a local provider."
            )

        return route

    def _provider(self, route: ModelRoute) -> ModelProvider:
        provider = self._providers.get(route.provider)

        if provider is None or not provider.enabled:
            raise ModelProviderUnavailableError(
                f"Model provider '{route.provider}' is unavailable."
            )

        return provider

    # JACE_4BS8_PRIVACY_ENFORCEMENT
    def _local_fallback(self, capability: str) -> ModelRoute:
        candidates = [
            provider
            for provider in self._providers.values()
            if provider.enabled and provider.local
        ]
        candidates.sort(
            key=lambda provider: (
                provider.provider_id != "ollama",
                provider.provider_id,
            )
        )

        if not candidates:
            raise ModelProviderUnavailableError(
                "Privacy policy requires local processing, "
                "but no local model provider is available."
            )

        provider = candidates[0]

        return ModelRoute(
            capability=capability,
            provider=provider.provider_id,
            model=self._default_model(capability),
            local=True,
            explicit_model=False,
        )

    def _prepare_privacy(
        self,
        *,
        route: ModelRoute,
        capability: str,
        payload: dict[str, Any],
        privacy_classification: str | None,
        privacy_mode: str | None,
    ):
        from jace.privacy import privacy_gateway

        provider = self._provider(route)

        decision = privacy_gateway.prepare_for_provider(
            payload,
            provider_local=provider.local,
            provider_supports_protected_cloud=(
                provider.supports_protected_cloud
            ),
            classification_hint=privacy_classification,
            requested_mode=privacy_mode,
        )

        if decision.require_local and not route.local:
            route = self._local_fallback(capability)
            provider = self._provider(route)

            decision = privacy_gateway.prepare_for_provider(
                payload,
                provider_local=True,
                provider_supports_protected_cloud=(
                    provider.supports_protected_cloud
                ),
                classification_hint=privacy_classification,
                requested_mode=privacy_mode,
            )

        return route, provider, decision

    async def stream_chat(
        self,
        *,
        capability: str = "conversation.fast",
        model: str | None = None,
        messages: list[dict[str, Any]],
        system_prompt: str,
        reasoning_mode: str = "fast",
        temperature: float = 0.4,
        tools: list[dict[str, Any]] | None = None,
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        route = self.resolve(
            capability,
            requested_model=model,
            local_only=local_only,
        )
        requested_route_id = route.route_id
        route, provider, privacy = self._prepare_privacy(
            route=route,
            capability=capability,
            payload={
                "messages": messages,
                "system_prompt": system_prompt,
                "tools": tools,
            },
            privacy_classification=privacy_classification,
            privacy_mode=privacy_mode,
        )

        prepared = privacy.transformed_payload

        async def _send_model_request():
            # C5B.1: factory runs per real adapter attempt, including retries.
            async for item in traced_stream(
                route=route, capability=capability, operation="stream_chat",
                privacy=privacy, requested_route=requested_route_id,
                stream=provider.stream_chat(
                    model=route.model,
                    messages=prepared["messages"],
                    system_prompt=prepared["system_prompt"],
                    reasoning_mode=reasoning_mode,
                    temperature=temperature,
                    tools=prepared["tools"],
                ),
            ):
                yield item

        async for chunk in guarded_stream(
            route_id=route.route_id,
            cloud=not route.local,
            policy=ReliabilityPolicy.from_settings(settings),
            monitor=provider_reliability,
            factory=_send_model_request,
        ):
            if isinstance(chunk, dict):
                chunk.setdefault("model_provider", route.provider)
                chunk.setdefault("model_capability", capability)
                chunk.setdefault("model", route.model)
                chunk.setdefault(
                    "privacy_classification",
                    privacy.classification,
                )
                chunk.setdefault("privacy_mode", privacy.mode)
                chunk.setdefault("privacy_action", privacy.action)

            yield chunk

    async def generate(
        self,
        *,
        capability: str = "conversation.fast",
        model: str | None = None,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
        reasoning_mode: str = "fast",
        temperature: float = 0.4,
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> str:
        parts: list[str] = []

        async for chunk in self.stream_chat(
            capability=capability,
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=None,
            local_only=local_only,
            privacy_classification=privacy_classification,
            privacy_mode=privacy_mode,
        ):
            message = chunk.get("message") or {}
            content = message.get("content") or ""

            if content:
                parts.append(str(content))

        return "".join(parts)

    async def call_tools(
        self,
        *,
        capability: str = "conversation.fast",
        model: str | None = None,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        reasoning_mode: str = "fast",
        temperature: float = 0.4,
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for chunk in self.stream_chat(
            capability=capability,
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tools,
            local_only=local_only,
            privacy_classification=privacy_classification,
            privacy_mode=privacy_mode,
        ):
            yield chunk

    async def generate_structured(
        self,
        *,
        capability: str = "memory.extract",
        model: str | None = None,
        messages: list[dict[str, str]],
        system_prompt: str,
        response_model: type[StructuredModel],
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> StructuredModel:
        route = self.resolve(
            capability,
            requested_model=model,
            local_only=local_only,
        )
        requested_route_id = route.route_id
        route, provider, privacy = self._prepare_privacy(
            route=route,
            capability=capability,
            payload={
                "messages": messages,
                "system_prompt": system_prompt,
            },
            privacy_classification=privacy_classification,
            privacy_mode=privacy_mode,
        )

        prepared = privacy.transformed_payload

        async def _send_structured():
            return await traced_call(
                route=route, capability=capability, operation="structured_chat",
                privacy=privacy, requested_route=requested_route_id,
                invoke=lambda: provider.structured_chat(
                    model=route.model,
                    messages=prepared["messages"],
                    system_prompt=prepared["system_prompt"],
                    response_model=response_model,
                ),
            )

        return await guarded_call(
            route_id=route.route_id, cloud=not route.local,
            policy=ReliabilityPolicy.from_settings(settings),
            monitor=provider_reliability, factory=_send_structured,
        )

    async def embed_with_route(
        self,
        text: str,
        *,
        capability: str = "embedding",
        model: str | None = None,
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> tuple[list[float], str]:
        """Return vector and actual route after privacy policy is enforced."""
        route = self.resolve(capability, requested_model=model, local_only=local_only)
        requested_route_id = route.route_id
        route, provider, privacy = self._prepare_privacy(
            route=route, capability=capability, payload={"text": text},
            privacy_classification=privacy_classification, privacy_mode=privacy_mode,
        )
        vector = await traced_call(
            route=route, capability=capability, operation="embedding",
            privacy=privacy, requested_route=requested_route_id,
            invoke=lambda: provider.embed(
                model=route.model, text=privacy.transformed_payload["text"]
            ),
        )
        return vector, route.route_id

    async def embed(
        self,
        text: str,
        *,
        capability: str = "embedding",
        model: str | None = None,
        local_only: bool = False,
        privacy_classification: str | None = None,
        privacy_mode: str | None = None,
    ) -> list[float]:
        route = self.resolve(
            capability,
            requested_model=model,
            local_only=local_only,
        )
        requested_route_id = route.route_id
        route, provider, privacy = self._prepare_privacy(
            route=route,
            capability=capability,
            payload={"text": text},
            privacy_classification=privacy_classification,
            privacy_mode=privacy_mode,
        )

        async def _send_embedding():
            return await traced_call(
                route=route, capability=capability, operation="embedding",
                privacy=privacy, requested_route=requested_route_id,
                invoke=lambda: provider.embed(
                    model=route.model,
                    text=privacy.transformed_payload["text"],
                ),
            )

        return await guarded_call(
            route_id=route.route_id, cloud=not route.local,
            policy=ReliabilityPolicy.from_settings(settings),
            monitor=provider_reliability, factory=_send_embedding,
        )

    async def warm(
        self,
        capability: str,
        *,
        model: str | None = None,
    ) -> ModelRoute:
        route = self.resolve(
            capability,
            requested_model=model,
        )
        provider = self._provider(route)
        await provider.warm(route.model)
        return route


model_gateway = ModelGateway()
