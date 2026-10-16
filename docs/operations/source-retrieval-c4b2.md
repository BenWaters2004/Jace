# C4B.2 — Permission-Gated Source Collection and Cross-Provider Review

**Status:** implemented behind explicit opt-in; live VPS/provider integration remains to be tested.

C4B.2 extends C4B.1. Jace can collect a maximum of four **explicitly identified** public webpages or approved local workspace text files, then run the existing three-model-call draft/review/revise workflow. It does **not** search the web autonomously, execute shell commands, change files, or integrate the resulting answer into normal Jace chat/Agent Director.

## Protected endpoint

`POST /collaboration/retrieve-review` (authenticated actor required).

```json
{
  "objective": "Describe how this service establishes device connections and identify documentation gaps",
  "sources": [
    {"id": "web1", "kind": "public_web", "url": "https://example.org/docs/architecture"},
    {"id": "code1", "kind": "workspace_file", "workspace_id": "<existing approved workspace UUID>", "path": "docs/architecture.md", "start_line": 1, "max_lines": 120}
  ]
}
```

A successful response returns the C4B.1 `claim_audit` and answer, plus:

- `stage: C4B.2`
- `sources[]` with `source_id`, source label, excerpt SHA-256, provenance, retrieval tool, retrieved-at timestamp, locator and truncation information;
- full-file SHA-256 when supplied by `read_workspace_file`;
- `verification_status: retrieved_excerpts_reviewed`;
- `independently_retrieved_sources` and `tools_executed` counting source reads;
- `independently_verified_claims: 0`, because excerpt agreement and quote anchoring do not independently verify the truth of a source.

The source hash is of the **captured excerpt**, not necessarily the whole page/file. A workspace receipt additionally includes the tool's full-file SHA-256. Web extraction may omit embedded tables, scripts, multimedia or dynamically rendered content. A time of retrieval does not prove the page's publication or modification date. Web receipt locators omit query parameters, so they may not reproduce query-dependent pages; the captured excerpt hash remains the integrity reference.

## Opt-in settings

In `backend/.env`, after configuring cloud-provider credentials, model routes and privacy controls:

```dotenv
JACE_COLLABORATION_ENABLED=true
JACE_COLLABORATION_EVIDENCE_ENABLED=true
JACE_COLLABORATION_RETRIEVAL_ENABLED=true
JACE_COLLABORATION_RETRIEVAL_TIMEOUT_SECONDS=150
```

The existing `JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true` still requires explicit consent to send eligible transformed content to external providers. Jace refuses protected-cloud collaboration when privacy is off, cloud egress is disallowed, the source is classified `local_only`, or the drafter and reviewer do not use different providers. Never place credentials in your request or URLs.

**Important:** `read_web_page` and `read_workspace_file` normally have permission **Ask**. C4B.2 respects that. It does not display or satisfy an interactive approval modal. To run, the user must separately set the needed tool permission to **Allow** through the existing Jace tool-permission settings, with the privacy implications understood. Otherwise the entire request stops **before any source tool is executed**. A write-capable tool or unlisted read tool cannot be substituted.

For workspace files, the workspace must already exist, be readable, belong to the authenticated actor in server mode, and pass Jace's file/path security controls. This endpoint does not delegate to a distant Device Agent. The current `read_workspace_file` tool accesses only Core-local approved workspaces; remote device files require a separate authorised transport milestone.

## Security and evidence integrity

1. All requested source IDs must be unique; at most four sources may be read. Each excerpt is bounded to 4,800 characters.
2. Public URLs must pass the existing Jace web fetcher's hostname, redirect and network protections; localhost, private IPs and nonstandard ports are rejected. Further DNS rebinding/SSRF hardening is recommended before unrestricted public VPS exposure.
3. Only registered `read_web_page` and `read_workspace_file` implementations are invoked. They must remain risk=`read`, be permission=`allow`, and satisfy any stricter tool policy.
4. Each permitted source read produces a Jace tool audit record. URL query strings and workspace-relative paths are **hashed**, not stored directly in the audit arguments; no raw page text is recorded in the audit preview.
5. The collector never accepts model-selected tools or further URLs discovered in page content.
6. All retrieved snippets are marked **untrusted source data** in the model prompt. Prompt injection within a page/file cannot override tool permissions or grant additional retrieval.
7. Retrieved content is passed through C4B.1 privacy policy before every external model call. If local-only classification is required, no model review is performed.
8. Source claims are checked against the actual captured excerpt using deterministic quote anchors; only the other provider's critique of that excerpt is considered. Agreement is not proof. The runtime does not assert truth or independently fetch a second corroborating source.
9. A failed read, schema mismatch, failed policy check, timeout or provider error returns no success result. Partial tool reads may have occurred and will remain in the audit, but no partially reviewed answer is returned.
10. No new SQL schema, background worker, credentials or auto-enablement is added.

## Test plan

- Install the package on top of an unchanged C4B.1 installation using `-DryRun`, apply and `-Verify`.
- Check `GET /collaboration/status` returns `retrieved_source_review_enabled` (false by default).
- With retrieval off, POST should fail without source access.
- With tools configured to Ask, POST should fail without source access.
- Test one public page, then one approved Core-local workspace file, with tools explicitly allowed and provider credentials configured in a staging environment.
- Verify source provenance, hashes, timestamp and quote anchors, then provoke an invalid URL and a source containing an example secret to confirm refusal.
- Compare actual retrieved text with the quoted claims; check that the revision does not claim a source is externally verified.
- Only after these live checks should C4B.2 be deployed to the VPS.

## Deferred to C4B.3 / C4C

Automatic web search and source discovery with a bounded budget; remote Device Agent source reads with per-device scope and approvals; independently retrieving corroboration; persistent claim/source graph; domain allowlists and stricter connection-pinned SSRF defence; durable workflow state, handoffs, status updates and integration with existing Agent Director/Pixel Office.
