# Repository hygiene and public-source safety

**Status:** audit required, not executed by the documentation installer. **Review date:** 16 October 2026.

## Findings from the reviewed public `master` tree

The tree contains entries under `backend/.venv/` and a tracked `data/jace.db` despite the present `.gitignore` excluding those paths. This means earlier commits or `git add -f` may have committed private/generated content; `.gitignore` does not remove already tracked files or purge their history.

**Do not publish, display, export or inspect user data in a public issue while troubleshooting this.** A tracked database may contain conversations, tokens, identifiers or none of those; its exact contents were **not** assessed in this documentation review.

## Controlled remediation (separate authorised development task)

1. Work in a dedicated branch and create a secure backup of anything needed from `data/jace.db` and local environment configuration.
2. Inspect which files are actually tracked with `git ls-files -- data/jace.db backend/.venv` and compare with the appropriate local data store. Do not remove the real database until a verified backup exists.
3. Inspect the contents locally for secrets or private data, including accidental check-in of `.env`, API keys, OAuth tokens or logs.
4. Stop tracking generated assets (e.g., using `git rm --cached` on the verified tracked paths), then commit the index cleanup without deleting needed working data.
5. If sensitive data was ever published, rotate compromised credentials and assess whether Git history removal/host-side remediation is necessary. Removing files in a new commit is **not** equivalent to erasing old commits.
6. Ensure CI/deployment excludes `.venv`, `data`, caches and secrets. The current VPS bundle script excludes common generated paths, but the Git repository itself still needs hygiene.
7. Add automated secret scanning and dependency security checks, with approvals for legitimate exceptions.
8. Verify fresh clones contain no private DB or virtual environment artifacts before deploying cloud-provider changes.

## Safe inspection commands (read-only)

From the repository root:

```powershell
git status --short
git ls-files -- data/jace.db backend/.venv
git log --oneline -5
```

Do **not** execute a history rewrite or destructive cleanup as part of a documentation update. Coordinate any history rewrite with users of the repository; it can invalidate existing clones and cached references.

## Cloud credentials

Store provider credentials only on Jace Core through an appropriate secret boundary. Do not place them in desktop React variables, public documentation, `.env.example` with real values, model prompts, runtime event payloads or error reports. Test privacy policies before enabling any cloud egress.

## Keeping documentation accurate

The [implementation tracker](../roadmap/implementation-tracker.md) is a snapshot and needs updates with commit/test evidence. Do not treat instructions in a historical phase document as proof the current VPS runs that service.
