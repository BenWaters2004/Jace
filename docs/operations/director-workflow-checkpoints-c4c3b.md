# C4C.3B — Persistent Director workflow checkpoints

## Scope

Adds one opt-in SQLAlchemy table (`director_workflow_checkpoints`) and checkpoints at these boundaries:

1. **Planned:** after the Director finishes building a validated plan, before child tasks are dispatched; enables recovery even if zero child tasks were created.
2. **Synthesized:** after the combined model text is fully received; reuse it after restart rather than requesting another synthesis.
3. **Reviewed:** after optional cross-provider review is complete; reuse the exact resulting handoff text and sanitized counters without rerunning the reviewer.
4. **Completed:** after the unique C4C.3 handoff receipt is committed; keeps the checkpoint from being recovered again.

The workflow/Agent Director still owns tool approval, execution, recovery and the one final chat handoff. This release does **not** replay tool calls from checkpoints.

## Deployment

Backup your Jace database with the Core stopped, then install/verify locally before enabling:

```dotenv
JACE_DIRECTOR_DURABLE_HANDOFFS_ENABLED=true
JACE_DIRECTOR_WORKFLOW_CHECKPOINTS_ENABLED=true
```

Run only a **single Core Director worker** while checkpoint recovery is enabled. The unique database handoff receipt blocks duplicate final saved messages, but the execution scheduler does not yet hold a distributed workflow lease. Multiple workers could race and duplicate work before reaching handoff persistence.

**Sensitive data:** the checkpoint table stores complete user objectives, plan details and model-generated synthesis/review text in Jace's existing database, without independent encryption. Protect backups, restrict database access, and never commit `data/jace.db` or runtime DB snapshots. Existing tool permission and privacy settings still apply to model calls; enabling checkpoints does not grant cloud egress.

## Limitations and recovery warnings

- A crash before the first plan checkpoint is committed still cannot be recovered automatically; no durable job acceptance receipt yet.
- A crash during an outbound model request, before its result is persisted, may lead to that request running again. Provider calls are not exactly-once.
- A crash during an external tool side effect cannot be made exactly-once using local checkpoint state. Recovered unfinished tasks with recorded tool/approval attempts are flagged for manual review; this does not override or prevent the separate Agent Manager's recovery scheduler, which must be audited before enabling autonomous side-effecting workflows on the VPS.
- No new write/edit/execute permissions are added; don't assume recorded source evidence proves factual truth.
- The `completed` checkpoint marker can lag the unique handoff receipt across a crash; the receipt remains authoritative and a recovery attempt reuses that committed handoff.
- The installer does not alter databases. On first Core start after install, `init_database` registers the table and creates it. Source rollback leaves the table and checkpoint history intact.

## Safety testing

Verifier runs import-order probes and C4C.3B tests plus C4B/C4C regression suites (when present). All tests are offline. It does not deploy to the VPS or push a Git commit.
