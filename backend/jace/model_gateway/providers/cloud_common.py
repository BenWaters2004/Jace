"""Small, provider-neutral cloud transport helpers for Jace's existing gateway.

Cloud errors deliberately omit provider response bodies and request payloads.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel


class CloudProviderError(RuntimeError):
    """Non-secret-bearing cloud provider error for presentation and audit."""


def api_error(provider: str, exc: Exception) -> CloudProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        return CloudProviderError(
            f"{provider} returned HTTP {exc.response.status_code}; "
            "check provider access, model ID, quotas and provider status."
        )
    if isinstance(exc, httpx.TimeoutException):
        return CloudProviderError(f"{provider} request timed out.")
    if isinstance(exc, httpx.RequestError):
        return CloudProviderError(f"{provider} network request failed.")
    return CloudProviderError(f"{provider} returned an unexpected response.")


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Decode SSE records, including multi-line data and keep-alives."""
    event = "message"
    data: list[str] = []
    async for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data:
                payload = "\n".join(data)
                if payload == "[DONE]":
                    return
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise CloudProviderError("Provider returned malformed streaming JSON.") from exc
                if not isinstance(parsed, dict):
                    raise CloudProviderError("Provider returned an invalid streaming event.")
                yield event, parsed
            event = "message"
            data = []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        payload = "\n".join(data)
        if payload != "[DONE]":
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise CloudProviderError("Provider returned malformed streaming JSON.") from exc
            if not isinstance(parsed, dict):
                raise CloudProviderError("Provider returned an invalid streaming event.")
            yield event, parsed


def text_only(message: dict[str, Any]) -> str:
    """Fail closed on modalities that this initial cloud adapter cannot render."""
    if message.get("images"):
        raise CloudProviderError("Cloud image inputs are not supported in Phase C1.")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise CloudProviderError("Cloud adapter currently supports text messages only.")
    return content


def tool_call_id(raw: dict[str, Any], index: int) -> str:
    existing = raw.get("id")
    return existing if isinstance(existing, str) and existing else f"jace_call_{index}"


def normalized_tool_call(*, name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def parsed_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise CloudProviderError("Provider returned malformed tool arguments.") from exc
    if not isinstance(value, dict):
        raise CloudProviderError("Provider returned a non-object tool argument payload.")
    return value


def openai_messages(messages: list[dict[str, Any]], system_prompt: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if system_prompt.strip():
        result.append({"role": "developer", "content": system_prompt.strip()})
    last_calls: list[str] = []
    for msg in messages:
        role = msg.get("role")
        content = text_only(msg)
        if role in ("user", "assistant", "system"):
            item: dict[str, Any] = {"role": role, "content": content}
            if role == "assistant" and msg.get("tool_calls"):
                calls = []
                last_calls = []
                for i, raw in enumerate(msg["tool_calls"]):
                    name = raw.get("function", {}).get("name")
                    if not name:
                        raise CloudProviderError("Assistant tool call has no name.")
                    call_id = tool_call_id(raw, i)
                    last_calls.append(call_id)
                    calls.append({"type": "function", "id": call_id, "function": {
                        "name": name,
                        "arguments": json.dumps(parsed_args(raw["function"].get("arguments")), ensure_ascii=False),
                    }})
                item["tool_calls"] = calls
            result.append(item)
        elif role == "tool":
            call_id = msg.get("tool_call_id") or (last_calls.pop(0) if last_calls else None)
            if not call_id:
                raise CloudProviderError("Cloud tool result is missing the matching call ID.")
            result.append({"role": "tool", "tool_call_id": call_id, "content": content})
        else:
            raise CloudProviderError("Unsupported conversation message role.")
    return result


def anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    last_calls: list[str] = []
    for msg in messages:
        role = msg.get("role")
        content = text_only(msg)
        if role == "system":
            raise CloudProviderError("System messages must be provided through the system prompt.")
        if role in ("assistant", "user"):
            if role == "assistant" and msg.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                last_calls = []
                for i, raw in enumerate(msg["tool_calls"]):
                    name = raw.get("function", {}).get("name")
                    if not name:
                        raise CloudProviderError("Assistant tool call has no name.")
                    call_id = tool_call_id(raw, i)
                    last_calls.append(call_id)
                    blocks.append({"type": "tool_use", "id": call_id,
                                   "name": name, "input": parsed_args(raw["function"].get("arguments"))})
                result.append({"role": "assistant", "content": blocks})
            else:
                result.append({"role": role, "content": content})
        elif role == "tool":
            call_id = msg.get("tool_call_id") or (last_calls.pop(0) if last_calls else None)
            if not call_id:
                raise CloudProviderError("Cloud tool result is missing the matching call ID.")
            block = {"type": "tool_result", "tool_use_id": call_id, "content": content}
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})
        else:
            raise CloudProviderError("Unsupported conversation message role.")
    if not result:
        result = [{"role": "user", "content": " "}]
    return result


def openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    for tool in tools or []:
        if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
            raise CloudProviderError("Unsupported Jace tool schema for OpenAI.")
    return tools or []


def anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    results = []
    for tool in tools or []:
        if tool.get("type") != "function":
            raise CloudProviderError("Unsupported Jace tool schema for Anthropic.")
        item = tool.get("function") or {}
        name = item.get("name")
        if not name:
            raise CloudProviderError("A Jace tool schema has no name.")
        results.append({"name": name, "description": item.get("description") or "",
                        "input_schema": item.get("parameters") or {"type": "object", "properties": {}}})
    return results


def structured_instructions(response_model: type[BaseModel]) -> str:
    return ("Return exactly one JSON object, with no Markdown fences, matching this JSON Schema. "
            "Never invent unsupported facts. Schema: "
            + json.dumps(response_model.model_json_schema(), separators=(",", ":")))


def validate_structured(text: str, response_model: type[BaseModel]) -> BaseModel:
    value = text.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    try:
        return response_model.model_validate_json(value)
    except Exception as exc:
        raise CloudProviderError("Cloud structured output failed schema validation.") from exc
