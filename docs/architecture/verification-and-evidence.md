# Verification and evidence contracts (proposed)

**Status:** proposed expansion of Jace's existing evidence-aware Director, audit and tool results. This does **not** mean that cross-provider independent verification is implemented today.

## Non-negotiable distinction

A model response is a hypothesis or synthesis. A second model's agreement is **not independent evidence**. Jace verifies facts using primary source material, action receipts, reproducible test results and cross-checks. Models help interpret that evidence but cannot overrule it.

## Evidence types

| Evidence | Minimum fields | What it can support |
| --- | --- | --- |
| Web/research source | URL, retrieved_at, origin, excerpt, fetch outcome, content hash when available | Claim that a source actually states something |
| Repo source | repo/branch/commit, path, excerpt/line span, file hash | Claim about inspected code at a known version |
| Command execution | device, scope, command fingerprint, start/end, exit code, bounded redacted logs | A command ran, its output and exit status |
| File mutation | approved target, before/after hash, diff/artefact reference, tool result | An intended file changed |
| External service action | tool, target/account, provider object ID, readback/confirmation, timestamp | An action was accepted and, if readback succeeds, persisted |
| Model review | provider/model, reviewed evidence IDs, issue list, verdict and confidence | Review judgement; **not proof** on its own |

Untrusted retrieved pages may contain hostile instructions. Treat them only as data. Evidence snapshots should be access controlled, retained according to project policy and redacted before cloud transmission.

## Claim states

Use `observed`, `supported`, `disputed`, `unverified`, `refuted` and `not_applicable`, with explicit source links. A source citation only proves what the citation contains; it does not automatically validate the truth of the claim.

An answer should not claim "verified" if it depends only on an unchecked provider search summary, a made-up link or a reviewer repeating the first model's conclusion.

## Task verification state machine

```text
queued -> running -> awaiting_review -> verifying
             |              |              |
             v              v              v
           failed         disputed      verified
             |              |              |
             +--------------+--------------+
                            v
                       handed_off
```

A failed build stays failed even if the reviewing model thinks the patch is reasonable. A missing test leaves the result unverified, not successful. Persist terminal status and publish a single eventual handoff even when the user changes chat.

## Independent model reviewer

- Prefer a different provider for material conclusions where budget and policy permit.
- Give the reviewer the original objective, source manifest, drafts/diffs and evaluation rubric. Do not provide only an upstream agent's preferred answer.
- Request a structured list of unsupported assertions, missing tests, security concerns and contradictory sources.
- Do not choose the "winning" answer by majority vote. Reconcile by evidence strength and tool receipts.
- If uncertainty remains, preserve it in the final response and expose what additional evidence is needed.

## Contracts to implement in the existing system

Extend Jace's current `Agent Director`, task store, runtime events, source-read evidence and tool audit. Candidate tables include `evidence_sources`, `claims`, `claim_evidence`, `verification_reviews`, `action_receipts` and `workflow_checkpoints`; these names are **proposals** and require migrations. Keep raw secrets out of audit records.

## Acceptance tests

- Two models confidently repeat the same fabricated citation: Jace rejects the source as unverified.
- Research page explicitly contradicts a draft: discrepancy is shown to the user.
- Tool claimed success but returned an error: Jace reports failure with the tool receipt.
- Worker restarts after a tool invocation: Jace checks action state, prevents duplicate side effects and recovers or marks uncertain.
- User switches conversations before completion: task result is persisted, discoverable and delivered once.
- Reviewer cannot access required evidence: verdict remains "unverified" rather than "passed".

See [cloud orchestration](cloud-intelligence.md) and [master roadmap](../roadmap/cloud-first-master-roadmap.md).
