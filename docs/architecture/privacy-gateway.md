# Phase 4B.S8 — Privacy Gateway

Privacy policy is enforced by Jace Core before model-provider egress. The LLM
does not decide whether privacy rules apply and cannot override them.

## Classifications

- `public`
- `internal`
- `confidential`
- `personal`
- `secret`

Unlabelled content defaults to `internal`. Automatic detection and caller hints
may only make handling stricter.

## Modes

- `cloud_allowed`
- `protected_cloud`
- `local_only`

Defaults:

- public → cloud allowed
- internal → protected cloud
- confidential → protected cloud
- personal → protected cloud
- secret → local only

A requested mode can only make handling stricter.

## Cloud egress

Cloud model egress is disabled by default:

`JACE_PRIVACY_CLOUD_EGRESS_ENABLED=false`

Any future non-local model route is therefore rerouted to an enabled local
provider unless the user explicitly enables cloud egress.

If a request is `local_only`, privacy overrides model routing even when the
requested model is remote.

## Protected cloud

Protected-cloud handling pseudonymises recognised email addresses and phone
numbers and redacts targeted credential/secret values before provider egress.

Aliases such as `<EMAIL_1>` are request-scoped pseudonyms. This is
pseudonymisation, not anonymisation.

Local providers receive the original payload unchanged.

Normal source-code identifiers are preserved. A name such as
`client_secret_name` is not itself treated as a secret; only targeted secret
values and credential forms are transformed.

## Secret detection

Targeted secret detection includes:

- private key material;
- Bearer tokens;
- JWTs;
- GitHub tokens;
- AWS access-key IDs;
- `sk-...` API keys;
- literal password/API-key/client-secret/access-token assignments.

Detected secret content is always `local_only`.

## Provider contract

Providers declare whether they are local and whether they support protected
cloud handling. Privacy is evaluated after model route selection and before
provider invocation. The decision may force a local route.

Model routing can never override privacy.

## API

- `GET /privacy/status`
- `POST /privacy/inspect`

The inspect endpoint returns classification metadata and a SHA-256 fingerprint,
not transformed secret-bearing content.
