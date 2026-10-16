"""C4C.1: bounded cross-provider excerpt assessment for completed Director work.

The Director owns the original workflow and final handoff. This optional stage
reuses *successful recorded read_workspace_file tool events*; it never invokes
new tools, writes files, or promotes a model opinion into verified source truth.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from jace.collaboration.evidence import EvidenceReviewRequest, SuppliedExcerpt, run_evidence_review
from jace.config import settings
from jace.model_gateway import model_gateway
from jace.privacy import privacy_gateway

logger = logging.getLogger("uvicorn.error")

MAX_SOURCES = 4
MAX_EXCERPT_CHARS = 4000


@dataclass(frozen=True)
class DirectorReviewOutcome:
    text: str
    status: str
    sources: int = 0
    model_calls: int | None = 0
    supported_excerpt_claims: int = 0
    unresolved_claims: int = 0

    def event_metadata(self) -> dict[str, Any]:
        """No source text, worker outputs, prompts, file paths or secrets in events."""
        return {
            "status": self.status,
            "source_count": self.sources,
            "model_calls": self.model_calls,
            "excerpt_supported_claims": self.supported_excerpt_claims,
            "unresolved_claims": self.unresolved_claims,
            "external_fact_verification": False,
        }


def source_excerpts(step_records: Iterable[tuple[str, list[dict[str, Any]]]]) -> list[SuppliedExcerpt]:
    """Select only completed, captured workspace reads with usable source evidence.

    Never parse model prose, forged READ markers or free-text specialist handoffs
    as evidence. A successful read event is provenance, not proof of correctness.
    """
    selected: list[SuppliedExcerpt] = []
    seen: set[str] = set()
    for _step_id, records in step_records:
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("success") is not True or record.get("tool_name") != "read_workspace_file":
                continue
            relevance = record.get("source_relevance")
            if isinstance(relevance, dict) and relevance.get("relevant") is False:
                continue
            evidence = record.get("evidence")
            if not isinstance(evidence, dict):
                continue
            path = str(evidence.get("path") or "").strip()
            workspace = str(evidence.get("workspace") or "").strip()
            source = str(evidence.get("text") or "").strip()
            if not path or not source or len(source) < 20:
                continue
            key = (workspace + "/" + path).replace("\\", "/").casefold()
            if key in seen:
                continue
            seen.add(key)
            # Workspace tool already returned line-numbered text. Preserve those
            # numbers so the review's quote anchors can be reconciled later.
            snippet = source[:MAX_EXCERPT_CHARS].strip()
            if len(snippet) < 20:
                continue
            label = re.sub(r"[\r\n\x00-\x1f]", " ", f"{workspace}:{path}")[:120].strip()
            if not label:
                continue
            selected.append(SuppliedExcerpt(id=f"D{len(selected)+1}", label=label, content=snippet))
            if len(selected) >= MAX_SOURCES:
                return selected
    return selected


def _appendix(*, status: str, detail: str) -> str:
    return (
        "\n\n---\n**C4C.1 cross-provider source assessment**\n\n"
        + detail
        + "\n\nThis assessment is of a separate model-generated draft against recorded "
          "workspace excerpts, not a verification of the Director's final "
          "answer, of full source files, or of external factual truth. "
          f"Assessment status: `{status}`."
    )


async def append_director_cross_review(
    *,
    objective: str,
    original_result: str,
    records: Iterable[tuple[str, list[dict[str, Any]]]],
    gateway=None,
    privacy=None,
    config=None,
) -> DirectorReviewOutcome:
    config = settings if config is None else config
    if not bool(getattr(config, "director_cross_review_enabled", False)):
        return DirectorReviewOutcome(text=original_result, status="disabled")

    # A misconfigured opt-in must not trigger any model calls. The original
    # synthesis remains authoritative and reaches the existing handoff path.
    if not (bool(getattr(config, "collaboration_enabled", False))
            and bool(getattr(config, "collaboration_evidence_enabled", False))):
        return DirectorReviewOutcome(
            text=original_result + _appendix(
                status="not_configured",
                detail="Cross-provider review was requested but C4A/C4B.1 collaboration is not enabled. No review occurred.",
            ), status="not_configured",
        )

    snippets = source_excerpts(records)
    if not snippets:
        return DirectorReviewOutcome(
            text=original_result + _appendix(
                status="no_eligible_sources",
                detail="No eligible, successful workspace file reads were recorded. Independent excerpt review was skipped.",
            ), status="no_eligible_sources",
        )

    request = EvidenceReviewRequest(objective=objective[:8000], evidence=snippets)
    try:
        response = await run_evidence_review(
            request,
            gateway=model_gateway if gateway is None else gateway,
            privacy=privacy_gateway if privacy is None else privacy,
            config=config,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Provider and privacy errors might contain credentials/source text.
        logger.warning("C4C.1 cross-provider assessment did not complete (%s)", type(exc).__name__)
        return DirectorReviewOutcome(
            text=original_result + _appendix(
                status="incomplete",
                detail="Cross-provider excerpt assessment did not complete. No independent verification was recorded; the original Director handoff is retained.",
            ), status="incomplete", sources=len(snippets), model_calls=None,
        )

    counts = Counter(x.status for x in response.claim_audit)
    supported = counts["reviewer_supported_on_supplied_text"]
    unresolved = len(response.claim_audit) - supported
    # Limit output to deterministic check results. Do NOT use the model's
    # separately generated final_answer to replace the Director handoff.
    parts = [
        f"Reviewed {len(response.claim_audit)} claims from a separate draft using "
        f"{len(response.sources)} tool-captured excerpt(s), with "
        f"{response.drafter_route.split(':', 1)[0]} and "
        f"{response.reviewer_route.split(':', 1)[0]}.",
        f"Source-excerpt support: {supported} supported by quoted text; {unresolved} partial, "
        "disputed, missing or not anchored.",
        "These are claim-to-excerpt checks only. They do not upgrade any existing "
        "Director claim from UNVERIFIED to VERIFIED.",
    ]
    for item in response.claim_audit[:6]:
        parts.append(f"- `{item.claim_id}`: {item.status}")
    return DirectorReviewOutcome(
        text=original_result + _appendix(status="completed_excerpt_review", detail="\n\n".join(parts)),
        status="completed_excerpt_review",
        sources=len(response.sources), model_calls=response.model_calls,
        supported_excerpt_claims=supported, unresolved_claims=unresolved,
    )
