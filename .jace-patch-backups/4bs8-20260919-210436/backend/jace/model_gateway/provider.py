from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from jace.model_gateway.types import ProviderInfo


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ModelProvider(ABC):
    provider_id: str
    local: bool = False
    enabled: bool = True

    @property
    @abstractmethod
    def operations(self) -> tuple[str, ...]:
        raise NotImplementedError

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self.provider_id,
            local=self.local,
            enabled=self.enabled,
            operations=self.operations,
        )

    @abstractmethod
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system_prompt: str,
        reasoning_mode: str,
        temperature: float,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def structured_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        system_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        raise NotImplementedError

    @abstractmethod
    async def embed(
        self,
        *,
        model: str,
        text: str,
    ) -> list[float]:
        raise NotImplementedError

    async def warm(self, model: str) -> None:
        del model
