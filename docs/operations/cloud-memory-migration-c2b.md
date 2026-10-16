# C2B — Cloud Memory Extraction and Provider-Safe Embeddings

**Status:** staged upgrade, not deployed automatically. This package does not call any provider or modify database rows during installation.

## Scope

- Jace can use an explicitly configured **cloud structured-generation route** for `memory.extract` (OpenAI or Anthropic).
- Jace can use an explicitly configured **OpenAI embeddings route** for `embedding`. The Anthropic adapter in C1 does *not* provide embeddings.
- New embeddings retain the **effective provider-qualified route** after privacy processing, not merely the requested route, so a fallback to local inference cannot be mistaken for a cloud vector.
- A conservative hybrid retrieval mode can combine compatible vectors with lexical matches of memories stored by a different model. Unrelated vectors are **never** compared.
- A lexical-only mode can read, create, and edit memories without running any embedding model. The vector column is populated with `[]`, identified by `embedding_model="lexical"` because the current database schema does not permit NULL. The text and metadata remain intact.
- Existing conversation history and previous memory rows are preserved. No automatic re-embedding, vector overwrites, or database migration occurs.

## Settings for a *controlled* local / staging test

Set these in **untracked** `backend/.env`, not in Git or the ZIP:

```dotenv
# Only after reviewing Jace privacy rules, data permissions, API costs and credentials.
JACE_PRIVACY_CLOUD_EGRESS_ENABLED=true
JACE_CLOUD_CHAT_CUTOVER=true
JACE_MODEL_ROUTE_CONVERSATION_FAST=openai:<actual-model-id>

# Structured extraction: use a supported, accessible text/chat model.
JACE_MODEL_ROUTE_MEMORY_EXTRACT=anthropic:<actual-model-id>

# OpenAI is the only native embeddings adapter currently included.
JACE_MODEL_ROUTE_EMBEDDING=openai:text-embedding-3-small

# Recommended while legacy Qwen vectors remain.
JACE_MEMORY_RETRIEVAL_MODE=hybrid
JACE_MEMORY_LEXICAL_MIN_SIMILARITY=0.60
```

Configure `JACE_OPENAI_API_KEY` / `JACE_ANTHROPIC_API_KEY` only for providers you actually use and verify model IDs and billing limits with each API account. Jace's privacy policy can still force local-only for secret content. If no permitted local route exists, inference must fail closed or (only in `hybrid` memory mode) degrade to lexical matching. Jace must never silently send secret input remotely.

### Memory modes

| Mode | Vector requests | Legacy vectors | New/edited memories | Behaviour when embedding API fails |
|---|---|---|---|---|
| `semantic` (default) | Yes | Only compared if the actual embedding model matches | Store effective route/vector | Error propagates; original behaviour preserved |
| `hybrid` | Yes | Lexical search on incompatible legacy vectors | Store actual route/vector, or lexical sentinel if inference fails | Falls back to local lexical ranking with a warning |
| `lexical` | **None** | All memories eligible by lexical ranking | Store lexical sentinel and text | No embedding provider involved |

Lexical relevance is an approximate term match; it is **not** cosine similarity, and will not find every relevant memory. The API's legacy `similarity` field remains numerical for compatibility. Generated memory context explicitly labels lexical relevance.

### Important limitation

Hybrid memory mode does not *convert* old Ollama vectors into cloud vectors. Existing `embedding_model` labels such as `qwen3-embedding:0.6b` remain untouched. Re-embedding should be done as a **separately approved**, checkpointed project with a tested database restore, a batch limit, and complete vector provenance. This upgrade deliberately does not do that.

### Initial tests

1. Install C1 and C2A and verify. Take a real backup of the Jace data directory before a provider cutover.
2. Apply C2B to local staging and run offline tests. Cloud egress remains off until explicitly enabled.
3. Configure `hybrid` with a verified OpenAI embedding model; start the backend **without Ollama**.
4. Search for a known existing project memory. Confirm lexical source is shown for legacy records; do not accept a false high-confidence similarity.
5. Create a test memory and verify its `embedding_model` is exactly `openai:<embedding-model>` after permitted cloud inference. The key is never persisted to the database.
6. Create an intentionally locally restricted memory: verify it cannot be sent to a cloud model. If permitted local embedding is unavailable, only `hybrid` mode may record a lexical-only fallback.
7. Test explicit remember/forget and background memory extraction under a cloud structured route.
8. Re-test normal fast chat, read-only tools, and the agent Director. Confirm no loss of conversations/memories and no unexpected cloud sends.
9. Test a bad API key or intentional provider outage: `hybrid` continues memory retrieval lexically, and warning records expose the reduced quality.
10. Use `GET /model-gateway/status` to check route resolution. It does not assert provider real-time availability.

## Operational warnings

- The current C1 providers use direct HTTP and their structured-output implementations require compatible models. Check live support before production use.
- Privacy transformations, logs, external retention and data-permission reviews remain required before sending email/source documents or personal context off-host.
- Back up and audit the tracked SQLite database and virtual environment files in the *public* Git repository before adding provider keys or pushing deployments. Removing them from the index alone does not remove Git history exposure.
- Automatic email/calendar action approval, OS-level device isolation, and VPS authentication are separate security boundaries.
- Run each first cloud test against a **non-production database** with synthetic records, never against private candidate or customer records.

## Next

C3 will introduce health-aware model routing and explicit budgets, then C4 will add independent cross-provider review and evidence contracts. Before that, the final full cloud-only cutover must include model-agnostic health/voice/vision status and a VPS backup/restore drill.
