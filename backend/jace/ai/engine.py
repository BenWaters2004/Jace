import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jace.config import settings
from jace.schemas import ChatMessage, ModelInfo


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama service cannot be reached."""


class OllamaRequestError(Exception):
    """Raised when Ollama returns an invalid or failed request."""


def _extract_error_text(
    status_code: int,
    response_text: str,
) -> str:
    try:
        data = json.loads(response_text)

        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except (json.JSONDecodeError, TypeError):
        pass

    if response_text.strip():
        return response_text.strip()

    return f"Ollama returned HTTP {status_code}"


async def get_models() -> list[ModelInfo]:
    url = f"{settings.ollama_base_url}/api/tags"

    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_seconds
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

    except httpx.ConnectError as exc:
        raise OllamaUnavailableError(
            "Could not connect to Ollama."
        ) from exc

    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError(
            "Ollama did not respond in time."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise OllamaRequestError(
            _extract_error_text(
                exc.response.status_code,
                exc.response.text,
            )
        ) from exc

    data = response.json()

    models: list[ModelInfo] = []

    for model in data.get("models", []):
        details = model.get("details") or {}

        models.append(
            ModelInfo(
                name=model.get("name", "Unknown model"),
                size=model.get("size"),
                parameter_size=details.get("parameter_size"),
                quantization_level=details.get(
                    "quantization_level"
                ),
            )
        )

    return models


async def stream_chat(
    model: str,
    messages: list[ChatMessage],
    system_prompt: str,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream raw response chunks from Ollama.

    Ollama returns newline-delimited JSON when stream=True.
    Each yielded dictionary represents one Ollama stream event.
    """

    ollama_messages: list[dict[str, str]] = []

    if system_prompt.strip():
        ollama_messages.append(
            {
                "role": "system",
                "content": system_prompt.strip(),
            }
        )

    ollama_messages.extend(
        {
            "role": message.role,
            "content": message.content,
        }
        for message in messages
    )

    payload = {
        "model": model,
        "messages": ollama_messages,
        "stream": True,
        "keep_alive": settings.ollama_keep_alive,
        "think": settings.ollama_think,
    }

    url = f"{settings.ollama_base_url}/api/chat"

    # We deliberately do not apply a read timeout while streaming.
    # A long response can legitimately remain open for some time.
    timeout = httpx.Timeout(
        connect=10.0,
        read=None,
        write=30.0,
        pool=10.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout
        ) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
            ) as response:

                if response.status_code >= 400:
                    response_body = await response.aread()

                    response_text = response_body.decode(
                        "utf-8",
                        errors="replace",
                    )

                    raise OllamaRequestError(
                        _extract_error_text(
                            response.status_code,
                            response_text,
                        )
                    )

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaRequestError(
                            "Ollama returned malformed streaming data."
                        ) from exc

                    if chunk.get("error"):
                        raise OllamaRequestError(
                            str(chunk["error"])
                        )

                    yield chunk

    except httpx.ConnectError as exc:
        raise OllamaUnavailableError(
            "Could not connect to Ollama. "
            "Make sure Ollama is running."
        ) from exc

    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError(
            "The connection to Ollama timed out."
        ) from exc

    except httpx.HTTPError as exc:
        raise OllamaRequestError(
            f"The Ollama connection failed: {exc}"
        ) from exc