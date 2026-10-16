"""Direct Anthropic Messages adapter for Jace's model gateway."""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from jace.config import settings
from jace.model_gateway.provider import ModelProvider
from jace.model_gateway.providers.cloud_common import (
    CloudProviderError, anthropic_messages, anthropic_tools, api_error,
    iter_sse, normalized_tool_call, parsed_args, structured_instructions,
    validate_structured,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class AnthropicProvider(ModelProvider):
    provider_id = "anthropic"
    local = False
    supports_protected_cloud = True

    def __init__(self) -> None:
        self.enabled = bool(settings.anthropic_api_key.strip())

    @property
    def operations(self) -> tuple[str, ...]:
        return ("stream_chat", "generate", "call_tools", "generate_structured")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={"x-api-key": settings.anthropic_api_key,
                     "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10, read=settings.request_timeout_seconds, write=30, pool=10),
            follow_redirects=False,
        )

    async def stream_chat(
        self, *, model: str, messages: list[dict[str, Any]], system_prompt: str,
        reasoning_mode: str, temperature: float, tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        del reasoning_mode, temperature
        payload: dict[str, Any] = {
            "model": model, "max_tokens": settings.cloud_max_output_tokens,
            "messages": anthropic_messages(messages), "stream": True,
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
        if tools:
            payload["tools"] = anthropic_tools(tools)
        started = time.monotonic()
        tokens_in = tokens_out = 0
        done_reason = "stop"
        buffered_text: list[str] = []
        current_tools: dict[int, dict[str, Any]] = {}
        finished = False
        try:
            async with self._client() as client:
                async with client.stream("POST", "/v1/messages", json=payload) as response:
                    response.raise_for_status()
                    async for kind, item in iter_sse(response.aiter_lines()):
                        kind = item.get("type") or kind
                        if kind == "error":
                            raise CloudProviderError("Anthropic returned a stream error (details withheld).")
                        if kind == "message_start":
                            tokens_in = int(((item.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
                        elif kind == "message_delta":
                            usage = item.get("usage") or {}
                            tokens_out = int(usage.get("output_tokens") or tokens_out)
                            reason = (item.get("delta") or {}).get("stop_reason")
                            if reason:
                                done_reason = "tool_calls" if reason == "tool_use" else ("length" if reason == "max_tokens" else "stop")
                        elif kind == "content_block_start":
                            idx = int(item.get("index") or 0)
                            block = item.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                current_tools[idx] = {"id": block.get("id") or "", "name": block.get("name") or "", "json": "", "input": block.get("input") or {}}
                            elif block.get("type") == "text" and block.get("text"):
                                if tools:
                                    buffered_text.append(block["text"])
                                else:
                                    yield {"message": {"content": block["text"]}, "done": False}
                        elif kind == "content_block_delta":
                            idx = int(item.get("index") or 0)
                            delta = item.get("delta") or {}
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                if tools:
                                    buffered_text.append(delta["text"])
                                else:
                                    yield {"message": {"content": delta["text"]}, "done": False}
                            elif delta.get("type") == "input_json_delta" and idx in current_tools:
                                current_tools[idx]["json"] += delta.get("partial_json") or ""
                        elif kind == "message_stop":
                            finished = True
        except CloudProviderError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise api_error("Anthropic", exc) from exc
        if not finished:
            raise CloudProviderError("Anthropic stream did not complete.")
        if current_tools:
            calls = []
            for _, item in sorted(current_tools.items()):
                if not item["id"] or not item["name"]:
                    raise CloudProviderError("Anthropic returned an incomplete tool call.")
                args = parsed_args(item["json"]) if item["json"] else parsed_args(item["input"])
                calls.append(normalized_tool_call(name=item["name"], arguments=args, call_id=item["id"]))
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
            "model": model, "max_tokens": settings.cloud_max_output_tokens,
            "system": system_prompt + "\n\n" + structured_instructions(response_model),
            "messages": anthropic_messages(messages),
        }
        try:
            async with self._client() as client:
                response = await client.post("/v1/messages", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise api_error("Anthropic", exc) from exc
        content = "".join(
            item.get("text", "") for item in data.get("content") or [] if item.get("type") == "text"
        )
        if not content:
            raise CloudProviderError("Anthropic returned no structured content.")
        return validate_structured(content, response_model)

    async def embed(self, *, model: str, text: str) -> list[float]:
        del model, text
        raise CloudProviderError("Anthropic does not expose a native embeddings route in this adapter.")
