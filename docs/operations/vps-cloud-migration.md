# VPS and cloud-first migration checklist

**Status:** operational plan, **not an executed deployment report**. Confirm all paths, service users, reverse proxy configuration and backups on the actual VPS before running any command. **The documentation upgrade script does not run these operations.**

## Release principle

Restore a stable Jace service before adding expensive or autonomous inference. Each change is reversible, tested on a staging or non-production instance if possible, and verified using machine evidence. Do not make the VPS depend on CPU-only Ollama to respond to ordinary chats.

## P0 — Inventory and protect what already exists

- [ ] Capture current repository commit, branch, uncommitted changes and deployment configuration (without revealing secrets).
- [ ] Identify how Core and workers actually run (systemd, Compose, containers, direct Python etc.). Do not assume the roadmap deployment diagram has already been implemented.
- [ ] Verify live HTTPS, authentication, WebSocket streaming and protected endpoint access; close unnecessary publicly reachable ports.
- [ ] Inventory live database backend, attachments, OAuth connections, agent state and data retention/backup locations.
- [ ] **Privately inspect the repository's tracked `data/jace.db` and `backend/.venv` content**; untrack and review history exposure before adding cloud secrets.
- [ ] Make an encrypted database+file backup, restore it into a separate test environment and record recovery steps.
- [ ] Establish health/readiness probes and structured redacted logs; know how to disable new model routes.
- [ ] Establish an identifiable deployment revision and rollback/backout procedure.

## C1 — Model contracts and evaluation fixture

- [ ] Extend existing `ModelProvider` interface to declare optional capabilities and normalized events/errors.
- [ ] Specify model profile metadata, request IDs, token accounting, cancellation and tool-call stream semantics.
- [ ] Build representative regression fixtures from harmless synthetic conversations, code tasks and evidence cases (no private uploads).
- [ ] Keep current desktop event protocol compatible during migration.

## C2–C3 — Cloud adapters

- [ ] Obtain *separately billed* API access; put keys in Core's secret store/environment, not Git or frontend code.
- [ ] Implement OpenAI adapter and real streaming/tool integration tests.
- [ ] Implement Anthropic adapter and the same conformance suite.
- [ ] Register both with Model Gateway without changing existing permissions or privacy defaults implicitly.
- [ ] Add provider health tests, typed errors, cancellation, request timeouts and usage accounting.
- [ ] Smoke-test cloud chat with Ollama stopped. No silent fallback to a non-working local engine.

## C4–C5 — Remove inference coupling and configure routing

- [ ] Identify and migrate remaining `jace.ai.engine`/direct Ollama paths, particularly the Agent Director.
- [ ] Move memory extraction, embedding, vision and background worker routes behind capability negotiation.
- [ ] Handle embedding dimension changes with versioned indexes and deliberate reindexing.
- [ ] Add manual/automatic provider selection without exposing secret values.
- [ ] Implement privacy-respecting failure fallback, bounded retries, circuit breaking and budget policies.
- [ ] Detect a broken provider without repeating tool side effects.

## C6–C8 — Evidence, research and model collaboration

- [ ] Persist step/task/dependency state and checkpoint workflow progress across Core restarts.
- [ ] Add claim/source linkage and action receipts, preserving current audit and tool permissions.
- [ ] Add independent review as an explicit phase, not an invisible mandatory parallel call on quick chats.
- [ ] Research must fetch sources and retain metadata; reject fabricated links and unsupported claims.
- [ ] Code changes require source/context evidence, diff review, permission where required and real tests.
- [ ] Make completion handoffs durable when users switch chats/devices.

## C9–C10 — Product readiness

- [ ] Expose provider/model and collaboration stages in UI without leaking private prompts or keys.
- [ ] Show task cost estimates, token usage, time and budget cutoff status.
- [ ] Run latency/cost/accuracy benchmarks and chaos/fault tests.
- [ ] Confirm backup restore, database migrations, deployment rollback and worker crash recovery.
- [ ] Confirm reconnect, notification and delivery semantics from desktop clients.
- [ ] Re-test permission denial, privacy blocking and malicious web-page instructions.

## Release acceptance matrix

| Gate | Pass criterion |
| --- | --- |
| Reliability | Fast and tool-based chat complete on both cloud adapters with Ollama stopped |
| Correctness | Tool outputs are correctly attributed; no dummy/canned response substituting for inference |
| Security | No secrets in logs, source, response events or desktop bundle; cloud egress policy enforced |
| Continuity | Jobs persist and recover or clearly transition to uncertain; handoffs delivered once |
| Verification | Unsourced research claims never marked verified; real command outcomes govern success |
| Cost | Every provider call accounted for; budget exceeded stops additional spend |
| Operations | Rollback and restoration proven against test copies; health probes and alerts present |

## Useful repository pointers

- Current deployment pipeline: [`.github/workflows/deploy-vps.yml`](../../.github/workflows/deploy-vps.yml). It runs backend syntax/desktop build checks and posts a bundle over HTTPS; that is not the same as a proven deployment rollback or smoke-test system.
- Settings template: [`backend/.env.example`](../../backend/.env.example) (today `JACE_MODEL_GATEWAY_DEFAULT_PROVIDER=ollama` and cloud egress is disabled).
- Provider baseline: [`backend/jace/model_gateway/gateway.py`](../../backend/jace/model_gateway/gateway.py).
- Privacy baseline: [privacy gateway](../architecture/privacy-gateway.md).
- Repo cleanup: [repository hygiene](repository-hygiene.md).

**Never run this migration directly against the only copy of persistent user data.**
