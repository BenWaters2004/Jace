"""Offline smoke test for the 11B.3D structured-output fallback.

Run from the Jace backend directory with the backend virtual environment active:

    python scripts/test_memory_structured_output.py

The test does not contact Ollama. It simulates the exact grammar failure from
11B.3D and verifies that structured_chat retries without `format`, while still
requiring the final response to pass Pydantic validation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

import jace.ai.engine as engine


class DemoStructuredResult(BaseModel):
    memories: list[str] = Field(default_factory=list)


async def main() -> None:
    original_post = engine._post_non_streaming_chat
    calls: list[str | None] = []

    async def fake_post(*, payload: dict[str, Any], timeout: Any) -> str:
        del timeout
        response_format = payload.get("format")
        calls.append(response_format)
        if response_format == "json":
            raise engine.OllamaRequestError(
                "Failed to initialize samplers: failed to parse grammar"
            )
        return "Result:\n```json\n{\"memories\":[\"fallback works\"]}\n```"

    model = "11b3d-offline-test-model"
    engine._json_mode_disabled_models.discard(model)
    engine._post_non_streaming_chat = fake_post

    try:
        first = await engine.structured_chat(
            model=model,
            messages=[{"role": "user", "content": "Return test JSON."}],
            system_prompt="This is an offline test.",
            response_model=DemoStructuredResult,
        )
        assert first.memories == ["fallback works"], first
        assert calls == ["json", None], calls
        assert model in engine._json_mode_disabled_models

        # Once a model has rejected Ollama JSON mode, later structured calls in
        # this backend process should skip that failing path entirely.
        calls.clear()
        second = await engine.structured_chat(
            model=model,
            messages=[{"role": "user", "content": "Return test JSON again."}],
            system_prompt="This is an offline test.",
            response_model=DemoStructuredResult,
        )
        assert second.memories == ["fallback works"], second
        assert calls == [None], calls
    finally:
        engine._post_non_streaming_chat = original_post
        engine._json_mode_disabled_models.discard(model)

    print("PASS: 11B.3D structured-output fallback and JSON repair are working.")


if __name__ == "__main__":
    asyncio.run(main())
