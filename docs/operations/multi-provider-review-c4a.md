# C4A — Cross-provider editorial review (first bounded slice)

**Status:** opt-in API prototype; no automatic director integration, retrieval, citation verification or workflow persistence.

## Purpose

A deliberately small three-inference experiment that tests Jace-owned multi-provider collaboration. This does **not** attempt research or execute tools. An explicit authenticated `POST /collaboration/review` invokes:

1. Draft from `JACE_COLLABORATION_DRAFTER_ROUTE` (`openai:model` or `anthropic:model`).
2. Structured, skeptical review from `JACE_COLLABORATION_REVIEWER_ROUTE` on a **different provider**.
3. Revision by the original drafter.

Both outputs and the reviewer assessment are returned. Notes supplied by callers are not trusted source receipts. **`verification_status` is always `not_verified`**. The entire workflow makes a maximum of three model calls, with a configured bounded timeout. No model/tool-generated commands are run. Provider gateway rules, privacy egress, existing C3B rate limits and cost controls remain applicable.

## Enabling (explicitly)

Set in `backend/.env` **only after live cloud providers and the existing privacy policy have been tested**:

```dotenv
JACE_COLLABORATION_ENABLED=true
JACE_COLLABORATION_DRAFTER_ROUTE=openai:<actual-supported-model-id>
JACE_COLLABORATION_REVIEWER_ROUTE=anthropic:<actual-supported-model-id>
JACE_COLLABORATION_TIMEOUT_SECONDS=120
JACE_COLLABORATION_MAX_OUTPUT_CHARS=12000
```

You can reverse provider roles. Both full route IDs must exist, differ at the provider level, and be supported by your account. Use real API keys held server-side, never in this document or requests. Keep `JACE_PRIVACY_ENABLED=true` and explicitly authorise cloud egress (`JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true`) only for data you are permitted to send.

For a server-mode Jace Core, authenticate normally with a valid Bearer token; never disable auth for convenience. `GET /collaboration/status` reveals only readiness flags, not credentials.

### Example request

```json
{
  "objective": "Review a proposal for scaling the Jace worker queue. State failure modes and trade-offs.",
  "notes": [
    {"id":"user_brief", "content":"We prefer PostgreSQL for durable state and Redis for transient coordination."}
  ]
}
```

Response contains `draft`, `review`, `final_answer`, routes and explicit unverified status. Requests and notes are not automatically saved to Jace conversations. This API is **not connected to the desktop chat** in C4A.

## Non-goals and limitations

- No web retrieval, Git reading, evidence validation, or fact-check tools. Two agreeing models are not evidence.
- Notes may be malicious prompt injections; they are marked as untrusted, but do not use this feature with protected data until the broader security work has been reviewed.
- No persistent workflow checkpoints. An interrupted request may be billed for earlier calls but returns no completed result.
- Existing C3B cost limits are approximate/process-local. A three-call review can be materially more expensive than one chat.
- Jace does not change default fast chat or Agent Director. Later C4B will introduce an evidence-backed durable workflow with authenticated source receipts and scoped tool permissions.

## Recommended verification

After dry-run/install/verify: keep disabled by default. In a test Core, set the three C4A options and required cloud privacy/provider configuration. Call `GET /collaboration/status` as an authenticated actor, then make a non-sensitive test `POST /collaboration/review`; confirm the provider routes, explicit `not_verified` status, three-call bound and absence of tool actions. Try disabled mode, missing reviewer, same-provider routes, disallowed secret content and provider timeout. Examine reliability metrics for observed calls. Never expose API keys in logs or screenshots.
