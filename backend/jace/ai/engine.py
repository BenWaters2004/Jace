import json
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from jace.ai.client import get_ollama_client
from jace.config import settings
from jace.schemas import ModelInfo


class OllamaUnavailableError(Exception):
    pass


class OllamaRequestError(Exception):
    pass


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def _extract_error_text(status_code: int, response_text: str) -> str:
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except (json.JSONDecodeError, TypeError):
        pass
    return response_text.strip() or f"Ollama returned HTTP {status_code}"


def generation_options(reasoning_mode: str, temperature: float) -> tuple[bool, dict]:
    """Map the UI's simple reasoning modes to predictable Ollama behaviour."""
    if reasoning_mode == "deep":
        return True, {"temperature": min(temperature, 0.5), "num_predict": 3072, "num_ctx": settings.ollama_num_ctx}
    if reasoning_mode == "balanced":
        return False, {"temperature": temperature, "num_predict": 1536, "num_ctx": settings.ollama_num_ctx}
    return False, {"temperature": min(temperature, 0.5), "num_predict": 768, "num_ctx": settings.ollama_num_ctx}


def _copy_chat_message(message: dict[str, Any]) -> dict[str, Any]:
    """
    Preserve fields used by Ollama's tool-calling loop instead of reducing every
    message to only role/content.
    """
    copied: dict[str, Any] = {"role": message["role"]}
    for key in ("content", "thinking", "tool_calls", "tool_name"):
        if key in message and message[key] is not None:
            copied[key] = message[key]
    if "content" not in copied:
        copied["content"] = ""
    return copied


async def get_models() -> list[ModelInfo]:
    url = f"{settings.ollama_base_url}/api/tags"
    try:
        client = await get_ollama_client()
        response = await client.get(url, timeout=settings.request_timeout_seconds)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError("Could not connect to Ollama.") from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("Ollama did not respond in time.") from exc
    except httpx.HTTPStatusError as exc:
        raise OllamaRequestError(_extract_error_text(exc.response.status_code, exc.response.text)) from exc

    models: list[ModelInfo] = []
    for model in response.json().get("models", []):
        details = model.get("details") or {}
        models.append(
            ModelInfo(
                name=model.get("name", "Unknown model"),
                size=model.get("size"),
                parameter_size=details.get("parameter_size"),
                quantization_level=details.get("quantization_level"),
            )
        )
    return models


async def warm_model(model: str) -> None:
    """Preload a model into Ollama without generating user-visible text."""
    url = f"{settings.ollama_base_url}/api/chat"
    timeout = httpx.Timeout(
        connect=10.0,
        read=settings.preload_timeout_seconds,
        write=30.0,
        pool=10.0,
    )
    payload = {
        "model": model,
        "keep_alive": settings.ollama_keep_alive,
    }

    try:
        client = await get_ollama_client()
        response = await client.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError("Could not connect to Ollama while preloading the model.") from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("Ollama model preload timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise OllamaRequestError(
            _extract_error_text(exc.response.status_code, exc.response.text)
        ) from exc


async def structured_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    system_prompt: str,
    response_model: type[StructuredModel],
) -> StructuredModel:
    ollama_messages: list[dict[str, str]] = []
    if system_prompt.strip():
        ollama_messages.append({"role": "system", "content": system_prompt.strip()})
    ollama_messages.extend({"role": m["role"], "content": m["content"]} for m in messages)

    payload = {
        "model": model,
        "messages": ollama_messages,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "think": False,
        "format": response_model.model_json_schema(),
        "options": {"temperature": 0, "num_ctx": settings.ollama_num_ctx},
    }

    url = f"{settings.ollama_base_url}/api/chat"
    timeout = httpx.Timeout(connect=10.0, read=settings.request_timeout_seconds, write=30.0, pool=10.0)

    try:
        client = await get_ollama_client()
        response = await client.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError("Could not connect to Ollama.") from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("The structured Ollama request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise OllamaRequestError(_extract_error_text(exc.response.status_code, exc.response.text)) from exc

    try:
        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise OllamaRequestError("Ollama returned an empty structured response.")
        return response_model.model_validate_json(content)
    except ValidationError as exc:
        raise OllamaRequestError("Ollama returned structured data that failed validation.") from exc


async def stream_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    reasoning_mode: str = "fast",
    temperature: float = 0.4,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream an Ollama chat request. If tools are supplied, tool_calls are left in
    the raw chunks so the Phase 4 agent loop can accumulate and execute them.
    """
    ollama_messages: list[dict[str, Any]] = []
    if system_prompt.strip():
        ollama_messages.append({"role": "system", "content": system_prompt.strip()})
    ollama_messages.extend(_copy_chat_message(message) for message in messages)

    think, options = generation_options(reasoning_mode, temperature)
    payload: dict[str, Any] = {
        "model": model,
        "messages": ollama_messages,
        "stream": True,
        "keep_alive": settings.ollama_keep_alive,
        "think": think,
        "options": options,
    }
    if tools:
        payload["tools"] = tools

    url = f"{settings.ollama_base_url}/api/chat"
    timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

    try:
        client = await get_ollama_client()
        async with client.stream("POST", url, json=payload, timeout=timeout) as response:
            if response.status_code >= 400:
                raw = (await response.aread()).decode("utf-8", errors="replace")
                raise OllamaRequestError(_extract_error_text(response.status_code, raw))

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise OllamaRequestError("Ollama returned malformed streaming data.") from exc
                if chunk.get("error"):
                    raise OllamaRequestError(str(chunk["error"]))
                yield chunk

    except httpx.ConnectError as exc:
        raise OllamaUnavailableError("Could not connect to Ollama. Make sure Ollama is running.") from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("The connection to Ollama timed out.") from exc
    except httpx.HTTPError as exc:
        raise OllamaRequestError(f"The Ollama connection failed: {exc}") from exc
