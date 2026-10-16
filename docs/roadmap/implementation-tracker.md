# Implementation tracker — cloud-first migration

**Baseline:** 16 October 2026, source-code review of `master` (no live VPS validation). **Status legend:** *Present foundation* = source exists, but not independently certified in production; *Planned* = not implemented in the reviewed baseline; *Needs verification* = behaviour requires live tests.

This tracker is deliberately conservative. A roadmap milestone is not "done" merely because a Python class or UI panel exists. Add tests and commit references when advancing a status.

| Workstream | Baseline status | Concrete evidence / remaining work |
| --- | --- | --- |
| Desktop Tauri/React client | Present foundation | `apps/desktop/`; native build and VPS connection need deployment testing |
| FastAPI Core / API routes | Present foundation | `backend/jace/api/` |
| Model Gateway | Present foundation | `backend/jace/model_gateway/`; only Ollama adapter registered by default |
| Privacy Gateway | Present foundation | `backend/jace/privacy/`; limited transformation, cloud egress disabled by default |
| Authentication | Present foundation | `backend/jace/api/auth.py`; check real VPS TLS/session security |
| Agent Director and worker tasks | Present foundation | `backend/jace/agents/`; some Director inference paths use Ollama engine |
| Device Agent / host runtime | Present foundation | `device-agent/`, process/terminal/permissions code; require local policy testing |
| VPS deployment workflow | Present foundation | `.github/workflows/deploy-vps.yml`; live reliability/rollback unverified |
| PostgreSQL migration lifecycle | Needs verification | SQLAlchemy DB URL support exists; production migrations/restore test needed |
| **P0: repo and VPS hygiene** | **Planned work** | Tracked `data/jace.db` and `backend/.venv` audit; secure baseline |
| **C1: provider interface refinement** | **Planned** | Canonical provider-agnostic streaming/tool/event/error contract |
| **C2: OpenAI provider** | **Planned** | Native official API adapter and integration tests |
| **C3: Anthropic provider** | **Planned** | Native official API adapter and integration tests |
| **C4: all-inference migration** | **Planned** | Director, memory, embeddings, image and health paths decoupled from Ollama |
| **C5: automatic model routing** | **Planned** | Capability/privacy/health/cost policies, fallback and budgets |
| **C6: durable workflow upgrades** | **Planned** | Recoverable step graphs, checkpoints and delivered-once handoffs |
| **C7: multi-model collaboration** | **Planned** | Independent reviewer selection and agent-role orchestration |
| **C8: evidence engine** | **Planned** | Source/claim links and deterministic action receipts |
| **C9: transparency UI** | **Planned** | Provider/model/task stage, cost and verification surface |
| **C10: hardening and release** | **Planned** | Failure injection, security gates, backups and production smoke tests |

## Release order

**M1 — Reliable cloud conversation:** P0 + C1–C3; cloud chat streams without Ollama.  
**M2 — No hidden local inference dependency:** C4–C5; background tasks, memory and embeddings work through explicit capability routes.  
**M3 — Proof of work:** C6 and the core of C8; durable handoffs, audit and receipts.  
**M4 — Multi-model intelligence:** C7 and full C8; verified research and cross-provider reviews.  
**M5 — Robust multi-device:** C9–C10 plus relevant 4B host work.  
**M6–M8 — Wider original programme:** projects/memory, automation, integrations, voice, OSINT, plugins, packaging, mobile/web and finally guarded autonomy.

## Updating this table

A completed milestone needs a commit ID, meaningful automated tests and a deployment result. If live acceptance was not performed, say **implemented but not deployed/verified**. Keep future goals in the [master roadmap](cloud-first-master-roadmap.md) and contracts in [cloud architecture contracts](../architecture/cloud-intelligence.md).
