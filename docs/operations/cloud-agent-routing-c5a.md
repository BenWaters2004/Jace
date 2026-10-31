# C5A: Opt-in cloud inference routes for Agent Director and specialists

**Status:** Tested offline only. This is **not** a successful live cloud-agent or tool-calling acceptance test.

## Behaviour

By default, `JACE_AGENT_CLOUD_ROUTING_ENABLED=false`; all old routing and Ollama readiness behaviour is preserved.

When enabled, the Agent Director planning and synthesis route and **each new specialist task** must use an explicitly configured `openai:model` or `anthropic:model`. No implicit Ollama fallback is allowed by this routing policy. The route is pinned into new `AgentTask.model` when queued; recovered tasks keep their recorded route. Already-queued legacy tasks without a pinned model are refused by the worker instead of silently migrated. A stored *old* explicit Ollama/unqualified task route is also rejected.

Cloud agent readiness verifies *configuration* (enabled provider, qualified model name, privacy enabled, cloud egress permitted), not provider connectivity. The Privacy Gateway may still classify sensitive content as local-only at execution time; its own policy is authoritative, so model-attribution work should verify actual runtime provider and identify fallback. The code intentionally does **not** bypass Privacy Gateway or existing tool permissions.

## Environment (edit production separately; never commit secrets)

```dotenv
JACE_AGENT_CLOUD_ROUTING_ENABLED=false
JACE_AGENT_ROUTE_DIRECTOR=openai:YOUR_TESTED_MODEL
JACE_AGENT_ROUTE_RESEARCH=anthropic:YOUR_TESTED_MODEL
JACE_AGENT_ROUTE_CODE=openai:YOUR_TESTED_MODEL
JACE_AGENT_ROUTE_FILES=anthropic:YOUR_TESTED_MODEL
JACE_AGENT_ROUTE_ANALYST=openai:YOUR_TESTED_MODEL
JACE_AGENT_ROUTE_GENERAL=anthropic:YOUR_TESTED_MODEL
```

Also requires existing `JACE_PRIVACY_ENABLED=true`, `JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true`, and real provider keys in the VPS-managed secret environment. No keys, secrets or database changes are made by the installer. **Do not enable for production write-enabled tool workflows until provider tool-call conformance tests have been executed in staging.**

## Acceptance checklist (staging first)

1. Back up the database, stop Jace Core, apply, verify, then restart.
2. Check `GET /agents/readiness` and inspect each specialist's `model`. Explicit routes should appear even when Ollama is offline.
3. Check that missing/invalid routes fail closed and do not create work.
4. Create one **read-only** specialist task with no sensitive content and verify actual tool-schema compatibility, permission checks and successful cloud request using provider telemetry.
5. Complete a staged Director workflow, inspect task `model` routes and Cloud Reliability observation counters; successful provider calls are not established by model selection alone.
6. Keep `JACE_AGENT_SAFE_RECOVERY_ENABLED=true`; test an interrupted tool execution is quarantined rather than replayed.
7. If verification fails, disable `JACE_AGENT_CLOUD_ROUTING_ENABLED` and investigate; source rollback is separately available via the installer.

## Limitations

- No distributed leases or exactly-once side-effect guarantee.
- The provider can be configured but unreachable, rate-limited or unable to accept a tool schema.
- Jace's Privacy Gateway can enforce local-only handling depending on payload classification; this phase does not record final effective provider.
- Does not migrate memory, embeddings, vision, TTS or existing stored task model selections.
- `GET /agents/readiness` still reports top-level `ollama_connected=false` when no Ollama probe was attempted; rely on per-agent readiness for cloud roles.
