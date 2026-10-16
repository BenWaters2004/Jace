# C4C.2 — Coordinated research and coding source review

C4C.2 extends C4C.1 with tool-captured public webpage evidence alongside approved workspace source evidence. It does not replace Agent Director, create a second worker scheduler, or execute tools during review. The existing research/code/files/analyst workers already collect evidence using Jace's normal Ask/Allow/Deny policies and approval UI.

## Processing

1. Agent Director plans specialists and runs them with their existing permissions. It records completed tool results in task events.
2. On successful `read_web_page`, the background runner recognises the *exact* untrusted web-tool JSON envelope and records a bounded excerpt, a SHA-256 of that excerpt, a sanitised URL with query/fragment removed, and a UTC timestamp. Malformed responses cannot count as web evidence.
3. On completed Director work, C4C.2 selects up to four unique successful `read_workspace_file` or `read_web_page` event receipts from completed specialist tasks. It excludes web-search snippets, failed reads, missing file checksums, and explicitly irrelevant workspace reads. Source selection includes both web and workspace classes where available.
4. If enabled, Jace calls the existing C4B.2 evidence-review pipeline (draft → independent cross-provider critique → final revision) using retrieved-source receipts. The privacy gateway must approve each cloud call.
5. The original Director synthesis is preserved. Jace appends a **separate** model review, including claim-to-excerpt counts. There is no automatic elevation of `UNVERIFIED` to `VERIFIED`, and source authenticity is not independently proven.
6. The existing Director handoff is persisted as before. Metrics-only `agent.director.cross_review` events include source counts and review outcome without source text, file paths or prompts.

## Configuration

Requires existing C4A/C4B.1/C4B.2 settings, model IDs, authorised cloud egress and provider credentials. New switch:

```dotenv
JACE_DIRECTOR_COORDINATED_REVIEW_ENABLED=true
```

The existing `JACE_DIRECTOR_CROSS_REVIEW_ENABLED=true` may remain set. C4C.2 supersedes C4C.1 when both flags are true, so there is **only one** extra review workflow per Director completion, not two.

`JACE_COLLABORATION_RETRIEVAL_ENABLED=true` is required because the C4B.2 evidence review checks genuine tool-source receipts. This switch does **not** set tool permissions to Allow. Web and workspace tools still require each background task's configured permission or interactive approval.

Each eligible workflow adds up to **three additional billable provider calls**. Use the existing provider request/budget controls and keep this off on production until staged tests pass. No full-file content is fetched anew during review.

## Safety and limitations

- **Text matching is not truth verification.** A source can be outdated, mistaken or manipulated; a successfully fetched document and a matching quotation do not prove a conclusion.
- Reviews concern a **separate newly generated evidence draft**, not the Director's actual final answer. No original findings are silently rewritten.
- Source excerpts are bounded to 4,000 characters per source, max 4 sources. Large projects need a later scoped evidence planning/indexing phase.
- A successful `read_web_page` event records what the tool returned, not a re-fetch. No dynamic browser rendering or automatic URL discovery is introduced.
- Existing task tool events may contain source snippets. Protect local databases and backups; redact source paths and user content from distributed logs.
- Approval for reading a file or webpage is separate from approval to send its contents to external models. Jace's cloud privacy controls must remain enabled, and sensitive projects should use local-only mode.
- C4C.2 doesn't implement durable billing ledgers, distributed locks, cross-provider tool execution, automatic code editing, or direct review of actual code diffs. These need later phases.
- Agent Director's existing resumed-workflow handling is unchanged; end-to-end idempotency/restart testing is still required before production use.

## Suggested staging checks

- Disable both review flags and confirm ordinary Director tasks are unchanged.
- Enable C4C.2 on a non-sensitive repository and ask for a code/workflow diagnosis. Check actual `read_workspace_file` receipts, the final handoff, source counts, and model costs.
- Ask for current official documentation and check the research agent obtains a `read_web_page` result through its normal permissions.
- With both flags enabled confirm only one assessment runs.
- Deny `read_web_page`, confirm no unsupported web evidence is treated as collected, and confirm the permission is not silently changed.
- Use a private/secret-bearing file to verify privacy-gated requests do not disclose source contents to a cloud model. Never place real secrets in a test fixture.

## Rollback

Use the upgrade's `-Rollback` command while the installed files still match its verification hashes. The installer does not change the database or `.env`. If a Git push triggers server deployment, test in a branch and deploy separately with a database backup and reviewed environment settings.
