import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from jace.ai.engine import (
    OllamaRequestError,
    OllamaUnavailableError,
    get_models,
    stream_chat,
)
from jace.config import settings
from jace.schemas import (
    ChatRequest,
    HealthResponse,
    ModelsResponse,
)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Local backend for the Jace AI assistant.",
)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(http://localhost(:\d+)?|"
        r"http://127\.0\.0\.1(:\d+)?|"
        r"http://tauri\.localhost|"
        r"https://tauri\.localhost|"
        r"tauri://localhost)$"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def ndjson_event(data: dict[str, Any]) -> str:
    """
    Encode a single event as newline-delimited JSON.
    """

    return (
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def nanoseconds_to_ms(
    nanoseconds: int | None,
) -> float | None:
    if nanoseconds is None:
        return None

    return round(
        nanoseconds / 1_000_000,
        2,
    )


def calculate_tokens_per_second(
    token_count: int | None,
    duration_nanoseconds: int | None,
) -> float | None:
    if (
        not token_count
        or not duration_nanoseconds
        or duration_nanoseconds <= 0
    ):
        return None

    seconds = duration_nanoseconds / 1_000_000_000

    if seconds <= 0:
        return None

    return round(
        token_count / seconds,
        2,
    )


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get(
    "/health",
    response_model=HealthResponse,
)
async def health():
    try:
        models = await get_models()

        return HealthResponse(
            status="ok",
            ollama_connected=True,
            app_version=settings.app_version,
            default_model=settings.default_model,
            installed_models=len(models),
        )

    except (
        OllamaUnavailableError,
        OllamaRequestError,
    ):
        return HealthResponse(
            status="degraded",
            ollama_connected=False,
            app_version=settings.app_version,
            default_model=settings.default_model,
            installed_models=0,
        )


@app.get(
    "/models",
    response_model=ModelsResponse,
)
async def models():
    try:
        installed_models = await get_models()

        return ModelsResponse(
            models=installed_models,
        )

    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except OllamaRequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@app.post("/chat/stream")
async def send_streaming_chat(
    request: ChatRequest,
):
    if not request.messages:
        raise HTTPException(
            status_code=400,
            detail="At least one chat message is required.",
        )

    async def generate() -> AsyncIterator[str]:
        try:
            async for chunk in stream_chat(
                model=request.model,
                messages=request.messages,
                system_prompt=request.system_prompt,
            ):
                message = chunk.get("message") or {}

                content = message.get("content") or ""

                if content:
                    yield ndjson_event(
                        {
                            "type": "token",
                            "content": content,
                        }
                    )

                if chunk.get("done"):
                    eval_count = chunk.get(
                        "eval_count"
                    )

                    eval_duration = chunk.get(
                        "eval_duration"
                    )

                    metrics = {
                        "total_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "total_duration"
                                )
                            ),

                        "load_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "load_duration"
                                )
                            ),

                        "prompt_eval_count":
                            chunk.get(
                                "prompt_eval_count"
                            ),

                        "prompt_eval_cached_count":
                            chunk.get(
                                "prompt_eval_cached_count"
                            ),

                        "prompt_eval_duration_ms":
                            nanoseconds_to_ms(
                                chunk.get(
                                    "prompt_eval_duration"
                                )
                            ),

                        "eval_count":
                            eval_count,

                        "eval_duration_ms":
                            nanoseconds_to_ms(
                                eval_duration
                            ),

                        "tokens_per_second":
                            calculate_tokens_per_second(
                                eval_count,
                                eval_duration,
                            ),
                    }

                    yield ndjson_event(
                        {
                            "type": "done",
                            "model": chunk.get(
                                "model",
                                request.model,
                            ),
                            "done_reason": chunk.get(
                                "done_reason"
                            ),
                            "metrics": metrics,
                        }
                    )

        except asyncio.CancelledError:
            # The desktop app aborted its fetch.
            #
            # Re-raising allows the cancellation to
            # propagate into the Ollama HTTP stream,
            # which closes the upstream request.
            raise

        except OllamaUnavailableError as exc:
            yield ndjson_event(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )

        except OllamaRequestError as exc:
            yield ndjson_event(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )

        except Exception as exc:
            yield ndjson_event(
                {
                    "type": "error",
                    "message": (
                        "Unexpected streaming error: "
                        f"{exc}"
                    ),
                }
            )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )