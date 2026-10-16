# Jace — Cloud-First Intelligence & Master Development Roadmap

**Version:** 2.0 (proposed)  
**Date:** 16 October 2026  
**Status:** Architecture and implementation plan; not an implementation report  
**Sources reviewed:** [Current Jace GitHub repository](https://github.com/BenWaters2004/Jace), default branch `master`, and the user-supplied *Jace — Master Architecture & Development Roadmap* (19 September 2026). Current vendor API documentation and pricing should be checked again immediately before integration.  
**Decision:** Make hosted model APIs the normal inference route. Retain local models as an optional privacy/offline capability, not a dependency of the VPS.

---

## 1. Executive decision

Jace is a persistent personal AI operating environment, not a branded wrapper around one model. Jace controls identity, memory, projects, context, tool authorisation, devices, integrations, workflows, audit records, costs and evidence. OpenAI, Anthropic and later providers are interchangeable reasoning resources. The VPS is the control plane; authorised devices and integrations are execution planes.

**New default behaviour:** routine chat → one fast cloud model; substantial reasoning → one stronger cloud model; consequential research, code and multi-step tasks → Jace creates a bounded workflow that may employ different providers in complementary roles. A separate evidence layer verifies facts, sources and actions. Multiple models are **not** an automatic truth guarantee: independent sources and deterministic tests take priority over model agreement.

**Non-goals for the first release:** replacing the entire existing application, running big models without a GPU, launching unbounded autonomous agents, allowing unrestricted terminal or desktop access, and introducing every long-term feature at once.

## 2. What exists and what must change

The `master` branch presently includes:

- `backend/jace/model_gateway/`: provider abstraction, model-capability routes and an Ollama adapter. It currently registers only Ollama by default.
- `backend/jace/privacy/`: privacy classification, routing constraints and a first protected-cloud transformer. Cloud egress is **off by default** in `backend/.env.example`.
- `backend/jace/tools/agent.py` and `backend/jace/agents/runner.py`: paths that use the model gateway. Some other paths, including `backend/jace/agents/director.py`, still import `stream_chat`/`structured_chat` from the Ollama-specific `jace.ai.engine`.
- `backend/jace/api/chat.py`: streaming chat, tools, persistence and an established frontend protocol. Its current model selection is tied to the conversation's stored model and assistant defaults.
- `backend/jace/agents/director.py`: specialist selection, tasks, handoffs and evidence gates that should be retained and improved, not rewritten wholesale.
- `backend/jace/database.py`: SQLAlchemy async and database URL support, but also a SQLite `create_all`/compatibility path; robust production schema migrations remain necessary.
- `backend/jace/api/auth.py`, device-agent modules, terminal/process services, audit and permission code, desktop frontend, voice, calendar and connections.
- `.github/workflows/deploy-vps.yml`: validates Python syntax and desktop build, bundles code and sends it to a deployment URL. This establishes a deployment path but does not demonstrate production health, database restore, smoke tests or a safe rollback.

**Release/security warning:** The public repository's tracked tree contains `data/jace.db` and many `backend/.venv` files despite `.gitignore` excluding them now. Do not open the database to publicise its contents; inspect locally for sensitive contents, untrack it and the virtual environment, clean caches, audit Git history, and rotate credentials if exposure is established. Do not assume `.gitignore` removes historical commits.

This review is of source, not a live VPS inspection. Runtime issues, provider billing, actual database integrity and endpoint availability require tests on the server.

## 3. Target system boundaries

```text
Desktop / Web / Mobile / Voice / Tray
                |
           HTTPS + WSS
                |
        JACE CORE on VPS
  identity | chat | memory | projects
  permissions | audit | notifications
  context builder | privacy gateway
                |
         INTELLIGENCE LAYER
  request classifier / policy router
  model gateway / budget + health
  workflow Director / verifier
                |
       +--------+---------+
       |        |         |
     OpenAI  Anthropic  Other/cloud
       |        |         |
       +--------+---------+
                |
     structured evidence + synthesis
                |
        tool/capability broker
                |
   +------------+--------------+
   |            |              |
 device agents  cloud integrations  sandbox workers
 files/shell/UI  email/calendar/Git  code/tests/browser
```

Only Jace decides which data crosses the provider boundary and what tools may run. The cloud model never directly possesses a device key, provider credential or unrestricted shell. Actions go through Jace-owned, typed, audited tools. A single task has stable IDs, event stream, state history, cost ledger and permission scope across every client.

### VPS deployment blueprint

- TLS reverse proxy and restricted `/api` + WebSocket ingress on 443; authentication on all sensitive routes; secure WebSocket handshake, origin and session checks.
- FastAPI API service with separate queue-consuming worker processes; never rely on request-scoped in-memory tasks for long jobs.
- PostgreSQL for authoritative state, ideally with `pgvector` when justified by retrieval needs; Redis for transient queues, leases, rate limiting and presence (not authoritative records); private object storage for attachments and evidence.
- Automatic health/readiness checks, request IDs, structured redacted logs, error tracking, trace metrics, provider monitors, durable backups and restore drills.
- Database, Redis, debug endpoints, host shells, Ollama and worker management are not publicly exposed.
- Outbound TLS access to OpenAI/Anthropic and authorised third-party APIs. API keys come from server-side secret storage, never the desktop bundle, Git or memory prompts.
- Deploy via staged releases with migrations, smoke checks, backout path and explicit approval for production if risk is high. Use Docker Compose or an equivalent managed service layout once actual VPS setup is inventoried.

### Local/remote modes

- **Normal mode:** remote Jace Core on VPS; cloud APIs for most inference; local device agents for on-device actions.
- **Local-only mode:** optional local core/model if available; fail closed with a clear explanation when no local model exists. Do not silently send protected data to the cloud or pretend offline tasks succeeded.
- **Degraded mode:** switch to an authorised alternate cloud provider when one fails; if none works, preserve the task and show retry/paused state.

## 4. Provider strategy and initial model roles

Keep named *capabilities* stable; external model IDs and prices remain settings, not hard-coded agent identity. Start with OpenAI and Anthropic through their official APIs, later add Gemini or other providers after the initial system is sound.

| Capability / routing class | Initial policy | Verification policy |
|---|---|---|
| `conversation.fast` | One low-latency, inexpensive cloud model | No second model unless disputed/high-risk |
| `conversation.balanced` | One mid-tier model with tools | Optional on-demand review |
| `reasoning.high` | Stronger frontier reasoning model | Counter-review when consequential |
| `coding.high` | Strong coding/reasoning model | Independent diff review + executable tests |
| `research.high` | Researcher model + Jace-controlled web retrieval | Separate source evaluator and claim checks |
| `research.verify` | Prefer another provider, with restricted role | Examine primary evidence independently |
| `workflow.plan` | Capable planning model | Jace validates task graph deterministically |
| `workflow.synthesise` | One capable writer/planner | Cannot override contrary evidence |
| `memory.extract` | Cheap structured-output model | Schema validation; only store justified stable facts |
| `embedding` | Small dedicated embedding model/service | Stable dimensions, version and reindex strategy |
| `vision` | Vision-capable API model | Screenshots only under privacy policy |
| `local.private` | Local model only, if configured | No cloud fallback without explicit consent |

Examples of candidates available in vendor documentation as of October 2026 include OpenAI `gpt-6-luna`, `gpt-6.1-sol` and `gpt-6-astra`, and Anthropic `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` and `claude-fable-5-1`. These names are **configuration examples**, not universal choices for every task or a guarantee of account access. Benchmark them using Jace's actual prompts, tools and UK-hosted connection latency before selecting defaults.

Use **native OpenAI Responses API** and **Anthropic Messages API** in the provider adapters. A common interface is essential, but avoid forcing all functionality through a lowest-common-denominator text API. Provider-specific capabilities should be represented as optional extensions. OpenAI and Anthropic subscriptions to consumer chat products are not substitutes for separately billed API access.

### Provider interface contract

Each adapter must support or accurately advertise:

- streamed text and tool-call deltas; structured outputs; multimodal inputs; cancel; max-output and reasoning settings; token usage; cost categories; provider request IDs;
- typed errors: authentication, permission, rate limit, quota, timeout, unavailable, invalid model, context overflow, safety refusal and malformed output;
- versioned model metadata: context length, streaming, tool use, vision, cost, region, data-handling class, available capabilities and health;
- secure key configuration and connectivity/self-tests; graceful close and connection pooling;
- explicit unsupported errors for operations a provider cannot do (rather than lying or silently substituting).

An initial internal contract might include `generate`, `stream`, `structured`, `embed`, `health`, `models` and `cancel`, with `ToolCallDelta`, `UsageRecord`, `ErrorRecord` and `SourceCitation` as shared normalized types.

**Critical compatibility work:** current Jace code consumes Ollama-shaped `message`, `tool_calls`, `done` and duration/tokens fields. Add a translation layer or migrate all consumers to canonical events; do not simply plug vendor SSE payloads into the existing agent loop. Ensure correct tool-call argument assembly, tool-result correlation, replay and exactly-once action semantics.

## 5. Smart routing and fallback

A route decision is a policy decision grounded in: task category, estimated complexity, desired latency, tool requirements, context size, privacy classification, configured budget, provider health, observed performance and any user-selected override.

1. Normalise the request and attachments; recover relevant project and memory context.
2. Classify confidentiality and user intent before model egress; reserve explicit/manual privacy mode.
3. Compute required capabilities, likely difficulty, urgency and action risk using cheap heuristics first. An LLM classifier is optional, with a fallback.
4. Choose workflow style: `direct`, `single_reasoner`, `research_verified`, `code_verified`, or `custom_directed`.
5. Select one primary route with bounded fallback list, reason and cost ceiling; persist decision.
6. Keep the chosen route consistent for the current tool turn; re-plan carefully if provider fails mid-tool-call.
7. Stream answer and status; record real provider/model and usage, not stale conversation settings.
8. Run quality checks only when indicated; record outcome and learned routing metrics.

**Fallback rules:** avoid retrying invalid credentials or unsupported parameters endlessly. Retry safe/idempotent inference with jittered backoff; route to an alternate compatible provider after transient failure; never replay side-effecting tools merely because text generation restarted. If the primary response is partially streamed, mark it and clearly reconcile before a fallback continuation. A local-only request never fails over to cloud. Service health should be based on fresh real probes and failure rates, not only configured presence.

**Manual controls:** Auto, Fast, Balanced, Deep and Research. Advanced settings allow preferred provider, cost limit and explicit model for a request. A manual preference must not override security/privacy restrictions.

## 6. Cross-provider workflows: useful collaboration, not constant voting

### A. Simple chat

One model receives Jace's identity prompt, small relevant memory/context and request. Stream immediately. Persist chat under Jace's own IDs. A second model is not called by default.

### B. Complex reasoning

Use one strong reasoner to produce a solution. For high-risk or uncertain decisions, request a *skeptical review* from another provider with the question and independent data/evidence, ideally **without** the first answer initially. Then show discrepancies for adjudication. Do not use agreement alone as proof.

### C. Research with citations

`scope -> search -> collect -> extract -> claim table -> evaluate -> challenge -> synthesise -> cite -> deliver`

- **Researcher:** creates research questions and finds candidate primary sources.
- **Retriever:** Jace-owned web/search/browser tools fetch actual pages/documents, record retrieval time, URL, title, content hash, author/date if available, direct excerpts and inaccessible/broken flags. When using provider-hosted web search, ingest citation annotations and source metadata into the same evidence store; verify URLs against actual retrieved material when practical.
- **Analyst:** extracts atomic factual claims and maps each to source IDs with relevance, confidence and temporal validity.
- **Independent verifier:** ideally another provider tests each material claim against the underlying retrieved material, checks contradictory sources, and requests additional retrieval when needed. It must not simply judge a polished unsourced narrative.
- **Editor/Synthesiser:** delivers one answer with inspectable source links, notes disputed/unknown points, separates fact from inference and indicates date sensitivity.

Citation validation must reject fabricated URLs, quote fragments not present in the retrieved document, empty evidence, irrelevant sources, dead links and stale claims presented as current. Certain claims need multiple *independent primary* sources; copying websites or two models citing the same unsupported claim are not independent confirmation.

### D. Coding and debugging

`inspect actual files -> reproduce error -> propose bounded patch -> independent review -> approved write -> run tests -> verify artefacts -> report`

The coding model obtains real repository state through Jace file/Git tools. Its reviewer receives the patch, task specification and relevant files, without needing to endorse the first model's reasoning. The reviewer flags logic flaws, regressions, security concerns, missing tests and deviations. However, **tests, compiler output, hashes, diffs and observed runtime behaviour outrank both model opinions**. A failed test is not overruled by unanimous AI agreement. Writes/pushes/deployments require appropriate permission; create check-pointed patches or branches.

### E. High-consequence actions

Plan and validate command + target + permissions + side effects first; acquire explicit approval for risky operations; execute once through a typed capability broker; capture host/tool-generated IDs, exit code and before/after state; optionally use an independent reviewer **before execution**; report `Verified`, `Unverified` or `Failed` from machine evidence. Never have two model agents independently execute the same side effect.

### F. Long-running delegated work

A user request becomes a durable workflow with a task graph. Director can hand off to agents using different models, wait for dependencies, retry bounded safe steps and persist artifacts. Work survives desktop closure, chat switching and worker restarts. Always publish exactly one final handoff per workflow, including failure/partial results, and expose progress across all clients.

## 7. Verification framework

Use a shared evidence object across tasks:

```text
EvidenceRecord
  id, task_id, claim_id, source_type
  source_uri / tool_id / file_path
  retrieved_or_observed_at
  content_hash / commit_sha / output_digest
  excerpt_or_artifact_reference
  direct_observation: bool
  trust_level, freshness, contradictions

ClaimRecord
  id, text, type: fact|inference|hypothesis
  evidence_ids, confidence, status
  verified_by, verification_method, reviewed_at

ActionReceipt
  tool_call_id, idempotency_key, target, approval
  started_at, finished_at, return_code
  remote_provider_id / file_hash / changed_resources
  status: verified|failed|uncertain
```

**Do not confuse model verification with evidence verification.** The verifier may detect logical faults but cannot truthfully establish that a program compiled without actual compiler output. Have explicit fail-closed rules for absent evidence. Display claim evidence and verifier dissent to the user. Prompt-injection content from web pages, emails, files and tool output is untrusted data and cannot grant capabilities or modify system policy.

## 8. Privacy, security and data governance

Retain the existing `public`, `internal`, `confidential`, `personal`, `secret` classifications and modes (`cloud_allowed`, `protected_cloud`, `local_only`). Upgrade enforcement before enabling cloud. Current protected cloud covers selected emails and phone numbers but should not be described as complete PII protection.

- **All egress paths:** scan user message, retrieved source content, attachments, memory, image descriptions, tool definitions/arguments, tool results and intermediate agent summaries—not just the initial prompt.
- **Credentials:** hard block secrets/private keys/OAuth tokens/connection strings; separate provider-managed OAuth secrets from model-visible context. Rotate any exposed secret.
- **Personal/confidential data:** request-scoped reversible pseudonyms only when semantically safe; preserve critical coding identifiers when code correctness requires it; classify documents and projects explicitly.
- **Data-minimisation:** retrieve only relevant passages, apply maximum attachment size and tool-output budgets, avoid sending entire inboxes/monorepos unless explicitly needed.
- **Cloud-denied mode:** stop with an honest unavailable message if no authorised local model exists; never silently downgrade protection.
- **Supply chain:** encrypt disks and backups, harden CORS/auth/WebSockets, prevent SSRF via web-fetch tools, use device outbound connections and short-lived scoped credentials.
- **Governance:** configurable retention for prompts, traces, citations, artifacts and memory; user controls for deletion/export, provider allowlists and data residency where offered. Confirm each provider's actual policy and contractual posture before processing sensitive work.
- **Tool execution:** typed capability manifest and explicit authorisation; server-side tool registry is not inherently safe just because a model is strong. E-mail sends, deletes, remote pushes, process kills, payments and account changes are approval-gated.

## 9. Cost, performance and reliability

Model bills are usage-based; the user needs paid API credentials and budgets. Create a central spend ledger for each provider/model/task/agent with prompt tokens, cached input, output/reasoning tokens, web/search tool fees, retries and final estimated bill. Currency conversion and VAT are separately configurable. Use provider usage metadata where possible and reconcile with provider billing.

Suggested controls: daily and monthly soft/hard limits, per-task approval thresholds, maximum specialist calls, per-workflow token/step limits, reasoning-effort caps, parallel agent limits, search budget, spend dashboard and alerts. On reaching a hard limit, pause discretionary work rather than secretly exceeding it.

Performance work: streaming-first responses; prompt/context caching when supported; compact memory retrieval; no full transcript replay for every agent; bounded history summaries; reuse retrieved documents between agents; avoid sending the entire knowledge base to each provider. Circuit breakers, per-provider concurrency/rate limiting, backoff and startup health checks are essential.

**Initial pricing reference:** See official, changing documentation at https://developers.openai.com/api/docs/pricing and https://platform.claude.com/docs/en/about-claude/pricing . Estimate using currently selected model's exact pricing tier, context, cache policy and tool costs. Do not treat the consumer ChatGPT/Claude subscription as API credit.

## 10. Revised development sequence — implementation and gates

### P0 — Stabilise VPS and secure the baseline (do this first)

1. Tag a known-good commit and capture the currently deployed commit/version; keep local Jace functional until migration passes.
2. Verify VPS OS, DNS, reverse proxy, firewall, TLS, service accounts, health endpoint, WebSocket and worker lifecycle; inspect and document real deployment architecture rather than assuming Compose.
3. Inventory persistent SQLite/other databases, attachments, OAuth connections, device keys, memory and settings; create an encrypted backup and **perform a restore test**.
4. Audit the tracked `data/jace.db`, `.venv` and any build/cache artefacts; untrack protected runtime data, investigate prior commits and rotate credentials as indicated.
5. Add post-deploy API, auth, database and WebSocket smoke checks; staged deploy and rollback; ensure CI refuses private data and oversized runtime files.
6. Reproduce the existing 'same canned welcome response' and model-loading issues as regression tests. Distinguish model output, frontend duplicate/stale events, voice wake acknowledgement and tool-stream bugs rather than attributing all symptoms to CPU.

**Exit gate:** repeatable secure deployment, recoverable database, known deployed SHA and baseline direct chat/stream status.

### C1 — Define the new provider contracts and acceptance tests

1. Document canonical message roles, multipart content, tool schemas, stream deltas, tool-call completion, structured output, provider usage/errors and citations.
2. Implement typed `ModelRequest`, `ModelResponse`, `ModelEvent`, `UsageRecord`, `ProviderCapabilities`, `ModelProfile` and `ModelError` types.
3. Introduce adapter conformance tests with simulated and recorded streams; never use production tools in provider tests.
4. Support provider-specific capabilities without making Ollama the canonical type.
5. Create a registry that can be updated or disabled by config, with model aliases separated from provider IDs and user-facing labels.

**Exit gate:** current Ollama adapter passes tests unchanged and all existing event consumers remain compatible.

### C2 — Integrate OpenAI

1. Add official SDK dependency and a credentials/config provider without exposing keys to frontend/agents.
2. Implement Responses API adapter for text, streaming, tool calling, structured output and usage accounting; add vision as needed.
3. Respect supported reasoning/temperature arguments per model; handle result IDs and tool-call deltas correctly.
4. Add `GET /model-gateway/status` self-test details, health probes and error mapping without leaking API keys.
5. Test one-off chat, 20-turn chat, tools, cancellation, invalid key, quota, rate limits, timeout, malformed output and provider unavailable.

**Exit gate:** authenticated VPS client can select an OpenAI model and produce a real streamed response without Ollama running.

### C3 — Integrate Anthropic

1. Add official Anthropic SDK and provider-managed secret configuration.
2. Implement Messages API streaming, tool-use blocks, thinking/config differences, structured generation and usage reports.
3. Normalise assistant/tool conversation history to Anthropic's accepted sequence, including multiple tool calls and errors.
4. Test the same scenarios as C2 and compare latency/quality on the same Jace tasks.

**Exit gate:** Jace can execute the same chat and safe tool flow on either provider; the user sees one consistent Jace identity.

### C4 — Remove Ollama dependencies from the rest of Jace

1. Search every inference call site (`jace.ai.engine`, `get_ollama_client`, model-warm calls, embeddings, memory, Director, voice text generation and diagnostics).
2. Migrate `director.py` off the Ollama-specific `stream_chat`/`structured_chat`; retain robust deterministic routing fallbacks.
3. Separate `ModelProfile` capability routes from `conversation.model` (which may contain an old `qwen` tag). Migrate old conversations to `auto` while recording original model metadata; do not overwrite history.
4. Choose cloud or tiny CPU embedding strategy; version embeddings and regenerate indexes when model/dimensions change. Keep privacy constraints.
5. Move memory extraction/structured tasks to configured cheap cloud or strictly local model, with JSON validation and deterministic no-op fallback on failure.
6. Make Ollama optional and disable preload/warm checks when provider disabled.

**Exit gate:** with Ollama stopped/uninstalled, chat, memory, Director, retrieval and background workflows operate within configured cloud policies; local-only tasks clearly refuse if no local runtime.

### C5 — Routing, fallback and model/policy settings

1. Implement `Fast`, `Balanced`, `Deep`, `Research`, `Auto` policies and model tiers based on capability, privacy, latency, spend, availability and task risk.
2. Manual provider/model choice, per-agent defaults, preference persistence, project privacy restrictions.
3. Circuit breaker, retry/backoff, no retry on inappropriate errors; prove failover between providers on simulated outage.
4. Add provider/model health UI and route trace showing why a model was chosen.
5. Add budgeting and cost estimation **before** unbounded background calls are enabled.

**Exit gate:** 95%+ of a representative simple-chat suite uses a single provider call, and failover succeeds without duplicating side effects.

### C6 — Common workflow/evidence contracts

1. Persist `Workflow`, `Step`, `Dependency`, `Evidence`, `Claim`, `ActionReceipt`, `Review` and `Artifact` records.
2. Ensure exactly-once terminal handoff delivery via a transactional outbox/idempotent inbox and notification fallback, independent of active chat.
3. Add cancellation, resume, retry leases, checkpoints, deadlines, spending ceilings and bounded parallelism.
4. Create tool success contracts for filesystem, shell, Git, calendar, email, web and browser actions; normalise observed vs inferred/unverified results.

**Exit gate:** simulate worker restart and chat change during work: the complete/failed result appears once and is recoverable.

### C7 — Multi-model Director and independent verification

1. Upgrade agent definitions to provider/model policies instead of only an agent name and one inherited conversation model.
2. Implement Directed task graphs, mandatory output schema, evidence requirements and no-duplicate-side-effect rule.
3. Add `Reviewer`/`Verifier` roles with independent prompts; optionally blind reviewers to the first proposed conclusion before exposing it for reconciliation.
4. Support parallel research/extraction tasks when independent, but serial dependencies for edits/deployments.
5. Create a deterministic arbiter for conflicts (evidence quality, freshness, build/test output, policy), escalating unresolved differences to the user.
6. Maintain a distinct planning budget, execution budget and verification budget, with hard-stop conditions.

**Exit gate:** research and code tasks use two different providers where appropriate; negative tests prove the reviewer rejects unsupported claims and failed builds.

### C8 — Research engine and citation discipline

1. Build `Source`, `DocumentSnapshot`, `Excerpt`, `Claim` and `Citation` tables/objects.
2. Integrate approved web search/fetch services and provider-hosted tools into a common source registry; enforce SSRF/security boundaries.
3. Parse page and PDF text, preserve URL and retrieval time, canonicalise/dedupe URLs, detect dated or stale evidence.
4. Require citation-to-claim matching with existence/excerpt checks; include contradiction detection.
5. Show sources, evidence strength and unverified/disputed findings in an expandable research report.

**Exit gate:** Jace cannot present fake sources or tool-unsupplied findings as verified, and users can inspect actual supporting material.

### C9 — UX and observability

1. Keep one visible Jace persona. Show 'Fast', 'Researching', 'Verifying', 'Executing', 'Waiting approval', or 'Paused' instead of changing speaker to model names.
2. Add an optional expandable workflow timeline: assigned agent, provider/model, current task, source reads, tool invocations, evidence, reviewer flags, costs and next action.
3. Preserve and improve Agent Office: true worker statuses and speech bubbles linked to actual events; provider logos only as optional metadata.
4. Add model settings and provider-test screen, cost dashboard, active-job centre, source viewer, conflict/approval UI and notification centre.
5. Keep chat free for new messages while long jobs run; display single final handoff in any client.

**Exit gate:** robust cancellation, duplicate-event handling and live status after reconnection; no default clutter for normal chat.

### C10 — Production hardening and release

1. Integrate unit, contract, E2E, chaos, performance and security tests into CI; never depend only on Python syntax + Vite build.
2. Run representative Jace benchmarks: simple chat, actual tool use, research, coding, privacy fail-closed, cross-provider failover and cost enforcement.
3. Stage release on VPS with provider credentials in a server-side secret store; verify rate limits, spend ceilings, TLS and audit redaction.
4. Cut over one capability at a time: OpenAI chat → Anthropic chat → memory/embeddings → Agent Director → multi-model verification.
5. Roll back on error spike while preserving saved state; document migration and recovery.

**Exit gate:** no Ollama or GPU required for the normal Jace experience; background task receipts and citations are robust; provider failure degrades predictably.

## 11. Detailed future roadmap (retained and updated from v1)

These are not discarded. Move them behind the new foundation, preserve working features, and prioritise dependencies:

### Phase 4B — Device and computer runtime

- **4B.3 Persistent terminals:** PowerShell, CMD, Bash/WSL sessions, cwd/env/state, stdin/stdout/stderr, exit codes, interruption, owner/device, audit. VPS requests go through outbound authenticated Device Agent rather than server-local shells.
- **4B.4 Applications/processes:** discover apps and processes, CPU/memory, launch/stop with approval, relate running processes to projects.
- **4B.5 Screen/computer use:** screenshots, window targeting, accessibility/UI actions, focus verification, bounded click loops, approval for sensitive actions.
- **4B.6 Computer context:** active editor, recent files, terminal sessions, dev servers and errors as a short-lived signed context snapshot; no stealth data capture.

### Phase 4D — Projects and knowledge

- **4D.1 First-class Projects:** logical object across repositories, devices, directories, chats, sites, contacts, tasks and files.
- **4D.2 Project Intelligence:** indexed stack, symbols, imports, entry points, tests, Git state, recent diffs, known issues, scoped read evidence, incremental refresh.
- **4D.3 Provenance-aware memory:** source references, observed/learned timestamps, confidence, scope and stale/contradicted state.
- **4D.4 Automatic memory:** extract lasting decisions/preferences, deduplicate, reconcile contradictions, explain provenance, allow review, forget and export.
- **4D.5 Working memory:** workflow checkpoints, files inspected, commands run, failed approaches and next steps; separate from long-term memory.
- **4D.6 Knowledge graph:** people, orgs, devices, systems, repos, domains, relationships and sources with confidence and permission scoping.

### Phase 5 — Agents v2

- **5A Agent Runtime v2:** configurable persistent workers, queues, permissions, model policies, execution limits, skills, history and Agent Office state.
- **5B Agent Director v2:** graph planner/executor, dynamic selection of specialist providers, dependency waits, recovery and progress.
- **5C Evidence contracts:** verified facts vs inference, machine receipts and independent review.
- **5D Background jobs:** durable, resumable workflows, notifications, single handoff, ability to continue between devices and conversations.

### Phase 6 — Proactive execution controls

- **6A Scheduled automations:** cron/interval/timezone, scoped capability grants, history and next-run UI.
- **6B Event-driven triggers:** new email, calendar changes, commits/CI, file events, device status, deduplication and rate limiting.
- **6C Conditional monitoring:** server/disk/service checks, price or external dependency watches, relevance thresholds, cooldowns and consolidated notifications.

### Phase 7 — Technical workspaces

- **7A Git/GitHub intelligence:** diffs, history, branches, PRs, reviews, issues, CI, repos across devices, safe write flows.
- **7B Coding workspace:** call graphs/symbols, targeted tests, unused code hints, patch bundles, two-model code review, rollback and branch-based execution.
- **7C Research v2:** source corpus, claims, citations, contradiction graph, temporal validity, exportable research dossier.
- **7D Browser automation:** structured browser sessions, accessibility-first interaction, downloads/uploads, consent/approval for high-impact submission.

### Phase 8 — Communication and relationships

- **8A Communication Hub:** Gmail and Outlook unified threads, search, attachments, linked tasks/projects, safe drafting and approved sending.
- **8B Calendar v2:** Google/Microsoft/own calendars, deduplication, colours, cross-day events, availability, recurrence, attendee handling, travel buffers and preparation.
- **8C Contacts/People:** verified contact IDs/aliases, organisations, meetings, emails, projects; no guessing recipient addresses.

### Phase 9 — Work management

- **9A Tasks:** priorities, due dates, owner, dependencies, status, source, projects, conversion from emails/meetings/issues.
- **9B Briefings:** daily/work/project recaps from actual tasks, emails, meetings, CI and agent reports; no invented state.

### Phase 10 — Voice, media and notifications

- **10A Voice v2:** low latency, cloud or local STT/TTS settings, streaming, interruption/barge-in, device audio routing, no reliance on VPS audio hardware; one Jace persona.
- **10B Media:** playback, control, progress, queues, device-owned media and context-aware voice commands.
- **10C Notifications:** deduplicated actionable messages for work completion, approvals, failures and health, optionally spoken.

### Phase 11 — OSINT and structured investigations

- **11A Cases:** case boundaries, subject/organisation/domain, scope, lawfulness and provenance.
- **11B Entity graphs:** evidence-linked relationship graphs and confidence classification; protect privacy and avoid unsupported identity attribution.
- **11C Collection:** lawful public web/DNS/WHOIS/repos/metadata with collection rules, source hashes, time stamps and deduplication.
- **11D Reporting:** sourced dossiers with methodology, findings, limitations, confidence, timelines and export to PDF/DOCX.

### Phase 12 — Security, recoverability and diagnostics

- **12A Secrets:** vault/keychain boundaries, rotation, encryption, no credentials in prompt/logs/code or shipped desktop builds.
- **12B Permissions:** capability grants, duration, user/device/project scope, revocation, high-impact ask-every-time.
- **12C Audit/replay:** redacted trace of why an agent acted, which permissions applied and what evidence verified results.
- **12D Crash recovery:** leases/heartbeats, orphan handling, resume/retry/uncertain states.
- **12E Migrations/backups:** versioned Postgres migrations and tested encrypted restore/rollback.
- **12F Diagnostics:** provider, API, workers, device connections, tools, auth, audio and data stores with detailed remediation.

### Phase 13 — Extensibility

- **13A Plugin/skill SDK:** typed manifests, tool rights, settings, events, dependencies, sandbox and versioning; Docker/cloud/home automation adapters later.
- **13B Custom Agent Builder:** configure role, prompt, model policy, knowledge, tools, project/device access, appearance and limits.
- **13C Advanced routing:** quality/price/latency telemetry, experiments, fallback strategies, local/cloud hybrid and contextual allocation of reviewers.
- **13D Cost/performance:** reports, budgets, prompt cache statistics, rate limits, worker quotas and alerts.

### Phase 14 — Distribution and clients

- **14A Install/update:** signed installer, safe migration, automatic updater with rollback and state retention.
- **14B First run:** choose local/remote, pair device, sign in, connect providers and integrations, verify mic/voice and authorise tools.
- **14C Tray/background service:** independent of desktop window lifecycle, start-on-login, notifications and device presence.
- **14D Windows integration:** native notifications, context menu 'Ask Jace', app/process management, file protocol links.
- **New 14E Web + mobile:** shared authenticated API and state, responsive clients, paired device selection, secure file transfer and push notifications.

### Phase 15 — Guarded autonomy (last)

Jace can suggest or initiate bounded, user-defined goals, such as spotting CI failure, opening an investigation and proposing a fix. It cannot circumvent privacy, tool permissions or budgets. Mutating actions follow established approval/evidence contracts. Provide goal dashboard, pause/kill switch, scopes, quiet hours, self-tests and audit. Avoid a generic unrestricted 'do anything' mode.

## 12. Future model collaboration enhancements (after C10)

- Calibrate verifier selection: which tasks benefit from a second provider, given extra cost and documented accuracy change? Use held-out benchmark tasks and known incorrect answers.
- Multi-model council only for rare high-stakes architecture/research decisions; avoid majority-vote confidence theatre.
- Specialized expert policies for cybersecurity, code security, research, documentation and multimodal tasks without enabling prohibited or unapproved actions.
- Evidence-backed confidence scoring, automatic re-search when citations become stale, and tests for false confidence.
- Provider portability: version-agnostic prompts, evaluations, model migration and re-run comparisons without changing Jace identity.
- Local/private inference as optional future on-device GPU or CPU feature, with offline mode that works independently and never silently sends secrets to a cloud model.

## 13. Suggested code organisation

Proposed locations; **not a claim they already exist**:

```text
backend/jace/model_gateway/
  types.py  gateway.py  registry.py  routing.py
  providers/ollama.py  providers/openai.py  providers/anthropic.py
  normalizers.py  retry.py  telemetry.py
backend/jace/intelligence/
  classifier.py  policies.py  orchestration.py  synthesis.py
backend/jace/verification/
  claims.py  evidence.py  citations.py  reviewers.py  receipts.py
backend/jace/research/
  search.py  retrieval.py  snapshots.py  extract.py
backend/jace/workflows/
  models.py  runner.py  outbox.py  checkpoints.py
backend/jace/billing/
  usage.py  pricing.py  budgets.py
backend/jace/security/
  provider_secrets.py  outbound_policy.py
backend/tests/
  contract/  integration/  regression/  fault_injection/
apps/desktop/src/
  (existing chat, office and settings; add provider/workflow/evidence views)
```

Do not add a second competing tool registry or Agent Director. Refactor code behind existing services and expand them with tests.

## 14. Persistent state additions

Versioned database migrations should introduce or extend:

- `providers`, `provider_accounts` (credential *references*, not plaintext), `model_profiles`, `model_routes`, `model_health`, `model_prices`;
- `model_invocations` and `usage_ledger` (provider, model, conversation/workflow, tokens, cost, timing, errors, status, request ID);
- `workflows`, `workflow_steps`, `workflow_dependencies`, `workflow_checkpoints`, `workflow_events`, `notification_outbox`;
- `evidence_sources`, `source_snapshots`, `evidence_excerpts`, `claims`, `claim_evidence`, `verification_reviews`, `action_receipts`;
- `project_privacy_policies`, `model_budget_policies`, `user_model_preferences`, `tool_grants`, and retention/audit metadata.

A database migration should preserve existing conversations, memory, device registration, OAuth connections and tool permissions. Test migration and rollback against a scrubbed representative copy of existing SQLite data before production cutover to Postgres. Preserve old model string as message history metadata; map active conversation preferences to route policies.

## 15. Minimum test matrix and quality gates

| Scenario | Minimum expected outcome |
|---|---|
| OpenAI chat | Genuine streaming output, correct stop and usage; no Ollama |
| Anthropic chat | Same canonical event semantics and tools |
| 100 quick-turn tests | No canned/repeated response leakage; no duplicate UI messages |
| Broken provider | Compatible other cloud model automatically takes over only when allowed |
| Invalid API key | Clear actionable error; no infinite retries |
| Stopped Ollama | Cloud chat, memory, Director and embedding paths remain usable |
| Privacy-local task | No outbound provider call when cloud denied |
| Dangerous tool | Requires authorised approval before real action |
| Chat change | Worker completes and result is persisted/delivered once |
| Worker restart | Recover or mark uncertain; no hidden loss or duplicate side effect |
| Research claim without evidence | Not labelled verified; fabricated citation rejected |
| Contradictory sources | Visible discrepancy and explicit uncertainty |
| Code patch with failing tests | Report failure, never 'fixed' |
| Model costs exceed task budget | Pause/abort gracefully; no unbounded spend |
| Database crash/restore | Restored messages and workflows are consistent |
| Prompt injection in source | Cannot change system policy or grant capabilities |

Benchmark with a stable evaluation set spanning short factual chat, tool calls, code fixes, citations, privacy, agent handoffs and VPS failures; record accuracy, p50/p95 time-to-first-token, completion rate, tool errors, hallucinated claims, source precision and cost per resolved task. Prefer demonstrated quality over broad promises.

## 16. Release milestones / recommended work order

**Milestone 1 — Jace speaks reliably from VPS:** P0 + C1–C3. OpenAI and Anthropic providers, real streamed chat, correct model list, no Ollama requirement. Keep normal UI and memory accessible.

**Milestone 2 — No hidden Ollama dependency:** C4–C5. Memory, embeddings, Director, vision and fallback route properly; user controls provider selection and budgets.

**Milestone 3 — Jace can prove work:** C6 + C8 (core evidence). Trustworthy tool receipts, source records and durable handoffs.

**Milestone 4 — Jace coordinates models:** C7 + remainder of C8. Independent reviewers, verified research and coding workflows, clear conflict resolution.

**Milestone 5 — Reliable multi-device Jace:** C9–C10 + 4B device work. Production UX, secrets, recoverability, robust connections and notifications.

**Milestone 6 — Personal AI environment:** phases 4D–10. Projects, memory, agents, automations, communications, voice, web/mobile and OS integration.

**Milestone 7 — Professional specialist system:** phases 11–14. OSINT, reports, plugin SDK, custom agents and packaged clients.

**Milestone 8 — Guarded autonomy:** phase 15, after verification, budget and permissions prove dependable.

Workstreams can overlap carefully (for example UX design alongside adapters; provider privacy tests alongside integration) but avoid introducing high-risk autonomy before runtime security is mature.

## 17. Immediate next development package

Create one branch, for example `feature/cloud-intelligence-foundation`, and deliver a small cohesive change set:

1. Repo/data safety fixes and confirmed VPS service inventory.
2. Provider capability/stream type contract and integration fixtures.
3. Secure config for API keys, cloud egress policy, OpenAI provider and Anthropic provider.
4. Gateway registration with safe `provider:model` routing and canonical error mapping.
5. Remove hard dependency on Ollama preloading for cloud routes, and add a cloud chat smoke-test endpoint/test suite.
6. Maintain UI compatibility initially; expose correct provider and model in status without leaking secrets.
7. Automated tests covering streaming, tools, failed provider and two-provider switch.
8. Deploy to staging, test end-to-end, then promote with rollback capability.

**Deliberately exclude** advanced verification, full memory migration and speculative user-interface redesign from the first code package. Finish the dependable cloud-first chat path first, then bring over auxiliary inference and finally implement collaborative intelligence.

## 18. Principles that must never be weakened

1. Jace identity, personality, memory and authorisation are independent from cloud models.
2. No provider, agent or document can override privacy or approval policy.
3. No model can assert success without evidence appropriate to the action.
4. No unsolicited external upload of local-only or secret-classified information.
5. No provider-specific state as the sole copy of memory/workflow data.
6. No uncontrolled retries of mutating tools or silent duplicate execution.
7. No disappearing agent results on chat change or worker restart.
8. No uncontrolled agent swarms or unbounded API spending.
9. No local machine command executed directly by an untrusted VPS-hosted model.
10. No unnecessary rewrite of working existing Jace systems.

## 19. Documentation references

- Original Jace roadmap, 19 September 2026 (attached in conversation).
- Current source: https://github.com/BenWaters2004/Jace
- OpenAI Models: https://developers.openai.com/api/docs/models
- OpenAI Responses and web citations: https://developers.openai.com/api/docs/guides/tools-web-search
- OpenAI API prices: https://developers.openai.com/api/docs/pricing
- Anthropic model overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic streaming: https://platform.claude.com/docs/en/build-with-claude/streaming
- Anthropic web search: https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool

**Bottom line:** Move the intelligence, not ownership of the assistant, into the cloud. Release reliable provider-independent chat first; then reliable auxiliary inference; then evidence-based cross-model collaboration; then the rest of the computer, project, memory and autonomy roadmap.
