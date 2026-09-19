# Phase 4B.S6 — Device Capability Broker

Jace already has a general capability registry for local tools and external
connections. 4B.S6 extends that existing system rather than replacing it.

New routes:
- `GET /capabilities/device/catalog`
- `POST /capabilities/device/execute`
- `GET /capabilities/device/requests/{request_id}`
- `POST /capabilities/device/requests/{request_id}/cancel`

The initial execution allowlist is:
- `system.info`
- `process.list`
- `filesystem.list`

All are read-only. Shell execution, file contents/writes, process termination,
and GUI control remain disabled.

Each request is durable in `device_capability_requests` and records request,
device, user/context IDs, parameters, timeout, idempotency key, status, result,
evidence and errors.

The Device Agent returns evidence containing hostname, agent version, start/end
times, duration and a read-only marker.
