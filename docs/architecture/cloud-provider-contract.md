# Cloud provider integration contract (proposed)

**Status:** intended implementation contract, **not a statement that OpenAI/Anthropic adapters are installed**. The current gateway code registers `OllamaProvider` by default and accepts `provider:model` routes.

## Preserve existing gateway shape

Current locations:

```text
backend/jace/model_gateway/provider.py
backend/jace/model_gateway/gateway.py
backend/jace/model_gateway/types.py
backend/jace/model_gateway/providers/ollama.py
backend/jace/model_gateway/providers/__init__.py
backend/jace/api/model_gateway.py
```

The existing `ModelProvider` interface includes `stream_chat`, `structured_chat`, `embed` and optional `warm`. Before writing cloud adapters, define which operations are required vs optional: a text-chat model should not need to manufacture fake embeddings just to satisfy an abstract method. Advertise supported operations accurately; unsupported operations must fail with a typed capability error.

## Adapter design

Create an `OpenAIProvider` that uses a supported OpenAI API and an `AnthropicProvider` using its Messages API. Keep credentials on the Core server. Separate model metadata/capability negotiation from transport. Record provider request IDs and usage after completion, including incomplete/cancelled requests where provided.

Canonical internal events should represent at least:

```text
response.started
response.text.delta
response.tool_call.started
response.tool_call.arguments.delta
response.tool_call.ready
response.usage
response.completed
response.failed
response.cancelled
```

The current Jace chat UI uses established event shapes; add an adapter layer to preserve frontend compatibility during the migration. Do not force the frontend to understand OpenAI or Anthropic wire formats.

## Provider feature differences

- Normalize system/developer/user/assistant and tool-result roles without losing the provider's supported instruction precedence.
- Assemble streamed tool-call argument fragments with stable call IDs; parse JSON and validate arguments against Jace-registered tool schemas.
- Never execute tools on the provider's authority: invoke existing Jace tool policies, approval flows and capability broker.
- Convert tool results back to the appropriate provider message schema; maintain complete per-turn conversation state.
- Support stream interruptions, cancel requests, provider timeouts, backpressure, token limits and explicit provider errors.
- Do not promise a model supports images, structured JSON, long context or tools until the selected model advertises it and passes an integration test.
- Prevent duplicate execution when retrying or failing over after a tool call; use Jace-side idempotency keys and receipts.

## Error taxonomy (planned)

`authentication_failed`, `permission_denied`, `quota_exceeded`, `rate_limited`, `timeout`, `provider_unavailable`, `model_unavailable`, `context_overflow`, `unsupported_capability`, `invalid_tool_output`, `invalid_structured_output`, `privacy_blocked`, `cancelled`.

Include human-readable diagnostic details **without** exposing API keys, raw prompts containing secrets or provider credentials. Use exponential bounded backoff for retryable errors and circuit breakers where provider outages persist. Do not retry non-idempotent tool actions without verifying their previous outcome.

## Routing and fallback policy

- Capability route and privacy rule first, then model compatibility, provider health, budget, cost and latency.
- A requested `local.private` route is strictly local.
- A cloud provider failure may switch to another *authorised* cloud model only if model capabilities and privacy policy match.
- If a partial response was streamed, show the interruption and resume cleanly rather than producing a second assistant message with duplicate actions.
- Avoid hidden paid retries and unbounded context expansion; enforce caps.
- Preserve original message provider/model attribution and tool evidence in Jace's database.

## Other inference paths requiring migration

Audit all calls to `jace.ai.engine` and to direct Ollama endpoints. In the reviewed baseline, `backend/jace/agents/director.py` imports `stream_chat` and `structured_chat` directly from the Ollama engine. Review chat, tools, background workers, structured memory extraction, embeddings, images, preload/warm logic and diagnostics. Merely setting `JACE_MODEL_GATEWAY_DEFAULT_PROVIDER=openai` will **not** create an OpenAI adapter and must not be treated as a completed migration.

## Security/testing gates

1. Valid and invalid keys; no credentials in logs or frontend bundles.
2. Real streamed chat on both providers with Ollama stopped.
3. Tool calls, parallel tool requests, malformed arguments and approval required.
4. Structured schema validation and a malformed-model-output recovery strategy.
5. Failure before response / during stream / after tool execution.
6. Cost and token usage accounting; rate limiting and cancellation.
7. Privacy-mode negative tests proving forbidden content never leaves Core.
8. Documented exact model IDs selected from current vendor metadata at implementation time.

Official resources to check before coding:

- https://platform.openai.com/docs/api-reference
- https://platform.claude.com/docs/en/api/messages
- https://platform.claude.com/docs/en/build-with-claude/streaming

Vendor details change; these links are references, not a guarantee of the current model names, limits or data retention terms.
