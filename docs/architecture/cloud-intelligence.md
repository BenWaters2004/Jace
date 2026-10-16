# Cloud intelligence orchestration (proposed)

**Status:** architecture proposal — **not yet implemented**. **Baseline:** 16 October 2026.

## Decision

Jace Core owns the conversation, identity, personality, memory, context and workflows. External model providers perform scoped inference behind a Model Gateway; they never become authoritative for Jace's state or action permissions. The VPS is the control plane; authorised Device Agents, cloud integrations and constrained workers are execution planes.

The immediate issue driving this work is that CPU-only Ollama inference on the VPS is too slow/unreliable for ordinary conversations. The primary path will use hosted model APIs, while a local-only inference option remains available when separately configured. This must not silently turn private-only requests into cloud requests.

## Request lifecycle

```text
Authenticated request
  -> conversation/project + context selection
  -> privacy classification and outbound policy
  -> request classifier (latency, risk, tool needs, input type)
  -> capability route + provider health + budget
      |- quick: one fast model -> streamed answer
      |- balanced: one capable model -> streamed answer/tools
      `- research/complex/risky: Director -> durable task graph
           |- source/tool investigation
           |- production (analysis/code/draft)
           |- independent review of evidence and output
           `- synthesis with explicit verification status
  -> store Jace-owned result/events/usage
  -> deliver once to the correct conversation + notifications
```

## Runtime routing (target policy)

| Route | Default behaviour | Constraints |
| --- | --- | --- |
| `conversation.fast` | One low-latency, lower-cost model | No multi-model orchestration by default |
| `conversation.balanced` | Capable general model | Tool calls still require Jace authorisation |
| `reasoning.high` | Strong reasoning model | Optional independent review for consequential results |
| `coding.high` | Specialist model and real repository context | Diff review and build/test receipts where applicable |
| `research.high` | Jace-owned retrieval, source synthesis | Citation and retrieval evidence required |
| `research.verify` | Reviewer preferably from a different provider | Must inspect primary evidence; no majority-vote shortcut |
| `workflow.plan` | Director task graph | Deterministic schema/dependency/permission validation |
| `workflow.synthesise` | Final coherent answer | Cannot override recorded contrary evidence |
| `memory.extract` | Cheap structured-output model | Validated schema and provenance |
| `embedding` | Dedicated embedding backend | Index versions/dimensions tracked; reindex when changed |
| `vision` | Model supporting images | Policy gate screenshots/documents before egress |
| `local.private` | Local-only model | Refuse/queue if absent; never silently send to cloud |

These extend the currently implemented capability set. Introducing a route name in a document **does not make it available in current code**.

## When to use multiple models

Use multi-model work only when the task justifies the additional expense and latency. Examples: complex software changes, high-stakes investigation, source-based research, substantial architectural planning and long reports requiring independent fact checks.

For a simple chat, a second model adds delay, cost and extra failure opportunities. Jace should expose an optional manual review request, not create an invisible swarm for every greeting.

### Sample code workflow

1. **Director** makes an evidence-required task graph and tool scope.
2. **Inspector** reads relevant source and build output using allowed tools.
3. **Implementer** writes a proposed diff on an approved branch/worktree.
4. **Reviewer** (preferably different provider) evaluates logic, regression risk and security using the actual diff and source evidence.
5. **Execution verifier** runs build/tests and records process exit codes and log references.
6. **Director** returns confirmed changes, failed checks and explicit unknowns; never reports unexecuted changes as successful.

### Sample research workflow

1. Search and retrieve sources using explicit web/research tools.
2. Save URL, retrieval time, document metadata and relevant extracts.
3. Researcher composes claim-to-source mappings.
4. Independent reviewer checks whether each claim is actually supported, searches for contradictory primary evidence and identifies stale or circular citations.
5. Director reconciles disagreements and labels unsupported claims; a second model agreeing without reviewing sources does not count as verification.

## Collaboration policies

- **Role isolation:** reviewer should not be forced to accept the first writer's assertions; provide independent source snippets and an evidence manifest, not just the writer's answer.
- **Deterministic checks:** compilation, HTTP status, provider event ID and hashes outweigh model confidence.
- **Structured handoffs:** every step records inputs/outputs, status, model+provider, source IDs, verification verdict, budget and artefact references.
- **Bounded operation:** cap model turns, tool steps, source fetches, parallel agents, deadlines and spend. Honour cancellation.
- **Persistent execution:** a workflow must survive UI reconnection and be recovered or marked uncertain after a worker restart. Never silently disappear.
- **Write safety:** no unapproved email sends, destructive commands, commits or publication. Use existing capability and approval services, not a second permission mechanism.
- **Prompt injection:** external pages/source files are untrusted content; instructions embedded in them cannot grant tools, access additional data or change privacy policy.
- **Provider fallback:** a compatible alternative may be tried only if policy allows it. Streaming fallbacks must avoid duplicate partial answers and duplicate tool actions.

## Data ownership and privacy

Protect credentials, private files, project secrets and customer data *before* external model calls. Jace must determine the data classification and whether cloud egress is authorised. The existing protected-cloud transformer is a foundation, not a guarantee that all PII is covered. Do not enable bulk external inference until representative tests pass.

Track a provider-independent invocation log with timestamps, request IDs, token/usage metadata, structured errors and cost estimates, excluding raw secrets and sensitive tool inputs.

## Where to implement

Preserve `backend/jace/model_gateway/`, `backend/jace/privacy/`, `backend/jace/agents/`, the current agent/tool registry, `backend/jace/api/chat.py`, agent handoffs and shared runtime events. Extend these rather than adding a competing orchestration core.

- Provider semantics: [cloud-provider-contract.md](cloud-provider-contract.md)
- Verification: [verification-and-evidence.md](verification-and-evidence.md)
- Actual milestones: [implementation-tracker.md](../roadmap/implementation-tracker.md)
- Full long-term requirements: [master roadmap](../roadmap/cloud-first-master-roadmap.md)
