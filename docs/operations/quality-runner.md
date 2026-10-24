# Phase 0A — Unified quality runner (initial baseline)

This is an **incremental** quality gate. It does not claim live cloud, database, device or production acceptance. No model calls, external integrations, or private database reads occur in `quick`.

## Profiles

| Profile | Executes | Exit policy |
| --- | --- | --- |
| `quick` | Layout, Python in-memory compile, runner self-tests, tracked-file audit | Fails syntax/self-test errors; **warns** for previously tracked private/generated files |
| `full` | `quick` plus backend `unittest discover` and desktop `npm run build` | Fails failing tests; incomplete if npm/dependencies unavailable |
| `security` | `quick` plus **strict** tracked-file hygiene and honest secret-scanning gap | Fails tracked violations; otherwise reports incomplete until scanning is integrated |
| `integration`, `live-provider`, `device`, `recovery`, `production-smoke` | Placeholder acceptance tracks only | **BLOCKED**, never reported as passed |
| `all` | `full`, strict security audit and unimplemented acceptance tracks | Fails or incomplete until all tracks are implemented |

Statuses: **PASS** (executed and succeeded), **WARN** (issue known and shown), **FAIL** (ran and failed), **NOT_CONFIGURED** (required infrastructure absent), **BLOCKED** (harness is not yet implemented). `PASS_WITH_WARNINGS` exits 0 for baseline adoption, but never means security complete.

Run on Windows from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile quick
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile full
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile security
```

Run on Linux or in CI:

```bash
python3 tools/jace_quality.py --profile quick
python3 tools/jace_quality.py --profile full
```

`full` requires Python dependencies (`backend/requirements.txt`) installed in the selected interpreter and `npm ci` in `apps/desktop`. It uses the repository's `backend/tests` offline unittest suite, not historical ad hoc scripts. It does not install anything, contact the VPS or reset any database.

The reports are `data/quality/last-run.json` and `.md` (ignored by current root `.gitignore`). **Test process output is deliberately not copied into reports** because third-party or local failures can print credentials, machine names or paths. Rerun a failing step interactively to see detailed errors.

## Current security debt

A review of GitHub `master` on 18 October 2026 found a tracked `data/jace.db` plus thousands of tracked files in `backend/.venv` and tracked patch-backup material. The audit reports **path categories/counts only**, never reading the DB or source content. A passing `quick` with warnings is only a migration convenience; `security` intentionally does **not** pass.

After confirming a protected backup of local data, inspect (read-only):

```powershell
git ls-files -- data/jace.db backend/.venv .jace-patch-backups
git status --short
```

After choosing exactly what to preserve, stop tracking generated content *without deleting local files*:

```powershell
git rm --cached -- data/jace.db
git rm -r --cached -- backend/.venv
# Evaluate .jace-patch-backups privately before deciding what to untrack.
```

Commit hygiene separately. **Removing files from HEAD does not remove them from Git history.** Investigate leaked credentials privately, rotate affected keys, plan history remediation with collaborators, and test new clones. Do not automatically delete tracked DBs or venv directories in a patch installer.

## Release workflow

The package adds `.github/workflows/quality-gates.yml` for pull requests. To also require the quick profile *before the existing `deploy-vps.yml` deploy job*, install with `-EnableDeployGate`. The installer recognises the exact syntax-check anchor, saves the previous workflow in LocalAppData, and refuses to edit an unfamiliar layout. Quality reports are uploaded for diagnostics. To require this PR check before merging, configure the repository's branch protection/ruleset accordingly.

Before a production push, run `full` locally. Currently the GitHub quick gate does **not** run backend integration tests, secret scanning, or live-cloud calls. These are future Phase 0B/0C acceptance work. Do not interpret its success as end-to-end readiness.
