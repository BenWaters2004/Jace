# C4B.1 — Evidence-linked collaboration (supplied excerpts)

**Status:** Optional implementation. **NOT** web research, filesystem retrieval, verified citations, Agent Director integration, or automatic fact-checking.

This phase extends the existing C4A editorial workflow with a separate authenticated endpoint that passes user-supplied excerpts to two different cloud providers. The first drafts a claim-by-claim analysis, the second assesses each claim against the same supplied excerpts, and a deterministic validator checks cited quotes against the text actually presented to the models. The first provider revises its response after seeing the audit.

**Trust boundary:** the supplied excerpts may be inaccurate, fabricated, outdated, or prompt-injected. The SHA-256 receipts identify the *supplied bytes only*. An anchored quote merely demonstrates that the quoted text occurs in the supplied excerpt. No source URL was fetched or independently authenticated; model agreement is not proof. The API always reports `verification_status=supplied_excerpts_only`, zero independently verified claims, zero independently retrieved sources, and zero executed tools.

## API

- `GET /collaboration/status`: now includes `supplied_excerpt_review_enabled`.
- `POST /collaboration/evidence-review`: requires Jace authentication (`require_actor`), plus both feature flags.
- The existing `POST /collaboration/review` remains unchanged and available if C4A is enabled.

Example request (fill with information you are authorised to send to both providers):

```json
{
  "objective": "Explain what the supplied design excerpt establishes about the device transport.",
  "evidence": [
    {
      "id": "design1",
      "label": "Document excerpt copied by the user",
      "content": "The device establishes an outbound authenticated WebSocket connection to the Core. Reconnection is automatic after network interruptions."
    }
  ]
}
```

The result contains `initial_answer`, `final_answer`, the independent review's overall assessment, and `claim_audit`, each with source ID, exact quote match result, model reviewer verdict and bounded audit status. Claim status `reviewer_supported_on_supplied_text` is deliberately **not** `verified`.

Limits: objective 8,000 characters, up to 8 excerpts, up to 5,000 characters per excerpt and 20,000 characters total, at most 8 claims. No tools, browser, device access, filesystem reads, writes, conversation persistence or background execution.

## Activation on an isolated test backend

Before enabling, complete live C1-C3 model integration and check credentials and billing, and back up the Jace database. Do not paste secrets or personal/customer records for this test. Set in `backend/.env`:

```dotenv
JACE_COLLABORATION_ENABLED=true
JACE_COLLABORATION_EVIDENCE_ENABLED=true
JACE_COLLABORATION_DRAFTER_ROUTE=openai:<real-API-model-ID>
JACE_COLLABORATION_REVIEWER_ROUTE=anthropic:<real-API-model-ID>
JACE_PRIVACY_ENABLED=true
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
```

Use real model IDs available through your own API subscriptions. Provider calls and quoted excerpts may incur costs. Privacy checks run before the first model call and again inside the Model Gateway for each call. A `local_only` classification blocks the collaboration endpoint entirely; it must **never** silently reroute to an uncontrolled provider.

Test with an authenticated request and benign fabricated example excerpts. Confirm the response contains `independently_verified_claims=0` and that a deliberately incorrect quote produces a `not_anchored` claim. Verify credentials are never logged or echoed in HTTP errors.

## Next phases

**C4B.2**: approved source retrieval using existing web or Device Agent tools, receipts with the actual source type, retrieval time, URL/device path, content hash and scope/permission outcome; implement SSRF restrictions and source prompt-injection isolation. **C4C**: durable workflow records, idempotent handoff and source-verified Director plans, with cancellation and cross-provider review. **C4D**: integrate with desktop chat, research UI, and evidence inspector once storage, tools and receipts are production-tested.

## Limitations and recovery

Evidence review is opt-in and not part of chat or Director flows. Runtime output is returned synchronously and lost if the caller disconnects. There is no automatic web retrieval, no claims-to-trusted-source validation and no production API verification yet. If installation fails, use the ZIP's rollback procedure; the installer deliberately does not alter the database or running VPS.
