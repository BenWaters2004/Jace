# Jace

**A self-hosted, provider-independent personal AI operating environment.**

> **Project status (16 October 2026):** active development. The repository already contains a Windows/Tauri desktop client, FastAPI backend, local model gateway, privacy gateway, agent workflows, device-agent foundations, integrations and VPS deployment tooling. **Cloud-provider integrations and multi-provider verification described below are planned work, not yet shipped.**

[Documentation](docs/README.md) · [Cloud-first master roadmap](docs/roadmap/cloud-first-master-roadmap.md) · [Implementation tracker](docs/roadmap/implementation-tracker.md) · [Security and repository hygiene](docs/operations/repository-hygiene.md)

## Vision

Jace should have one identity and one persistent memory across desktop, web, mobile and voice. It should understand projects, coordinate specialist workers, use authorised computer and service capabilities, remember evidence, and keep the owner in control of private data and high-impact actions.

**Jace owns the assistant; models only supply intelligence.** Model APIs are replaceable dependencies, not the source of truth for Jace's personality, state, permissions, history or results.

## Current architecture

| Component | Existing foundation |
| --- | --- |
| Desktop | Tauri 2, React, TypeScript, Vite; chat, settings and agent workspaces |
| Core API | Python/FastAPI; HTTP and WebSocket runtime events |
| Inference | Model Gateway with a registered Ollama provider; cloud adapters **not yet implemented** |
| Privacy | Classification and protected-cloud processing; cloud egress **disabled by default** |
| Agents | Research, Analyst, Code, Files, General; Agent Director, task/event infrastructure |
| Device capabilities | Paired Device Agent, capability broker and permission-controlled host execution groundwork |
| State | SQLAlchemy with SQLite local support and configurable PostgreSQL URL |
| Deployment | GitHub Actions VPS deployment workflow; production hardening and recovery need verification |

This describes code present in the `master` branch when the documentation was prepared, **not a claim that every feature is deployed, production-tested or enabled**. Consult the feature-specific docs for constraints.

## Planned cloud-first intelligence

1. **Fast chat:** one low-latency hosted model; stream responses directly.
2. **Balanced/deep reasoning:** select a stronger model when the problem warrants it.
3. **Collaborative workflows:** Agent Director coordinates distinct research, implementation and review steps, potentially using OpenAI, Anthropic and later providers.
4. **Independent verification:** claims use source records; code uses tests and diffs; important actions use execution receipts. Another model's agreement alone is not proof.
5. **Cost and privacy policy:** bound spending, prevent unintended cloud disclosure, and use optional local inference when required and available.

See [Cloud Intelligence Architecture](docs/architecture/cloud-intelligence.md) and [Provider Integration Contract](docs/architecture/cloud-provider-contract.md).

## Repository layout

```text
apps/desktop/      Windows desktop application and frontend
backend/jace/      Core API, agents, model gateway, privacy and tools
device-agent/      Outbound, paired device runtime and PowerShell helpers
docs/              Architecture, roadmap, operational guidance
.github/workflows/ CI/deployment workflow
```

## Running and deploying

- For desktop development, see [apps/desktop/README.md](apps/desktop/README.md).
- To pair a Windows host, see [device-agent/README.md](device-agent/README.md).
- For the VPS migration, follow the [VPS checklist](docs/operations/vps-cloud-migration.md) **after verifying the real server configuration**.
- Backend settings and environment variable names are documented by [`backend/.env.example`](backend/.env.example). Never commit a populated `.env` or API token.

This documentation-only refresh does **not** deploy services, migrate a database, enable external inference or modify runtime settings.

## Development priorities

| Order | Workstream | Deliverable |
| --- | --- | --- |
| P0 | VPS/repository hygiene | Reproducible, secured, backed-up baseline |
| C1–C3 | Model provider adapters | Real OpenAI and Anthropic chat and tool streams |
| C4–C5 | Full inference migration | No hidden Ollama dependency; provider routing and fallbacks |
| C6–C8 | Durable verification | Recoverable workflows, source-backed cross-provider review |
| C9–C10 | UX and release | Provider/activity views, costs, error handling, production tests |
| Later | Core expansion | Device control, projects, memory, coding, research, automations, voice, OSINT, plugins and guarded autonomy |

These are **targets**, not a release-completion statement. Track status in [Implementation Tracker](docs/roadmap/implementation-tracker.md).

## Security principles

- Jace Core authorises tools; a model never receives unrestricted access to a device or provider credential.
- Cloud inference must pass the Privacy Gateway, with a default-deny stance where the relevant policy requires it.
- Significant changes and claims need recorded evidence; failures must be reported accurately.
- Devices connect *outward* to Jace Core; do not expose local shells or device control ports on the public internet.
- Background work needs durable state, bounded retries and a kill switch.
- **Audit repository contents before publishing new data.** See [tracked database / virtualenv warning](docs/operations/repository-hygiene.md).

## Documentation conventions

Current implementation documents can describe historical milestones; they should not be mistaken for the latest overall product target. The authoritative **future** direction is the [v2 roadmap](docs/roadmap/cloud-first-master-roadmap.md). The [docs index](docs/README.md) distinguishes implemented foundations, proposed architecture and operational checklists.

## Status and contribution

Jace is under active development. Features described as *planned* require implementation and validation before use. When changing interfaces or permission logic, update the relevant documentation and tests alongside the code.
