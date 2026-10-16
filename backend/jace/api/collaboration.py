"""Explicitly invoked, authenticated C4A cross-provider editorial review."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from jace.auth.actor_context import ActorContext, require_actor
from jace.collaboration.contracts import CollaborationRequest, CollaborationResponse
from jace.collaboration.retrieval import (
    RetrievalReviewRequest, run_retrieval_review, RetrievalNotAvailable, RetrievalFailed,
)
from jace.collaboration.evidence import (
    EvidenceReviewRequest, EvidenceReviewResponse, run_evidence_review,
)  # JACE_C4B_EVIDENCE_REVIEW
from jace.collaboration.review import (
    CollaborationNotReady, CollaborationOutputError, run_review,
)
from jace.config import settings
from jace.model_gateway import model_gateway
from jace.privacy import privacy_gateway

router = APIRouter(prefix="/collaboration", tags=["collaboration"])


@router.get("/status")
async def collaboration_status(actor: ActorContext = Depends(require_actor)):
    del actor
    return {
        "enabled": settings.collaboration_enabled,
        "privacy_enabled": privacy_gateway.enabled,
        "cloud_egress_enabled": privacy_gateway.cloud_egress_enabled,
        "drafter_configured": bool(settings.collaboration_drafter_route),
        "reviewer_configured": bool(settings.collaboration_reviewer_route),
        "source_verification_available": False,
        "retrieved_source_review_enabled": bool(settings.collaboration_retrieval_enabled),
        "supplied_excerpt_review_enabled": bool(settings.collaboration_evidence_enabled),
        "tools_available": False,
        "stage": "C4A: draft / independent editorial review / revision",
    }


@router.post("/review", response_model=CollaborationResponse)
async def collaboration_review(
    payload: CollaborationRequest,
    actor: ActorContext = Depends(require_actor),
):
    del actor
    try:
        return await run_review(
            payload, gateway=model_gateway, privacy=privacy_gateway, config=settings,
        )
    except CollaborationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CollaborationOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception:
        # Provider exceptions may include raw payloads, keys, or endpoint data.
        # Never reflect these to the client as an HTTP detail.
        raise HTTPException(
            status_code=502,
            detail="Cloud reviewer request failed. No result was marked verified.",
        ) from None


@router.post("/evidence-review", response_model=EvidenceReviewResponse)
async def evidence_review(
    payload: EvidenceReviewRequest,
    actor: ActorContext = Depends(require_actor),
):
    del actor
    try:
        return await run_evidence_review(
            payload, gateway=model_gateway, privacy=privacy_gateway, config=settings,
        )
    except CollaborationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CollaborationOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception:
        # Do not reflect raw provider errors: they can contain sensitive content.
        raise HTTPException(
            status_code=502, detail="Evidence review failed; nothing was independently verified.",
        ) from None


@router.post("/retrieve-review", response_model=EvidenceReviewResponse)
async def retrieve_review(
    payload: RetrievalReviewRequest,
    actor: ActorContext = Depends(require_actor),
):
    try:
        return await run_retrieval_review(
            payload, actor=actor, gateway=model_gateway,
            privacy=privacy_gateway, config=settings,
        )
    except RetrievalNotAvailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RetrievalFailed:
        raise HTTPException(
            status_code=424,
            detail="Source collection or retrieved-source review failed. No claim was verified.",
        ) from None
    except CollaborationNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CollaborationOutputError:
        raise HTTPException(
            status_code=502, detail="Retrieved-source model review failed; nothing was verified.",
        ) from None
    except Exception:
        # Tool/provider exceptions may embed credentials, page text or source paths.
        raise HTTPException(
            status_code=502, detail="C4B.2 failed without a verified result.",
        ) from None
