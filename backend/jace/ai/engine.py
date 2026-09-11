import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from jace.ai.client import get_ollama_client
from jace.config import settings
from jace.schemas import ModelInfo


logger = logging.getLogger("uvicorn.error")


class OllamaUnavailableError(Exception):
    pass


class OllamaRequestError(Exception):
    pass


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)

# Some Ollama/model combinations implement JSON mode through a grammar sampler.
# If even the simple JSON grammar is rejected for a model, remember that for the
# lifetime of this backend process and use prompt-only JSON on later calls.
_json_mode_disabled_models: set[str] = set()


def _extract_error_text(status_code: int, response_text: str) -> str:
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            if isinstance(error, dict):
                message = error.get("message")
                if message:
                    return str(message)
            return str(error)
    except (json.JSONDecodeError, TypeError):
        pass
    return response_text.strip() or f"Ollama returned HTTP {status_code}"


def generation_options(reasoning_mode: str, temperature: float) -> tuple[bool, dict]:
    """Map the UI's simple reasoning modes to predictable Ollama behaviour."""
    if reasoning_mode == "deep":
        return True, {
            "temperature": min(temperature, 0.5),
            "num_predict": 3072,
            "num_ctx": settings.ollama_num_ctx,
        }
    if reasoning_mode == "balanced":
        return False, {
            "temperature": temperature,
            "num_predict": 1536,
            "num_ctx": settings.ollama_num_ctx,
        }
    return False, {
        "temperature": min(temperature, 0.5),
        "num_predict": 768,
        "num_ctx": settings.ollama_num_ctx,
    }


def _copy_chat_message(message: dict[str, Any]) -> dict[str, Any]:
    """
    Preserve fields used by Ollama's tool-calling loop instead of reducing every
    message to only role/content.
    """
    copied: dict[str, Any] = {"role": message["role"]}
    for key in ("content", "thinking", "tool_calls", "tool_name", "images"):
        if key in message and message[key] is not None:
            copied[key] = message[key]
    if "content" not in copied:
        copied["content"] = ""
    return copied


def _looks_like_format_rejection(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "failed to parse grammar",
            "failed to initialize samplers",
            "grammar",
            "json format",
            "response format",
        )
    )


def _structured_output_contract(response_model: type[StructuredModel]) -> str:
    """
    Put the schema in the prompt rather than passing the full Pydantic schema as
    Ollama's `format` value. Complex JSON Schema -> grammar conversion is the
    source of the repeated `failed to parse grammar` failure seen with some
    local model/Ollama combinations.
    """
    schema = json.dumps(
        response_model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "STRUCTURED OUTPUT CONTRACT\n"
        "Return exactly one JSON value and no prose, Markdown, or code fence.\n"
        "The JSON must validate against this schema:\n"
        f"{schema}\n"
        "If there is no meaningful result, return the schema's valid empty/default form.\n"
        "END STRUCTURED OUTPUT CONTRACT"
    )


def _json_values_from_text(text: str) -> Iterator[Any]:
    """
    Yield plausible JSON values from a model response.

    Models occasionally wrap otherwise valid JSON in a ```json fence or a short
    sentence. JSON mode normally prevents this, but the prompt-only fallback must
    tolerate it without accepting arbitrary malformed data.
    """
    stripped = text.lstrip("\ufeff").strip()
    if not stripped:
        return

    seen: set[str] = set()

    def emit(candidate: str) -> Iterator[Any]:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return
        yield value

    yield from emit(stripped)

    for match in re.finditer(
        r"```(?:json)?\s*(.*?)```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        yield from emit(match.group(1))

    # Last-resort extraction for text such as `Result: {"memories": []}`.
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        fingerprint = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        yield value


def _validate_structured_content(
    content: str,
    response_model: type[StructuredModel],
) -> StructuredModel:
    validation_errors: list[str] = []
    found_json = False

    for value in _json_values_from_text(content):
        found_json = True

        # A few models double-encode the object as a JSON string. Unwrap once.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass

        try:
            return response_model.model_validate(value)
        except ValidationError as exc:
            validation_errors.append(str(exc))

    if not found_json:
        raise OllamaRequestError(
            "Ollama did not return a JSON value for the structured request."
        )

    detail = validation_errors[-1] if validation_errors else "Unknown validation error."
    if len(detail) > 800:
        detail = detail[:800] + "..."
    raise OllamaRequestError(
        "Ollama returned JSON that failed structured validation: " + detail
    )


async def _post_non_streaming_chat(
    *,
    payload: dict[str, Any],
    timeout: httpx.Timeout,
) -> str:
    url = f"{settings.ollama_base_url}/api/chat"
    try:
        client = await get_ollama_client()
        response = await client.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError("Could not connect to Ollama.") from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("The structured Ollama request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise OllamaRequestError(
            _extract_error_text(exc.response.status_code, exc.response.text)
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise OllamaRequestError("Ollama returned a malformed JSON API response.") from exc

    content = body.get("message", {}).get("content", "") if isinstance(body, dict) else ""
    if not isinstance(content, str) or not content.strip():
        raise OllamaRequestError("Ollama returned an empty structured response.")
    return content


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
        raise OllamaRequestError(
            _extract_error_text(exc.response.status_code, exc.response.text)
        ) from exc

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
        raise OllamaUnavailableError(
            "Could not connect to Ollama while preloading the model."
        ) from exc
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
    """
    Request and validate structured output without relying on a complex Ollama
    JSON-Schema grammar.

    Primary path:
      * Ollama `format: "json"`
      * schema carried as normal prompt text
      * defensive JSON extraction
      * strict Pydantic validation

    Fallback path:
      * if JSON mode itself is rejected or returns unusable output, retry once
        without `format` while keeping the same JSON-only schema contract.

    The previous implementation passed `response_model.model_json_schema()`
    directly as `format`. On affected Ollama/model builds that schema was
    compiled into an invalid grammar before generation, producing the repeated
    `failed to parse grammar` memory-extraction error.
    """
    contract = _structured_output_contract(response_model)
    combined_system_prompt = "\n\n".join(
        part for part in (system_prompt.strip(), contract) if part
    )

    ollama_messages: list[dict[str, str]] = []
    if combined_system_prompt:
        ollama_messages.append({"role": "system", "content": combined_system_prompt})
    ollama_messages.extend(
        {"role": message["role"], "content": message["content"]}
        for message in messages
    )

    timeout = httpx.Timeout(
        connect=10.0,
        read=settings.request_timeout_seconds,
        write=30.0,
        pool=10.0,
    )

    attempts: list[tuple[str, str | None]] = []
    if model not in _json_mode_disabled_models:
        attempts.append(("json_mode", "json"))
    attempts.append(("prompt_only", None))

    last_error: OllamaRequestError | None = None

    for attempt_name, response_format in attempts:
        payload: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "think": False,
            "options": {
                "temperature": 0,
                "num_ctx": settings.ollama_num_ctx,
            },
        }
        if response_format is not None:
            payload["format"] = response_format

        try:
            content = await _post_non_streaming_chat(payload=payload, timeout=timeout)
        except OllamaUnavailableError:
            raise
        except OllamaRequestError as exc:
            last_error = exc
            if attempt_name == "json_mode":
                if _looks_like_format_rejection(str(exc)):
                    _json_mode_disabled_models.add(model)
                    logger.warning(
                        "Ollama JSON mode was rejected for model %s; "
                        "structured requests will use prompt-only JSON for this process. Error: %s",
                        model,
                        exc,
                    )
                else:
                    logger.warning(
                        "Ollama JSON-mode structured request failed for model %s; "
                        "retrying once with prompt-only JSON. Error: %s",
                        model,
                        exc,
                    )
                continue
            raise

        try:
            return _validate_structured_content(content, response_model)
        except OllamaRequestError as exc:
            last_error = exc
            if attempt_name == "json_mode":
                logger.warning(
                    "Ollama JSON-mode output did not validate for %s; "
                    "retrying once with prompt-only JSON. Error: %s",
                    response_model.__name__,
                    exc,
                )
                continue
            raise

    if last_error is not None:
        raise OllamaRequestError(
            f"Structured Ollama request failed after all JSON fallbacks: {last_error}"
        ) from last_error
    raise OllamaRequestError("Structured Ollama request failed without a usable response.")


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
                raise OllamaRequestError(
                    _extract_error_text(response.status_code, raw)
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
                    raise OllamaRequestError(str(chunk["error"]))
                yield chunk
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError(
            "Could not connect to Ollama. Make sure Ollama is running."
        ) from exc
    except httpx.TimeoutException as exc:
        raise OllamaUnavailableError("The connection to Ollama timed out.") from exc
    except httpx.HTTPError as exc:
        raise OllamaRequestError(f"The Ollama connection failed: {exc}") from exc
