# Phase C3B — Cloud Provider Reliability & Cost Observation

## What is implemented

- **Opt-in** bounded retries for OpenAI/Anthropic **inference only**. Only retry sanitized HTTP 429/500/502/503/504, network timeout, or transport failure **before any response chunk has been emitted**. Once streaming begins, errors reach the caller: no duplicate text, repeated tool execution, or silent second provider request.
- **Per-route** circuit breakers based on failures *observed by this one Jace process*. Three consecutive transient failures open that route for 45 seconds by default. Circuits fail closed; no proactive endpoint probing. No health assertion is made about unknown models.
- Optional per-route **in-process** 60-second attempt limit. Retries count toward the limit.
- Optional Auto-only *pre-request* fast-tier fallback when the preferred route's circuit is already open and the fast-tier circuit is not. Manual model choices and streaming requests are never silently switched to another model. Actual API failures during this request are not cross-provider rerouted.
- Usage telemetry from provider-reported tokens on completed streaming responses, optional manually configured USD-per-million-token estimates, and a **soft in-process observed-spend guard**. Structured calls/embeddings are counted but their usage is not measured in this phase. Missing provider usage and failures may undercount spending.
- `GET /model-gateway/reliability` gives sanitized aggregate observation (no raw prompts, completions, keys or errors).

## Enable on a private staging instance, NOT before configuring privacy

Put real credentials only in `backend/.env` or your secret manager. The installer does not modify `.env` and does not contact provider APIs.

```dotenv
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
JACE_CLOUD_CHAT_CUTOVER=true
JACE_SMART_ROUTING_ENABLED=true
JACE_CLOUD_RELIABILITY_ENABLED=true
JACE_CLOUD_RETRY_COUNT=1
JACE_CLOUD_CIRCUIT_FAILURE_THRESHOLD=3
JACE_CLOUD_CIRCUIT_COOLDOWN_SECONDS=45
JACE_CLOUD_REQUESTS_PER_MINUTE=10
JACE_CLOUD_AUTO_FAST_FALLBACK=false
```

To estimate cost, add **YOUR VERIFIED PROVIDER PRICES** (do not copy stale prices):

```dotenv
JACE_CLOUD_PRICING_JSON={"openai:YOUR_MODEL":{"input_per_million":0,"output_per_million":0}}
JACE_CLOUD_OBSERVED_COST_LIMIT_USD=0
```

Replace `YOUR_MODEL` and both `0` example rates with current official rates and verify your billing terms. Rates of zero merely calculate zero and should **not** be used with a spend guard. With an observed cost limit greater than zero, the selected route must have an explicit price entry or the request is blocked. Prices can vary for cached input, batch, service tiers and tools; this package does not price them.

## Critical limitations

1. **Not a hard budget**. Counters reset on process restart; parallel Uvicorn/worker processes have separate trackers. Concurrent requests can exceed the observed limit. Provider invoices are authoritative. Put authoritative billing budgets/limits at the provider and implement a durable per-user, per-project reservation ledger before production enforcement.
2. Provider 429s may represent rate limits, quotas or temporary throttling; a single bounded retry cannot correct exhausted credit. Errors remain visible after limits.
3. A stream interrupted after the first chunk is **never automatically retried**. The UI must show failure, not silently repeat it.
4. No actual health probes or cross-provider verification in this phase. `observed_success` means only a prior successful call.
5. In-process 60-second rate limit is advisory for single-process use; it is not a distributed throttle.
6. Model Gateway privacy enforcement still runs before any cloud request. A `local_only` payload is not permitted to escape via a different cloud fallback. Auto preselection occurs prior to privacy enforcement; the gateway still applies final policy.
7. No changes to DB schema, automatic re-embedding, API credentials, project folders, VPS services, desktop or Agent Office.

## Suggested validation

1. Run the C3B installer dry-run, apply and `-Verify` (offline only).
2. Check `GET /model-gateway/reliability` in authenticated staging; it should report `in_process_only` and `live_probes:false`.
3. Configure a known-good cloud model and egress only in staging. Verify a short text chat and confirm success and token usage counters.
4. With a development mock only: fail before any token with HTTP 503; verify bounded retry, then circuit open after configured threshold.
5. With a mock only: emit one token and fail; verify **no retry**. With tools enabled, verify no tool runs twice.
6. Force local-only privacy and inspect gateway redirection; verify cloud counters do not increment.
7. Test manual model selection vs Auto after opening a circuit. Turn the feature off to restore earlier behavior.

## Next milestone

C3C will address a durable, centrally enforced cost ledger, provider latency comparisons, operational alerts and carefully defined post-failure fallback boundaries. C4 will add independent multi-model review grounded in retrieved sources and executed-tool evidence.
