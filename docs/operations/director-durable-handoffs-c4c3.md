# C4C.3 — Durable Agent Director handoffs and retry safety

**Status:** opt-in after backup and validation; not a guarantee of exactly-once external actions.

## Why

The older Director wrote an assistant handoff and then marked workflow tasks finalised separately. If Jace stopped after saving the message, recovery could synthesize again and write a second assistant message. C4C.3 adds `director_handoff_receipts` with a unique workflow ID, commits each receipt and chat message in *one database transaction*, and checks the receipt before restarting a recovered Director workflow.

The receipt records workflow ID, optional conversation and message IDs, a SHA-256 of the result, review status and an allowlisted set of numerical review counts. It does not persist a second copy of the answer or tool arguments.

## Execution boundaries

- A Director workflow with an existing receipt does not rerun models or specialist tasks; it reconciles prior task finalisation and emits a UI refresh event.
- If a failed specialist has *any* tool/approval event or previously used tool, its automatic retry is skipped. The failure remains visible. Users can manually decide what to retry after checking side effects.
- Recovery of a workflow that failed *before a receipt was committed* can still repeat model calls; provider billing may recur. An upstream task or tool that executed but never saved an event is not covered.
- Existing task-recovery and time-of-crash edge cases (including pre-first-task crashes), UI event de-duplication, and cross-process workflow leases remain future work. Events may be delivered more than once; persisted handoffs are idempotent.
- If the original conversation was deleted, a receipt with status `no_conversation` is stored, but no new chat message is created.
- Enabling this mode creates a new table at the next Core startup. Application rollback does **not** drop that table; do not delete it just to undo the software patch.

## Local rollout

1. Back up the Jace database before deployment, and test on the local checkout first.
2. Run `-DryRun`, apply, run `-Verify`, restart Core and confirm `director_handoff_receipts` exists in the configured database.
3. Set `JACE_DIRECTOR_DURABLE_HANDOFFS_ENABLED=true` in the server-side `backend/.env` and restart Core.
4. Send a harmless read-only agent request (e.g., inspect an approved workspace file). Check exactly one `agent:director` handoff appears, and verify the `agent.director.completed` event references its message ID.
5. Interrupt a test workflow only in a disposable environment. Verify a persisted receipt prevents a second handoff.
6. Do not deploy blindly to the VPS; source patch verification does not check the live database backup, security policy or deployment health.

## Reset / rollback

Use the package `-Rollback` switch **only if its installed file checksums are still unchanged**. Stop Jace Core before applying or rolling back. Rollback restores original source files and retains the new database table and rows. Never delete historical receipts until retention and recovery implications have been reviewed.

## Privacy

No additional prompts, full source excerpts or secrets are written into the new receipt. The existing Director chat message may include source details as before. This release does not grant tools or change privacy egress policy.
