# Jace C2A — controlled cloud-chat cutover

**Status:** Source upgrade only. Disabled by default; no provider activation, secrets, VPS changes, model migration, or live API tests are performed by the installer.

## What this step changes

- Existing saved conversations can move from legacy unqualified model names (e.g. `qwen3.5:4b`) to the configured **cloud** `conversation.fast` route **when C2A cutover is explicitly enabled**.
- Explicitly qualified `ollama:<model>` always stays local. Explicit `openai:<model>` or `anthropic:<model>` requests are honoured.
- New conversations use the cloud route after opt-in. Existing conversations migrate *lazily on their next request*; chat history remains intact.
- `/models` lists configured and credentialed cloud text-chat routes, even without Ollama. Locally available models appear as `ollama:<model>` to allow explicit manual selection when cutover is on.
- The desktop suppresses the misleading "Ollama unavailable" warning if a configured cloud model is listed. This does **not** imply that the cloud API has been verified; the first test request verifies that.
- During cloud-chat cutover, a temporary embedding failure will no longer abort general conversations requiring memory search. The system records a warning and instructs Jace not to pretend long-term memory was retrieved.

## Do not enable until P0 safeguards are reviewed

1. Ensure GitHub does not expose passwords, OAuth tokens, real user data or API credentials. Inspect tracked `data/jace.db`, `backend/.venv`, and commit history. Removing an indexed file is not the same as removing past exposure.
2. Verify VPS TLS, authenticated API, firewall rules, trusted deployment, database backups with a restore drill, and provider billing limits.
3. Confirm your own allowed provider model IDs, account permissions, expected features, API rates and privacy requirements. A ChatGPT subscription does not substitute for OpenAI API billing.
4. Use a **development or staged** Jace Core first. Make a backup of your database before switching routes.

## Controlled activation (only after review)

Add the following to the *untracked* server-side `backend/.env`, using a model ID confirmed in your own API account. Examples use placeholders intentionally:

```dotenv
JACE_OPENAI_API_KEY=<your-openai-api-key>
JACE_ANTHROPIC_API_KEY=<your-anthropic-api-key>
JACE_MODEL_ROUTE_CONVERSATION_FAST=openai:<your-supported-chat-model-id>
JACE_CLOUD_CHAT_CUTOVER=true
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
```

Only one provider key is needed for first tests. Keep `JACE_MODEL_GATEWAY_DEFAULT_PROVIDER=ollama` unchanged for now; C2A uses the explicit `conversation.fast` route, not a global default. The gateway continues to enforce privacy classification and **fail closed** if data must stay local. Sensitive material must not be sent to cloud models without permission and an adequate privacy policy. New Jace options are loaded on restart.

For a Claude-only first test, set:

```dotenv
JACE_MODEL_ROUTE_CONVERSATION_FAST=anthropic:<your-supported-chat-model-id>
```

To immediately stop legacy-chat cutover, revert:

```dotenv
JACE_CLOUD_CHAT_CUTOVER=false
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=false
```

Restart the staged service. This does **not** delete cloud-qualified names saved in conversations; reopen or select a local model explicitly if cloud access is disabled.

## Required smoke-test matrix

| Test | Expected result |
| --- | --- |
| `GET /model-gateway/status` with valid credentials | Configured provider enabled; no key returned |
| `GET /models`, Ollama offline, cloud cutover enabled | Selected configured cloud routes returned |
| Create new conversation with historical Qwen model name | Stored model is configured cloud route |
| Reply in an existing legacy-Qwen conversation | Routes to configured cloud model; history retained |
| Manually select `ollama:<model>` | Preserves explicit local choice |
| Plain greeting to selected cloud model | Real provider response, streamed |
| Safe read-only tool request | Tool executes through Jace permission system and response finishes |
| Explicit memory-recall question while embeddings are unavailable | Chat can continue; Jace must not claim unavailable memory was recalled |
| Unavailable/missing API key | Clear provider error, **no** false success |
| Privacy `local_only`, Ollama offline | No cloud egress; error rather than private-data transfer |
| Enabling cutover without proper cloud route | Clear configuration error instead of silently using local Qwen |

## Known limitations — next subphase C2B/C3

- Ollama may still be needed for embeddings, memory extraction and other background tasks; C2A does not make the *entire* platform Ollama-independent.
- An embedding switch requires a deliberate dimension/index compatibility and migration plan. Never automatically re-embed or overwrite existing vectors as part of a chat cutover.
- The adapters remain text-only for model input; images, audio and other modalities are handled in later milestones.
- The cloud providers and gateways do not yet implement cost-aware routing, retries/fallbacks across providers, independent multi-model verification or spending thresholds.
- `/models` shows **configured** routes; it is not a live provider catalogue or health probe.
- `openai` and `anthropic` adapters currently use direct HTTP APIs introduced by C1. API availability must be live-tested separately.
- Desktop selected model can be stale until reloading a conversation after the first lazily migrated reply.

## Verification and rollback

```powershell
powershell -ExecutionPolicy Bypass -File .\apply_jace_cloud_c2.ps1 -RepoRoot C:\Users\Ben\jace -DryRun
powershell -ExecutionPolicy Bypass -File .\apply_jace_cloud_c2.ps1 -RepoRoot C:\Users\Ben\jace
powershell -ExecutionPolicy Bypass -File .\apply_jace_cloud_c2.ps1 -RepoRoot C:\Users\Ben\jace -Verify
powershell -ExecutionPolicy Bypass -File .\apply_jace_cloud_c2.ps1 -RepoRoot C:\Users\Ben\jace -Rollback
```

Rollback restores exactly the original source files (only while installed files still match expected hashes); it does not edit your `.env`, revert already migrated conversation rows, revoke provider keys or control the VPS. The package does not perform a Git commit or deploy.
