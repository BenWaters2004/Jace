# Jace documentation

**Documentation baseline:** 16 October 2026. The repository is being migrated toward a VPS-hosted, cloud-first orchestration system. This index separates **present implementation**, **proposed architecture** and **operational runbooks**, so historical phase documents remain useful without being confused for deployment status.

## Read these first

| Document | Purpose | Status |
| --- | --- | --- |
| [Root README](../README.md) | Overview, present foundations, next development steps | Current documentation |
| [Cloud-first master roadmap v2](roadmap/cloud-first-master-roadmap.md) | Complete architecture and all future phases | **Proposal / target** |
| [Implementation tracker](roadmap/implementation-tracker.md) | What is present, what must be implemented, release gates | **Baseline assessment**, not live status |
| [Cloud intelligence architecture](architecture/cloud-intelligence.md) | Fast routing, multi-model workflows and Jace-owned orchestration | **Proposed** |
| [Cloud provider contract](architecture/cloud-provider-contract.md) | OpenAI/Anthropic adapters, streaming/tool/events/error semantics | **Proposed** |
| [Verification and evidence](architecture/verification-and-evidence.md) | Independent reviewers, real source/command evidence and receipts | **Proposed** |
| [VPS cloud migration](operations/vps-cloud-migration.md) | Security, operations, migration and release gates | Checklist, **not executed** |
| [Repository hygiene](operations/repository-hygiene.md) | Tracked data, dependencies and secret/history audit | Immediate review needed |

## Existing architecture and implementation documents

These documents describe **incremental implementation milestones** and existing contracts. Where their phase-specific language says "future provider", it describes the state of that milestone and does not override the cloud-first roadmap.

- [Distributed Jace foundation](architecture/distributed-jace-foundation.md) — server/device/client boundaries and shared events.
- [Model Gateway (Ollama baseline)](architecture/model-gateway.md) — current provider abstraction and capability classes.
- [Privacy Gateway](architecture/privacy-gateway.md) — policy, classification and the present transformation limits.
- [Authentication foundation](architecture/authentication-foundation.md) — server-mode sessions and limitations.
- [Device registry](architecture/device-registry.md), [Device Agent](architecture/device-agent.md), [Capability Broker](architecture/device-capability-broker.md) — authorised remote execution foundations.
- [Durable runtime events](architecture/durable-runtime-events.md) — event IDs/replay and transport requirements.
- [Persistent process runtime](architecture/persistent-process-runtime.md), [Interactive terminal runtime](architecture/interactive-terminal-runtime.md), [Scoped execution policy](architecture/scoped-execution-policy.md), [Trusted host execution](architecture/trusted-host-execution.md) — permissions, execution and limitations.
- [Connection capabilities](architecture/connections-capabilities.md), [Unified calendar](architecture/unified-calendar.md) — integration contracts.

For exact endpoints, flags and behaviour, **the currently checked-out source is definitive**. Existing docs may represent a narrower historical phase than the newest code.

## How to maintain these docs

1. When a feature ships, mark its acceptance checks complete in the tracker with a source commit/test reference. Do not flip a planned feature to implemented because code was merely written.
2. Put product objectives and phase dependency changes in the master roadmap.
3. Put interface contracts in `docs/architecture/` and operational procedures in `docs/operations/`.
4. Record whether a statement describes **implemented**, **verified in deployment**, or **planned** behaviour.
5. Keep secrets, private database contents, account identifiers and server credentials out of public documentation.
6. When commands change, verify they match the actual repository scripts and working directory.

**Historical source:** the September 2026 original master roadmap informed the revised plan. It is not included verbatim in this public-repo patch because it was supplied as a private project attachment; keep the original separately if an archive is needed.
