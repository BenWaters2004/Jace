# C5B.1 — Durable model invocation receipts

This **additive** phase records one database row for each actual Model Gateway
adapter attempt, including attempts made by the existing C3B reliability retries.
Routes are recorded *after* Privacy Gateway policy and provider resolution.
`requested_route` records the pre-privacy route, and `effective_route` records
which Jace adapter was actually called. `route_changed` makes local reroutes
visible. A route name is metadata, not proof a remote provider processed the call.

## Coverage

- `ModelGateway.stream_chat`: provider attempt per stream; text, tool calling,
  and gateway-backed Agent Director work are included.
- `ModelGateway.generate_structured`: provider attempt per structured response.
- `ModelGateway.embed` and `embed_with_route`: provider attempt per embedding.
- Gateway `.generate` and `.call_tools` use `.stream_chat`, so are counted once.
- Direct legacy calls to `jace.ai.engine`, or providers invoked outside the
  gateway, are **not** covered. A complete inventory is C5B.2 work.
- The receipt table is created by Jace Core on **next startup** using existing
  `metadata.create_all`. Alembic migration management remains a later phase.

## Data handling

Stored: generated receipt UUID, timestamps, provider/model, capability,
operation, requested and effective routes, privacy classification/mode/action,
status, sanitized exception **type only**, latency, available reported token
counts, estimated cost and hash of the configured price schedule.

Never stored: prompts, responses, tool arguments/results, embeddings, headers,
API keys, exception messages, or provider request IDs inferred from model text.
`provider_request_id` remains `NULL` because current adapters do not expose
trusted HTTP request IDs. Structured and embedding usage remains unknown until
provider adapters return real metadata; it is not estimated from input text.
When stream providers return both token counts as zero, usage is `unavailable`,
not zero-billed.

Costs are `NULL` unless the user has configured a valid `JACE_CLOUD_PRICING_JSON`
for the exact provider:model route. Even with rates, amounts are **estimates,
not provider invoices**. Retry attempts are stored as separate rows; it is
possible that a provider bills an unsuccessful attempt with no token receipt.

## Inspect locally (no open HTTP receipts endpoint)

Run from the repo root **on the machine hosting the authoritative Jace DB**:

```powershell
.\backend\.venv\Scripts\python.exe .\backend\scripts\show_provider_receipts.py --limit 20
```

On a VPS, use the Python interpreter/environment used by `jace-core` and run
`python backend/scripts/show_provider_receipts.py --limit 20` from its code root.
Server-mode endpoints are intentionally not added until owner scoping and access
control are designed. This command uses the current Jace `DATABASE_URL`.

## Acceptance

1. Shut down Jace Core for a controlled deployment and back up its database.
2. Install code, then restart Core. The table is added, not replacing others.
3. Use existing GPT and Claude chat with **short benign prompts** and no tools.
4. Run `show_provider_receipts.py` against the same Core DB. You should see
   one or more separate `openai` / `anthropic` rows with success statuses.
5. Compare configured vs effective route; no unrequested cloud fallbacks should
   appear. Check token counts for stream responses if provided. If rates were
   not configured, costs correctly show `unpriced`.
6. Run the new offline unittest and existing `quick`, `full`, and `security`
   quality profiles; no live providers are used by these tests.
7. Repeat the provider test with Ollama stopped **only in staging** to establish
   cloud independence. C5D production acceptance remains outstanding.

### Known limits

- Best-effort DB writes: a database outage logs only an exception class, and
  does not abort a completed provider response. It may leave gaps in receipts.
  A future strict telemetry/monitoring policy will make failures detectable.
- Cancelled streaming generators persist when Python closes them; a hard worker
  kill can lose in-flight, uncommitted receipts.
- No per-conversation/user/workflow IDs, provider HTTP response IDs, verified
  billing, automatic price updates, or owner-filtered REST API yet.
- This does not change providers' existing tool permissions or privacy policy.

### Rollback

Use the backups printed by `tools/apply_c5b1.py`, stored outside the repository
in `../Jace-C5B1-Backups/<timestamp>/`. Restore the original `gateway.py` and
`database.py` after stopping Core. Remove the newly added files **only if they
have not been modified by later work**. The additive receipt table is left
untouched; do not drop it before taking a verified backup.
