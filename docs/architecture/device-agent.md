# Phase 4B.S5 — Device Agent

## Purpose

Jace Core may run on a VPS while an authorised computer exposes local
capabilities through a trusted outbound Device Agent.

The Device Agent is a separate application from both Jace Core and the desktop
UI.

## Trust flow

1. User creates a short-lived pairing code through Jace Core.
2. Device Agent exchanges the code for a device identity/token.
3. The device token is stored in the operating-system credential store.
4. The agent opens an outbound WebSocket to `/devices/connect`.
5. Jace Core authenticates the device credential before accepting the session.
6. The agent sends identity/capability information and regular heartbeats.
7. Jace Core tracks the currently connected WebSocket in an ephemeral
   `DeviceConnectionManager`.

Persistent identity remains in the database; connection presence remains
ephemeral.

## Transport security

Loopback HTTP/WS is allowed for local development.

Remote Device Agent connections should use HTTPS/WSS. The agent refuses
non-TLS remote URLs unless the explicit development override is enabled.

## Capability advertisement

The Device Agent detects potential host capabilities such as:

- filesystem
- processes
- applications
- PowerShell
- CMD
- WSL
- screen access
- local Ollama

Phase 4B.S5 only advertises these. It does not execute them remotely.

## 4B.S6 integration

`DeviceConnectionManager.send(device_id, message)` is the transport primitive
the next phase will use for capability requests.

The agent already understands `capability.request` messages but returns
`unsupported` until 4B.S6 installs the guarded capability executor.
