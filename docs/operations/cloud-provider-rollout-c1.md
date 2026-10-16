# Phase C1 — Cloud provider foundation (staged rollout)

Status: **Implemented by the optional Phase C1 upgrade; not automatically deployed, enabled, or live-tested.**

## Scope

Adds OpenAI Chat Completions and Anthropic Messages provider adapters to Jace's existing `ModelGateway`. They implement text streaming, Jace function tool calls, structured output with Pydantic validation and relevant token counts; OpenAI also supports embeddings. The adapters use the existing `httpx` dependency. Jace does not need provider SDK packages for these integrations.

Cloud streaming maps onto Jace's existing Ollama-compatible chunk shape. When a request includes tools, the adapters buffer output until the model decides whether to call a tool. This avoids exposing internal planning narration before a tool call. Full incremental tool streaming is a later improvement.

The foreground and background agent loops now preserve provider tool-call IDs across tool execution. The Agent Director's two remaining direct calls to the Ollama engine have been switched to the gateway.

## What this does not finish

- Automatic model switching, cost-aware routing, circuit breakers, and multi-provider verification.
- Legacy conversation model selection and model picker migration. Current saved conversations may still request a Qwen model explicitly. These will need mapping before a complete production cutover.
- Memory extraction and embedding migration away from Ollama. Configure and test these separately.
- Image input and advanced model-specific reasoning parameters.
- Cloud voice inference and direct cloud audio generation.
- Production API availability, billing, spending caps, or privacy compliance verification.
- Secure VPS production deployment, server hardening, PostgreSQL migration and a verified backup/restore drill.

## Security gates

**Do not deploy cloud keys or enable cloud egress until the P0 preflight report is reviewed.** The public repository currently has tracked SQLite/virtual-environment artifacts; remove them from the Git index and check whether any private information has already been exposed. A Git history rewrite and credential rotation may be necessary if secrets are found. Avoid copying real credentials into Git, the installer, issue reports or logs.

The new provider IDs are *disabled* in `/model-gateway/status` until their `JACE_OPENAI_API_KEY` or `JACE_ANTHROPIC_API_KEY` has been configured. `JACE_PRIVACY_CLOUD_EGRESS_ENABLED` remains `false` by default. Jace does not override the privacy policy simply because a cloud provider exists.

## Dev-only smoke checks (when security gates are satisfied)

Start with a local, isolated Jace dev environment and a new conversation. Do not immediately repoint the live VPS or bulk migrate chat models.

1. Add `JACE_OPENAI_API_KEY` and/or `JACE_ANTHROPIC_API_KEY` to your **untracked** `backend/.env`.
2. Review classification, payload transformation and third-party retention requirements. Only then enable `JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true` for the controlled test.
3. Run `GET /model-gateway/status` through the existing authenticated API; verify provider enabled state (credentials must never be returned).
4. Use explicit `openai:<model-id>` / `anthropic:<model-id>` on a **test** chat. Begin with a plain greeting, then a read-only tool request.
5. Test a structured extraction operation through the gateway, a timeout, a bad key and unavailable-model failures.
6. Confirm local-only and secret-bearing prompts stay local or fail closed, not sent remotely.
7. Inspect audit logs for credentials, payloads, provider errors and token accounting. Fix any leakage before production.

Select model IDs available in your own API account. Model availability, features, limitations and prices can change; confirm against the official provider APIs before the first live test.

## Upstream references

- OpenAI Chat Completions: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- OpenAI streaming chunks: https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events
- Anthropic Messages streaming: https://platform.claude.com/docs/en/build-with-claude/streaming
- Anthropic tool use: https://platform.claude.com/docs/en/claude_api_primer

## Next: Phase C2

Migrate existing conversation selection and historical model IDs to provider-qualified routes, move remaining Ollama-only auxiliary AI (memory, embeddings, voice where relevant), then build and verify automatic routing and fallback. Only after the single-model path is stable should Agent Director v2 expand into independent cross-provider review.
