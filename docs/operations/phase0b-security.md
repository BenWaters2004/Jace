# Jace Phase 0B — Git index cleanup and safe secret scanning

This package is incremental and does not change the Jace runtime, model routing or database schema. It addresses the known Security-profile failures from Phase 0A.

## 1. Before applying

Use a **feature branch**. Do not push a cleanup commit before examining the staged diff. Confirm backups are in a safe local directory not synced or shared publicly. The untracking script creates a consistent SQLite backup using `sqlite3.backup` and verifies `PRAGMA quick_check` before touching the index. No local file contents are deleted. The database backup is not encrypted automatically: protect the backup directory and delete it according to your retention policy once a separate, tested backup exists.

Run `scripts/phase0b-untrack.ps1` without `-Apply` first (read-only); then rerun with `-Apply` if you agree to stage removals from the Git index.

This does **not** alter the production VPS database. In particular, `data/jace.db` is excluded from the production deploy bundle but the public Git repository currently contains a past committed copy. Do not use production secrets inside a development checkout.

## 2. What's changed

- Adds `.jace-patch-backups/` to root `.gitignore` (the other two tracked categories were already ignored).
- Adds `scripts/phase0b-untrack.ps1`. This stages removal of only these **exact** paths: `data/jace.db`, `backend/.venv`, `.jace-patch-backups`. It never runs `git clean` or removes files from disk.
- Upgrades `tools/jace_quality.py` to execute an actual local Gitleaks check when available.
- Adds `tools/jace_secret_scan.py`: scans a *temporary snapshot of current staged Git index blobs only*. It excludes private/generated paths until they're untracked, refuses files that it cannot scan, suppresses scanner stdout/stderr and discards the temporary redacted findings report. No secrets or matching lines are recorded in normal Jace reports.
- Adds `tools/test_jace_secret_scan.py` with offline tests and `.github/workflows/security-gates.yml` with pinned Gitleaks installation in CI.

## 3. Local commands (PowerShell)

From the **extracted package** directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_phase0b.ps1 -RepoRoot 'C:\Users\Ben\jace' -DryRun
powershell -ExecutionPolicy Bypass -File .\install_phase0b.ps1 -RepoRoot 'C:\Users\Ben\jace'
```

From the **Jace repository root**:

```powershell
git switch -c security/phase0b-index-cleanup
powershell -ExecutionPolicy Bypass -File .\scripts\phase0b-untrack.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\phase0b-untrack.ps1 -Apply
```

Gitleaks is an external command-line dependency on Windows:

```powershell
winget install -e --id Gitleaks.Gitleaks
# Restart the terminal if required to refresh PATH.
gitleaks version
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile quick
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile full
powershell -ExecutionPolicy Bypass -File .\scripts\test-jace.ps1 -Profile security
```

After the staged cleanup:

```powershell
git status --short
git diff --cached --stat
git ls-files -- data/jace.db backend/.venv .jace-patch-backups
```

`git ls-files` must return **no entries** in those paths. The many staged `D` entries in `git status --short` are expected **index-only** removals. Check that local `data/jace.db` and `backend/.venv` still exist before committing. Use `git add .gitignore tools scripts docs .github/workflows/security-gates.yml` carefully and inspect staged changes, not `git add -f` for ignored files.

**Do not push while secret-scan findings remain unresolved.** If Gitleaks reports potential secrets, the quality runner deliberately prints only their count; investigate privately, and treat real exposed credentials as compromised. No bypass flags are built in.

## 4. History is still a separate task

Removing files in a new commit prevents their presence in the latest tree, but **does not remove previous commits**. The current-index scanner also **does not check historical commits**. That limitation is intentional: a historical scan of the public repository may expose sensitive strings and requires a secure, private evidence-handling plan.

To conduct a historical review on a secured machine, follow Gitleaks' official `git` subcommand documentation using `--redact`, store findings outside the repository, and do not paste results into chat or public issues. Determine credential rotations and whether history rewriting is needed; coordinate force-pushes and clone resets before any `git filter-repo` operation. Even a rewrite cannot guarantee removal of forks and caches. If a secret was exposed, rotate it regardless of whether rewriting succeeds.

## 5. Definition of done

- Quick and Full profiles continue to pass.
- Security profile passes with Gitleaks installed **only after tracked index cleanup** and no current-index scanner findings.
- CI PR security job succeeds.
- GitHub `master` is checked separately after the cleanup commit is merged, and no private DB/virtualenv/patch backups appear in fresh clones.
- Historical exposure and credential rotation are addressed as separate security remediation. A passing Phase 0B security profile is **not** evidence that Git history, private data, external accounts or live provider execution are secure.
