# C4D.2 — Persisted Collaboration Inspector

C4D.2 exposes read-only, authenticated, owner-scoped details of **one** already-persisted Agent Director workflow.

- Endpoint: `GET /collaboration/workflows/{workflow_id}/inspection`.
- `require_actor` resolves the authenticated identity from request state. In server mode the endpoint requires an **existing** `resource_ownership` entry for the workflow's conversation; no server-side auto-claim. In local single-user mode that conversation must still exist.
- Checkpoint stage and synthesis model are from a workflow checkpoint. Review aggregate counts and status are from the handoff receipt (or checkpoint when no receipt exists). No model or tool actions occur.
- The source list uses successful `tool_completed` records for `read_workspace_file` / `read_web_page` with recorded checksum provenance. No text, URLs, file paths, tool arguments, or raw review responses are returned. Each record is an **available source-tool observation**, not proof it was included in any review.
- Legacy workflows without a saved checkpoint or receipt return 404. Server-side conversations without established ownership also return 404. No automatic data migration/backfill.
- Earlier phases **did not persist detailed per-claim reviewer verdicts or exact reviewed-source IDs**. The UI therefore only displays aggregate counts and review status when recorded; it never invents missing detail.
- Performance bounds: latest 500 tasks for the conversation, latest 500 matching source events, at most 12 unique source observations, at most 30 specialist summaries. Older records may be omitted. SHA-256 does not prove publisher authenticity.

## Operations

Install C4C.3C backend and C4D.1 Fix1 desktop first. Stop Core before patching. After verification, restart Core (register new route) and restart/rebuild the desktop client. The VPS GitHub workflow validates desktop builds but does not install a Windows desktop binary.

Read-only endpoint has no feature flag because it performs no external actions; server-mode access control is mandatory.

## Remaining work

C4D.3 could persist full structured reviewer verdicts with consent-aware retention/erasure and display per-claim attribution. C4D.2 does not retrofit historical detail.
