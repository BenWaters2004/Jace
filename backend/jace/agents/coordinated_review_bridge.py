"""C4C.2: review evidence ALREADY collected by authorised Director workers.

No tools are called here. Successful, persisted tool-completion records are the
only allowed source of excerpts. These receipts establish what Jace captured,
not whether any claim or external source is factually correct.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from jace.collaboration.evidence import EvidenceReviewRequest, SourceReceipt, SuppliedExcerpt, run_evidence_review
from jace.config import settings
from jace.model_gateway import model_gateway
from jace.privacy import privacy_gateway

logger = logging.getLogger("uvicorn.error")
MAX_SOURCES = 4
MAX_EXCERPT_CHARS = 4000


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_valid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _label(value: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:120]


def collected_sources(step_records: Iterable[tuple[str, list[dict[str, Any]]]]) -> tuple[list[SuppliedExcerpt], list[SourceReceipt]]:
    """Select diverse, completed read results with backend-recorded provenance.

    Web search snippets and model-generated citations are deliberately excluded;
    only successful public-page fetches and approved workspace file reads count.
    """
    buckets: dict[str, list[tuple[str, str, str, str | None, str | None, bool, str | None]]] = {
        "workspace": [], "web": [],
    }
    seen: set[str] = set()
    for _step_id, records in step_records:
        for record in records:
            if not isinstance(record, dict) or record.get("success") is not True:
                continue
            tool_name = record.get("tool_name")
            if tool_name not in {"read_workspace_file", "read_web_page"}:
                continue
            relevance = record.get("source_relevance")
            if isinstance(relevance, dict) and relevance.get("relevant") is False:
                continue
            data = record.get("evidence")
            if not isinstance(data, dict):
                continue
            text = data.get("text")
            if not isinstance(text, str) or len(text.strip()) < 20:
                continue
            # Do not accept loose previews, mock document READ markers, or
            # ill-formed records masquerading as successful tool results.
            if tool_name == "read_workspace_file":
                path = data.get("path")
                workspace = data.get("workspace")
                full_sha = str(data.get("sha256") or "")
                if not isinstance(path, str) or not path.strip() or not isinstance(workspace, str) or not workspace.strip():
                    continue
                if not _sha256_valid(full_sha):
                    continue
                category = "workspace"
                marker = f"workspace:{workspace}/{path}".replace("\\", "/").casefold()
                label = _label(f"{workspace}:{path}")
                final_sha = full_sha.lower()
            else:
                # Runner only writes this shape after strict parsing of the
                # web tool's untrusted-content envelope and a successful fetch.
                url = data.get("url")
                title = data.get("title")
                recorded_sha = data.get("sha256")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                if not isinstance(recorded_sha, str) or not _sha256_valid(recorded_sha):
                    continue
                if _hash(text) != recorded_sha.lower():
                    continue
                category = "web"
                marker = "web:" + url.casefold()
                label = _label(str(title or url))
                final_sha = None
            if marker in seen or not label:
                continue
            excerpt = text[:MAX_EXCERPT_CHARS].strip()
            if len(excerpt) < 20:
                continue
            seen.add(marker)
            captured = data.get("captured_at") or record.get("_event_created_at")
            timestamp = captured if isinstance(captured, str) and len(captured) <= 40 else None
            buckets[category].append((marker, label, excerpt, timestamp, final_sha,
                                       bool(data.get("truncated")) or len(text) > MAX_EXCERPT_CHARS,
                                       "read_web_page" if category == "web" else "read_workspace_file"))

    # Use both source classes when available, preserving deterministic ordering.
    queue: list[tuple[str, tuple[str, str, str, str | None, str | None, bool, str | None]]] = []
    wi = we = 0
    while len(queue) < MAX_SOURCES and (wi < len(buckets["workspace"]) or we < len(buckets["web"])):
        for kind in ("workspace", "web"):
            idx = wi if kind == "workspace" else we
            if idx >= len(buckets[kind]) or len(queue) >= MAX_SOURCES:
                continue
            queue.append((kind, buckets[kind][idx]))
            if kind == "workspace":
                wi += 1
            else:
                we += 1
    excerpts: list[SuppliedExcerpt] = []
    receipts: list[SourceReceipt] = []
    for kind, (_marker, label, snippet, timestamp, full_sha, truncated, tool) in queue:
        source_id = f"J{len(excerpts) + 1}"
        excerpts.append(SuppliedExcerpt(id=source_id, label=label, content=snippet))
        receipts.append(SourceReceipt(
            source_id=source_id, label=label, sha256=_hash(snippet),
            provenance="jace_public_web_read" if kind == "web" else "jace_approved_workspace_read",
            # Do not expose URLs with query strings or file paths in metrics.
            locator=None, retrieved_at=timestamp, retrieval_tool=tool,
            full_document_sha256=full_sha, excerpt_truncated=truncated,
        ))
    return excerpts, receipts


@dataclass(frozen=True)
class CoordinatedReviewOutcome:
    text: str
    status: str
    source_count: int = 0
    workspace_sources: int = 0
    web_sources: int = 0
    model_calls: int | None = 0
    excerpt_supported_claims: int = 0
    unresolved_claims: int = 0

    def event_metadata(self) -> dict[str, Any]:
        """A metrics-only event; no source text, prompts or paths."""
        return {
            "status": self.status,
            "source_count": self.source_count,
            "workspace_source_count": self.workspace_sources,
            "web_source_count": self.web_sources,
            "model_calls": self.model_calls,
            "excerpt_supported_claims": self.excerpt_supported_claims,
            "unresolved_claims": self.unresolved_claims,
            "external_fact_verification": False,
        }


def _append(original: str, status: str, message: str) -> str:
    return (
        original + "\n\n---\n**C4C.2 coordinated source assessment**\n\n" + message
        + "\n\nThis is a separate model-generated claim review against excerpts previously "
          "captured by authorised Jace tools. It does **not** verify the Director's "
          "original conclusions, run tests, authenticate sources or establish factual "
          f"truth. Assessment status: `{status}`."
    )


async def append_coordinated_review(
    *, objective: str, original_result: str,
    records: Iterable[tuple[str, list[dict[str, Any]]]],
    gateway=None, privacy=None, config=None,
) -> CoordinatedReviewOutcome:
    cfg = settings if config is None else config
    if not bool(getattr(cfg, "director_coordinated_review_enabled", False)):
        return CoordinatedReviewOutcome(original_result, "disabled")
    if not all(bool(getattr(cfg, key, False)) for key in
               ("collaboration_enabled", "collaboration_evidence_enabled", "collaboration_retrieval_enabled")):
        return CoordinatedReviewOutcome(
            _append(original_result, "not_configured", "Coordinated source review was requested but collaboration prerequisites are disabled. No provider calls occurred."),
            "not_configured",
        )
    excerpts, receipts = collected_sources(records)
    if not excerpts:
        return CoordinatedReviewOutcome(
            _append(original_result, "no_eligible_sources", "No successful, tool-captured webpage or workspace source excerpt was available. Review was skipped."),
            "no_eligible_sources",
        )
    workspace_count = sum(1 for x in receipts if x.provenance == "jace_approved_workspace_read")
    web_count = len(receipts) - workspace_count
    try:
        review_request = EvidenceReviewRequest(objective=objective[:8000], evidence=excerpts)
        response = await run_evidence_review(
            review_request,
            retrieved_receipts=receipts,
            gateway=model_gateway if gateway is None else gateway,
            privacy=privacy_gateway if privacy is None else privacy,
            config=cfg,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("C4C.2 coordinated source assessment incomplete (%s)", type(exc).__name__)
        return CoordinatedReviewOutcome(
            _append(original_result, "incomplete", "Cross-provider source assessment did not finish. The original Director result is unchanged and no new verification was recorded."),
            "incomplete", len(receipts), workspace_count, web_count, None,
        )
    counts = Counter(x.status for x in response.claim_audit)
    supported = counts["reviewer_supported_on_supplied_text"]
    unresolved = len(response.claim_audit) - supported
    message = (
        f"Reviewed {len(response.claim_audit)} claims from a separate draft against "
        f"{len(receipts)} completed tool-source excerpts ({workspace_count} workspace, {web_count} web). "
        f"Providers: {response.drafter_route.split(':', 1)[0]} and "
        f"{response.reviewer_route.split(':', 1)[0]}.\n\n"
        f"Source-excerpt support: {supported} supported; {unresolved} unresolved, partial, disputed or unanchored. "
        "Successful retrieval is evidence of text capture only, not proof of correctness.\n\n"
        + "\n".join(f"- `{x.claim_id}`: {x.status}" for x in response.claim_audit[:6])
    )
    return CoordinatedReviewOutcome(
        text=_append(original_result, "completed_excerpt_review", message),
        status="completed_excerpt_review", source_count=len(receipts),
        workspace_sources=workspace_count, web_sources=web_count,
        model_calls=response.model_calls, excerpt_supported_claims=supported,
        unresolved_claims=unresolved,
    )
