from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jace.config import settings
from jace.privacy import privacy_gateway
from jace.privacy.policy import (
    default_mode_for_classification,
)


router = APIRouter(
    prefix="/privacy",
    tags=["privacy"],
)


class PrivacyInspectRequest(BaseModel):
    payload: Any
    classification_hint: str | None = Field(
        default=None,
        max_length=40,
    )
    requested_mode: str | None = Field(
        default=None,
        max_length=40,
    )


@router.get("/status")
async def privacy_status():
    classifications = [
        "public",
        "internal",
        "confidential",
        "personal",
        "secret",
    ]

    return {
        "enabled": settings.privacy_enabled,
        "cloud_egress_enabled": (
            settings.privacy_cloud_egress_enabled
        ),
        "default_classification": (
            settings.privacy_default_classification
        ),
        "classification_policy": {
            value: default_mode_for_classification(value)  # type: ignore[arg-type]
            for value in classifications
        },
    }


@router.post("/inspect")
async def inspect_privacy(
    payload: PrivacyInspectRequest,
):
    try:
        decision = privacy_gateway.inspect(
            payload.payload,
            classification_hint=payload.classification_hint,
            requested_mode=payload.requested_mode,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "classification": decision.classification,
        "mode": decision.mode,
        "require_local": decision.require_local,
        "content_sha256": decision.content_sha256,
        "detections": [
            {
                "kind": detection.kind,
                "classification": detection.classification,
                "count": detection.count,
            }
            for detection in decision.detections
        ],
    }
