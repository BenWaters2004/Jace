# 4B.3A — Durable Shared Runtime Events

## Problem

Jace already has a useful in-process runtime event bus, but it is intentionally
lossy and its sequence is process-local. That is appropriate for animation and
presentation, but not for reconnectable distributed clients.

## Authority

The database becomes the durable runtime-event ledger.

The in-process queue remains the low-latency delivery path.

Flow:

1. producer publishes an event;
2. Core persists the redacted event row;
3. the database assigns its durable sequence;
4. Core fans the committed event out to subscribers;
5. clients persist their last durable sequence;
6. reconnecting clients replay everything after that sequence;
7. live delivery resumes after the replay watermark.

If event persistence itself fails, the producing operation is not failed merely
because observability is unavailable. The event is marked `durable=false` and
is delivered as transient live information without advancing the durable
cursor.

## Table

`runtime_events`

Important fields:

- integer durable sequence;
- UUID event ID;
- type;
- payload JSON;
- timestamp;
- conversation/project/workflow/task/agent/device/request scope columns.

Scope columns are projections for efficient future filtering. The payload
remains the event body.

## Sensitive values

Before persistence, dictionary keys which clearly represent tokens,
credentials, passwords, secrets or API keys are redacted recursively.

This event ledger must not become a second credential store.

## Replay

Authenticated HTTP clients may use:

`GET /runtime/events/replay?after_sequence=N`

The primary live transport is:

`WS /runtime/stream`

The stream subscribes first, takes a database watermark, replays through that
watermark, then switches to queued live events while skipping duplicates.

## WebSocket authentication

Server mode no longer relies on the legacy unauthenticated runtime WebSocket.

Clients first obtain:

`POST /runtime/stream-ticket`

through the normal authenticated HTTP API. The returned token is:

- random;
- short-lived;
- held in memory only;
- single-use.

The WebSocket consumes that one-time ticket.

The legacy `/runtime/events` WebSocket remains available in local mode for
compatibility, but is rejected in authenticated server mode.

## Retention

Default durable event retention is 30 days. Pruning occurs when the durable
event bus initialises.

## Scope

This is the event substrate for later:

- persistent terminal/process sessions;
- capability execution timelines;
- approvals;
- agent workflows and handoffs;
- automation activity;
- device state;
- web/mobile reconnection.

It does not make terminal output or model token deltas durable by itself.
Those producers decide which semantic events belong in the shared ledger.
