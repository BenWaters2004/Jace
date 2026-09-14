# Jace Connections & Capabilities Contract

Step 4A defines the boundary between authentication, provider access, Jace policy,
tool execution and audit.

## Connection

A connection answers: which account or service can Jace authenticate to?
Secrets and OAuth token bundles remain in the OS credential store. SQLite stores
non-secret connection metadata only.

## Capability

Capabilities are provider-neutral intents such as `email.search`, `email.send`,
`calendar.read`, `files.read`, and `repositories.read`.

An external capability is `ready` only when the connection is active, runtime
external access and the provider switch are enabled, provider scopes are present,
Jace permission allows it, an executable tool is bound, and the backend master tool
switch is enabled.

## Runtime resolution

The model asks for a generic capability. Jace resolves provider/account, scope,
permission and tool binding. The model never chooses a connection ID. If equally
suitable accounts exist and the user did not identify one, Jace must not silently
guess.

## Permission contract

Provider authorization and Jace permission are separate. External persistent
approval decisions are scoped to the exact connection + capability. A global tool
`deny` remains an emergency kill switch.

## External access switches

Step 4A.6 adds a master external-services switch plus Google, Microsoft, GitHub and
Custom API switches. Disabling them never deletes credentials; it only makes the
matching capabilities unavailable.

## Audit contract

External audit events may store provider ID, connection ID, account hint,
capability ID, tool name, redacted arguments, policy mode, approval ID, status,
result/error and timestamps. They must never contain access/refresh tokens, API
keys, client secrets, passwords or Authorization header values.

## 4B contract

Full Computer Integration should reuse this architecture: filesystem, terminal,
apps and processes become capabilities; permission decisions remain explicit;
dangerous actions fail closed; every action remains auditable.
