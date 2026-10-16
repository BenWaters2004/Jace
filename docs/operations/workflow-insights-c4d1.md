# C4D.1 — Agent Director Workflow Insights

C4D.1 is a front-end-only read-only addition to Agent Office's **SYSTEM** tab. The existing Pixel Office, worker dispatch, model gateway, agent permissions, database, checkpoints, and chat handoffs are unchanged.

## What is shown

- Recent Agent Director workflow IDs, grouped from the existing `/agents/tasks` task snapshot. The office currently fetches at most 100 tasks, so this is **not an exhaustive history**.
- Queued/active/completed specialist task counts, recorded recovery markers, and recovery quarantine warnings (`metadata.recovery_quarantined === true`).
- Names of models recorded on specialist task records, *if available*. The panel does not infer model usage from configuration.
- Whether specialist task records show use of `read_workspace_file` or `read_web_page`; this is not the number of sources or claim verification.
- Configuration status from Jace's existing authenticated read-only `GET /collaboration/status` endpoint. This does not prove providers were called or the requested review completed.

## Limitations and future phases

This phase does not show durable checkpoint table rows or stored review receipt detail because existing authenticated read-only APIs do not expose those safely. Those need a purpose-built actor-filtered endpoint and privacy review. For a completed cross-provider assessment, inspect the Director's final chat handoff. C4D.2 will add deeper review insights with explicit permissions and ownership checks.

## Security

- No backend changes, migrations, new tool permissions, Git operations, or provider calls.
- Uses the same authenticated API helper used elsewhere in the desktop app.
- No raw source text, tool arguments, file contents, secrets or signed URL queries are shown.
- Follow the existing P0 repository hygiene warning: public GitHub history may contain `data/jace.db`. Do not push database files or secrets.

## Installation

Run `apply_jace_c4d1.ps1 -RepoRoot C:\Users\Ben\jace -DryRun`, then apply, then verify. Backups are stored alongside the installer. Restart/rebuild the desktop application to load the new UI. Server restart is not necessary.
