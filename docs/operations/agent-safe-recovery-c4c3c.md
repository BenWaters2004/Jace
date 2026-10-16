# C4C.3C — Agent Manager recovery safety

## Scope and safety boundary

When `JACE_AGENT_SAFE_RECOVERY_ENABLED=true`, Agent Manager examines persisted `tool_*` and `approval_*` events, the task's `used_tools_json`, and agent-scoped `ToolAuditLog` entries *before* returning unfinished tasks to its executor queue. If any are present (or metadata is corrupt), it marks the task `failed` with a `recovery_quarantined` event and leaves it unqueued. The same check runs after an unexpected executor exit. Existing task retry refuses quarantined tasks, regardless of subsequent feature-toggle changes.

This deliberately blocks even read-only interrupted tasks because Jace cannot prove effects by looking at logs. Completed tasks are left intact and tool-free interruptions can recover as before. Cancellation takes precedence. No new database table, tool permission or cloud provider call is introduced.

**Do not confuse this with exactly-once execution.** It is an at-most-once-*automatic replay* safety boundary based on persistently recorded intent, not transactional fencing of side effects outside Jace. Actions that were triggered by external processes, tools that do not record a start event, and concurrent Core instances remain unprotected. This feature does **not** implement distributed leases or approval replay; keep one Core process per database.

## Operational response to a quarantined task

1. Inspect task ID, event history and tool audit in Jace. Check the external service or filesystem for completed side effects before attempting anything else.
2. Do **not** use the existing Retry action; it is blocked. Create a new task only after explicitly assessing and approving any potential duplicates.
3. For an interrupted Director specialist, report the affected step as incomplete. The Director's existing evidence guardrails must not promote it to verified.

## Enable only after validation

```dotenv
JACE_DIRECTOR_DURABLE_HANDOFFS_ENABLED=true
JACE_DIRECTOR_WORKFLOW_CHECKPOINTS_ENABLED=true
JACE_AGENT_SAFE_RECOVERY_ENABLED=true
```

Core startup reads flags from environment. Back up database, test with one worker first, and check final handoffs and worker restarts. Stop Jace Core before applying source updates. Installer rollback restores source files but cannot reverse any task-state changes made while enabled. Never deploy to a multi-worker VPS until distributed lease/action idempotency is addressed.

## Git hygiene

Prior installer checks detected `data/jace.db` tracked in Git. Investigate the data and repository history before any public push; adding `.gitignore` or removing the current index entry does not scrub previous commits. Protect local DB files and checkpoint backups from cloud sync and public artifacts.
