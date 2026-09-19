# Phase 4B.S7 — Model Gateway

## Purpose

Jace application code should ask for a model capability, not depend on a
specific model provider.

The gateway contract supports:

- `stream_chat`
- `generate`
- `call_tools`
- `generate_structured`
- `embed`
- provider/model resolution
- provider-safe status reporting

## Capability classes

- `conversation.fast`
- `reasoning.high`
- `coding.high`
- `vision`
- `research.high`
- `local.private`
- `memory.extract`
- `embedding`
- `reranking`

## Phase 4B.S7 provider set

Only `ollama` is registered by default.

This phase does not introduce a cloud provider, external API key, or automatic
off-device data transfer. Existing local behaviour remains the default.

`local.private` is additionally guarded so it can only resolve to a provider
marked as local.

## Routing

Configured routes use:

`provider:model`

Example:

`ollama:qwen3.5:4b`

Ollama model tags may themselves contain a colon; route parsing splits only the
first colon.

Blank route settings inherit the existing Jace model settings so current model
configuration keeps working.

An explicit model selected by an existing conversation remains an override.
Plain model names are interpreted using the configured default provider.

## Compatibility

`jace.ai.engine` remains the Ollama implementation in 4B.S7. The new Ollama
provider adapter delegates chat and structured generation to that mature code,
preserving the existing tool-calling, streaming, reasoning and structured JSON
fallback behaviour.

Live chat/tool inference, background agents, memory extraction and memory
embeddings are routed through the gateway after this phase.

## Future providers

A future provider implements `ModelProvider` and is registered with the
gateway. Jace's chat, memory and agent layers do not need provider-specific
rewrites.

4B.S8 adds the Privacy Gateway in front of provider selection/data egress.
