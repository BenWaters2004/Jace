from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ModelCapability = Literal[
    "conversation.fast",
    "reasoning.high",
    "coding.high",
    "vision",
    "research.high",
    "local.private",
    "memory.extract",
    "embedding",
    "reranking",
]


@dataclass(frozen=True, slots=True)
class ModelRoute:
    capability: str
    provider: str
    model: str
    local: bool
    explicit_model: bool = False

    @property
    def route_id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    provider_id: str
    local: bool
    enabled: bool
    operations: tuple[str, ...]
