from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from jace.model_gateway.gateway import (
    ModelGateway,
    ModelGatewayError,
    ModelProviderUnavailableError,
    ModelRouteError,
    model_gateway,
)
from jace.model_gateway.types import ModelRoute


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def resolve_model_route(
    capability: str,
    *,
    model: str | None = None,
    local_only: bool = False,
) -> ModelRoute:
    return model_gateway.resolve(
        capability,
        requested_model=model,
        local_only=local_only,
    )


def resolved_model_name(capability: str) -> str:
    return model_gateway.resolve(capability).model


async def stream_chat(
    *,
    model: str | None = None,
    messages: list[dict[str, Any]],
    system_prompt: str,
    reasoning_mode: str = "fast",
    temperature: float = 0.4,
    tools: list[dict[str, Any]] | None = None,
    capability: str = "conversation.fast",
    local_only: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    async for chunk in model_gateway.stream_chat(
        capability=capability,
        model=model,
        messages=messages,
        system_prompt=system_prompt,
        reasoning_mode=reasoning_mode,
        temperature=temperature,
        tools=tools,
        local_only=local_only,
    ):
        yield chunk


async def structured_chat(
    *,
    model: str | None = None,
    messages: list[dict[str, str]],
    system_prompt: str,
    response_model: type[StructuredModel],
    capability: str = "memory.extract",
    local_only: bool = False,
) -> StructuredModel:
    return await model_gateway.generate_structured(
        capability=capability,
        model=model,
        messages=messages,
        system_prompt=system_prompt,
        response_model=response_model,
        local_only=local_only,
    )


async def embed_text(
    text: str,
    *,
    model: str | None = None,
    capability: str = "embedding",
    local_only: bool = False,
) -> list[float]:
    return await model_gateway.embed(
        text,
        capability=capability,
        model=model,
        local_only=local_only,
    )


__all__ = [
    "ModelGateway",
    "ModelGatewayError",
    "ModelProviderUnavailableError",
    "ModelRoute",
    "ModelRouteError",
    "embed_text",
    "model_gateway",
    "resolve_model_route",
    "resolved_model_name",
    "stream_chat",
    "structured_chat",
]
