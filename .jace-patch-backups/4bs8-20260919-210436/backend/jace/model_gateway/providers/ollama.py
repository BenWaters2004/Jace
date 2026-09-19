from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from jace.ai.client import get_ollama_client
from jace.ai.engine import (
    OllamaRequestError,
    OllamaUnavailableError,
    stream_chat as ollama_stream_chat,
    structured_chat as ollama_structured_chat,
    warm_model,
)
from jace.config import settings
from jace.model_gateway.provider import ModelProvider


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class OllamaProvider(ModelProvider):
    provider_id = "ollama"
    local = True
    enabled = True

    @property
    def operations(self) -> tuple[str, ...]:
        return (
            "stream_chat",
            "generate",
            "call_tools",
            "generate_structured",
            "embed",
        )

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
        async for chunk in ollama_stream_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            reasoning_mode=reasoning_mode,
            temperature=temperature,
            tools=tools,
        ):
            yield chunk

    async def structured_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        system_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        return await ollama_structured_chat(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            response_model=response_model,
        )

    async def embed(
        self,
        *,
        model: str,
        text: str,
    ) -> list[float]:
        url = f"{settings.ollama_base_url}/api/embed"
        payload = {
            "model": model,
            "input": text,
            "keep_alive": settings.embedding_keep_alive,
        }

        try:
            client = await get_ollama_client()
            response = await client.post(
                url,
                json=payload,
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                "Could not connect to Ollama for embeddings."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                "Ollama embedding request timed out."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaRequestError(
                f"Ollama embedding request failed with HTTP "
                f"{exc.response.status_code}: {exc.response.text}"
            ) from exc

        body = response.json()
        embeddings = body.get("embeddings") if isinstance(body, dict) else None

        if not isinstance(embeddings, list) or not embeddings:
            raise OllamaRequestError(
                "Ollama returned no embedding vector."
            )

        first = embeddings[0]

        if not isinstance(first, list) or not first:
            raise OllamaRequestError(
                "Ollama returned an invalid embedding vector."
            )

        return [float(value) for value in first]

    async def warm(self, model: str) -> None:
        await warm_model(model)
