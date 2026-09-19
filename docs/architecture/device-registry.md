# Phase 4B.S4 — Device Registry

Jace Core now owns first-class device records before the long-lived Device
Agent transport is added in Phase 4B.S5.

Pairing codes are short-lived, one-time, high-entropy credentials. Only their
SHA-256 hashes are stored. Successful pairing returns an opaque device token;
only that token's SHA-256 hash is stored.

Device-originated requests authenticate with:

`Authorization: Device <device-token>`

Online/offline is derived from `last_seen_at` using the configured online
window rather than storing an unreliable boolean.

User/client endpoints:
- `POST /devices/pairing`
- `GET /devices`
- `GET /devices/{device_id}`
- `PATCH /devices/{device_id}`
- `DELETE /devices/{device_id}`

Device endpoints:
- `POST /devices/pair`
- `POST /devices/heartbeat`

Runtime events:
- `device.paired`
- `device.heartbeat`
- `device.updated`
- `device.revoked`

4B.S5 adds the persistent Device Agent process/connection. 4B.S6 routes
capability execution to the correct device.
