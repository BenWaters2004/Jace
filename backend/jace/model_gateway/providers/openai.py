"""Direct OpenAI Chat Completions adapter for Jace's existing gateway.

Uses httpx already supplied by Jace. Credentials never appear in exceptions or
status payloads. We intentionally avoid model-specific temperature/reasoning
arguments until model capability profiles are introduced in Phase C4.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from jace.config import settings
from jace.model_gateway.provider import ModelProvider
from jace.model_gateway.providers.cloud_common import (
    CloudProviderError, api_error, iter_sse, normalized_tool_call,
    openai_messages, openai_tools, parsed_args, structured_instructions,
    validate_structured,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class OpenAIProvider(ModelProvider):
    provider_id = "openai"
    local = False
    supports_protected_cloud = True

    def __init__(self) -> None:
        self.enabled = bool(settings.openai_api_key.strip())

    @property
    def operations(self) -> tuple[str, ...]:
        return ("stream_chat", "generate", "call_tools", "generate_structured", "embed")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.openai.com",
            headers={"Authorization": f"Bearer {settings.openai_api_key}",
                     "Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10, read=settings.request_timeout_seconds, write=30, pool=10),
            follow_redirects=False,
        )

    async def stream_chat(
        self, *, model: str, messages: list[dict[str, Any]], system_prompt: str,
        reasoning_mode: str, temperature: float, tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        del reasoning_mode, temperature  # Model-specific controls come in Phase C4.
        payload: dict[str, Any] = {
            "model": model, "stream": True,
            "messages": openai_messages(messages, system_prompt),
            "stream_options": {"include_usage": True},
            "max_completion_tokens": settings.cloud_max_output_tokens,
        }
        if tools:
            payload["tools"] = openai_tools(tools)
            payload["tool_choice"] = "auto"
        started = time.monotonic()
        tokens_in = 0
        tokens_out = 0
        done_reason = "stop"
        buffered_text: list[str] = []
        partial_tools: dict[int, dict[str, str]] = {}
        finished = False
        try:
            async with self._client() as client:
                async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    async for _kind, item in iter_sse(response.aiter_lines()):
                        if "error" in item:
                            raise CloudProviderError("OpenAI returned a stream error (details withheld).")
                        usage = item.get("usage") or {}
                        tokens_in = int(usage.get("prompt_tokens") or tokens_in)
                        tokens_out = int(usage.get("completion_tokens") or tokens_out)
                        for choice in item.get("choices") or []:
                            delta = choice.get("delta") or {}
                            content = delta.get("content") or ""
                            if content:
                                if tools:
                                    buffered_text.append(content)
                                else:
                                    yield {"message": {"content": content}, "done": False}
                            for entry in delta.get("tool_calls") or []:
                                idx = int(entry.get("index") or 0)
                                stored = partial_tools.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if entry.get("id"):
                                    stored["id"] = entry["id"]
                                fn = entry.get("function") or {}
                                stored["name"] += fn.get("name") or ""
                                stored["arguments"] += fn.get("arguments") or ""
                            if choice.get("finish_reason"):
                                done_reason = choice["finish_reason"]
                    finished = True
        except CloudProviderError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise api_error("OpenAI", exc) from exc
        if not finished:
            raise CloudProviderError("OpenAI stream did not complete.")
        if partial_tools:
            calls = []
            for idx, item in sorted(partial_tools.items()):
                if not item["id"] or not item["name"]:
                    raise CloudProviderError("OpenAI returned an incomplete tool call.")
                calls.append(normalized_tool_call(
                    name=item["name"], arguments=parsed_args(item["arguments"]), call_id=item["id"]
                ))
            yield {"message": {"tool_calls": calls}, "done": False}
        elif buffered_text:
            yield {"message": {"content": "".join(buffered_text)}, "done": False}
        yield {"model": model, "message": {}, "done": True, "done_reason": done_reason,
               "total_duration": int((time.monotonic()-started)*1e9),
               "prompt_eval_count": tokens_in, "eval_count": tokens_out}

    async def structured_chat(
        self, *, model: str, messages: list[dict[str, str]], system_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        payload = {
            "model": model,
            "messages": openai_messages(
                messages, system_prompt + "\n\n" + structured_instructions(response_model)),
            "max_completion_tokens": settings.cloud_max_output_tokens,
        }
        try:
            async with self._client() as client:
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise api_error("OpenAI", exc) from exc
        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else None)
        if not isinstance(content, str):
            raise CloudProviderError("OpenAI returned no structured content.")
        return validate_structured(content, response_model)

    async def embed(self, *, model: str, text: str) -> list[float]:
        try:
            async with self._client() as client:
                response = await client.post("/v1/embeddings", json={"model": model, "input": text})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise api_error("OpenAI", exc) from exc
        items = data.get("data") or []
        vector = items[0].get("embedding") if items else None
        if not isinstance(vector, list) or not vector:
            raise CloudProviderError("OpenAI returned no embedding vector.")
        try:
            return [float(value) for value in vector]
        except (ValueError, TypeError) as exc:
            raise CloudProviderError("OpenAI returned an invalid embedding vector.") from exc
