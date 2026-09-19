# Phase 4B.S3 — Authentication Foundation

## Objective

Provide the identity/session boundary required before Jace Core can safely run
on a VPS and serve desktop, web and mobile clients.

## Local mode

Authentication is bypassed. Existing local desktop development continues
without a login screen.

## Server mode

Authentication is required for Jace Core routes except the public health and
authentication bootstrap/login/refresh routes.

The first account is created through `/auth/bootstrap` and requires the
server-side `JACE_AUTH_BOOTSTRAP_TOKEN`.

## Passwords

Passwords are hashed with Argon2id using `argon2-cffi`. Plaintext passwords are
never stored.

## Sessions

Jace uses revocable opaque sessions:

- short-lived access token;
- rotating refresh token;
- client ID;
- optional client name;
- expiry timestamps;
- explicit revocation.

Only SHA-256 hashes of the tokens are stored in the database.

## Desktop client

The shared request layer gains Bearer authentication, `X-Jace-Client-ID`,
automatic token refresh, and authentication API helpers.

Tokens remain memory-only in this foundation phase. Persistent credentials will
later be placed behind a secure operating-system credential/keychain boundary.

## Deliberate limitation

Resources currently rendered as unauthenticated plain URLs are not made public
as an authentication workaround. Remote clients will later move those to
authenticated blob or signed-resource flows.

## Production note

This phase is a prerequisite for VPS deployment. It is not, by itself, a
complete public-internet deployment hardening step. TLS/reverse proxy, rate
limiting, secure secrets and production monitoring remain separate work.
