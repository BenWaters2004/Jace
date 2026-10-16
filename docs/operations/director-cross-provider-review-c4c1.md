# C4C.1 — Agent Director cross-provider excerpt review

**Status:** opt-in runtime bridge; disabled by default. **No automatic tool execution.**

This integration runs after the Agent Director's normal specialist execution and synthesis, but before the usual single handoff is persisted into the original conversation. It uses the already-recorded successful `read_workspace_file` results from completed Director child tasks. The existing model gateway and C4B.1 claim/excerpt reviewer do three separate calls across the two configured cloud providers.

## Opt-in configuration

After live provider tests, set the following in the backend's **private** `.env` (not Git):

```dotenv
JACE_COLLABORATION_ENABLED=true
JACE_COLLABORATION_EVIDENCE_ENABLED=true
JACE_DIRECTOR_CROSS_REVIEW_ENABLED=true
JACE_COLLABORATION_DRAFTER_ROUTE=openai:<actual-id>
JACE_COLLABORATION_REVIEWER_ROUTE=anthropic:<actual-id>
JACE_PRIVACY_ENABLED=true
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
```

Exact model IDs depend on your account and installed C1 gateway providers. First test on staging, not a public VPS. Protect credentials and any source data entrusted to cloud models. This option incurs up to three additional billable model calls per Director workflow with eligible source reads.

## Behaviour and scope

- Review input comes only from successful, saved, bounded, Core-approved `read_workspace_file` tool events. A worker's prose and manufactured `READ` blocks cannot qualify as sources.
- **No new workspace access, search, shell operation, code write, Git action, or change to Jace tool permissions.** Existing user approvals and audit for the original reads remain authoritative.
- Review drafts its own claims and uses a second provider to check quote anchors against the captured snippets; it does **not** prove the final Director answer factually true.
- The Director's original synthesis is preserved. A clearly labelled assessment appendix is added to the same existing handoff, not a second chat message.
- If no suitable captured read exists, a short skipped notice is appended with no new model API calls.
- A reviewer/provider failure adds an *incomplete* notice; it does not prevent the original handoff. Cancellation propagates.
- The existing Director event is supplemented with `agent.director.cross_review` containing only status and counts, not prompts, source text, file names, or model outputs.
- **Web research, independently fetching source evidence, retryable/durable review checkpoints, reviewer access to tests, and full claim-to-final-answer verification are not part of C4C.1.** These belong to later milestones.

## Checks

Install with `-DryRun`, `-Verify`, and use `-Rollback` to restore only C4C.1-owned changes (provided no subsequent edits were made to those files). Source checksums are local to the recorded installation. Do not commit source, credentials or archived databases until the Git index has been reviewed.

Note that upgrades following C4C.1 will make exact checksum verification of earlier packages stale for files they subsequently extend. Verify the newest package after each installation.
