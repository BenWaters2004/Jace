# C3A — Opt-in Auto model routing

This is the first *deterministic routing* stage, not the multi-provider verification stage. **C3A does not call multiple providers for one request, does not probe health, and does not automatically retry failed tool operations.**

## Prerequisites

Apply C1, C2A and C2B first and verify. Back up Jace's database before any live rollout. Ensure the privacy gateway's cloud egress policy is understood before enabling cloud credentials. API costs are separately billed by providers.

## Configuration (example only)

In your **untracked** `backend/.env`, using exact valid model IDs from your own API accounts:

```dotenv
JACE_CLOUD_CHAT_CUTOVER=true
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
JACE_MODEL_ROUTE_CONVERSATION_FAST=openai:<verified-fast-model>
JACE_MODEL_ROUTE_CONVERSATION_BALANCED=anthropic:<verified-balanced-model>
JACE_MODEL_ROUTE_REASONING_HIGH=openai:<verified-deep-model>
JACE_MODEL_ROUTE_CODING_HIGH=anthropic:<verified-coding-model>
JACE_MODEL_ROUTE_RESEARCH_HIGH=anthropic:<verified-research-model>
JACE_SMART_ROUTING_ENABLED=true
```

Set provider credentials using the documented `JACE_OPENAI_API_KEY` and `JACE_ANTHROPIC_API_KEY` variables (never commit them). The fallback route `conversation.fast` must be a valid **cloud provider:model** route while C2A cloud cutover is enabled. A tier with an empty route inherits the *configured* fast route. Invalid configured routes fail closed rather than guessing.

## UI

After backend restart and desktop refresh, `GET /models` includes `auto` (displayed as **Auto (Jace)**) when cloud chat cutover, smart routing and at least one configured usable cloud route are enabled. Existing explicitly selected models remain manual. Auto is saved as a conversation choice; the actual route is chosen per new turn. The assistant message records the resolved provider:model route.

## Decision order

1. User chooses Deep → `reasoning.high`.
2. Explicit research/source-validation task → `research.high`.
3. Explicit coding/debug/refactor task → `coding.high`.
4. User chooses Balanced or request is long/multi-step → `conversation.balanced`.
5. Otherwise → `conversation.fast`.

These are **heuristics**, not guarantees about reasoning quality. Research tier selection never substitutes for retrieval, citation checking or evidence provenance. All inference is still filtered through the existing Privacy Gateway and permissioned tool loop.

## Manual tests

- Confirm `/models` contains Auto and configured provider-qualified model choices after restart.
- Select Auto; ask `Hello` (fast), ask for a detailed architecture plan (balanced), ask to debug a script (coding), and ask for external sources (research).
- Switch reasoning to Deep and verify it uses the deep route.
- Switch to a specific model; confirm the router doesn't override the explicit selection.
- Turn off JACE_SMART_ROUTING_ENABLED; confirm Auto disappears from `/models` on restart.
- Turn cloud egress off; confirm privacy blocks or local-reroutes protected content rather than leaking it.
- Confirm cloud responses still require tool execution evidence before claiming calendar/filesystem actions completed.

## Limitations / next phase

**C3B:** provider credential/health checks, circuit breakers, cost estimates/budgets, bounded pre-first-token fallback, request-scoped privacy controls and provenance. **C4:** independent research and review, citations/evidence, multiple providers, disagreement reporting, durable workflows. C3A does not verify billing availability and does not touch VPS services or existing memory vectors.
