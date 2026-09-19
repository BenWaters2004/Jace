from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jace.model_gateway import (
    ModelGatewayError,
    model_gateway,
)


router = APIRouter(
    prefix="/model-gateway",
    tags=["model-gateway"],
)


class ResolveModelRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=300)
    local_only: bool = False


@router.get("/status")
async def model_gateway_status():
    capabilities = [
        "conversation.fast",
        "reasoning.high",
        "coding.high",
        "vision",
        "research.high",
        "local.private",
        "memory.extract",
        "embedding",
        "reranking",
    ]

    routes = {}

    for capability in capabilities:
        try:
            route = model_gateway.resolve(capability)
            routes[capability] = {
                "provider": route.provider,
                "model": route.model,
                "local": route.local,
                "route_id": route.route_id,
            }
        except ModelGatewayError as exc:
            routes[capability] = {
                "error": str(exc),
            }

    return {
        "providers": [
            {
                "provider_id": provider.provider_id,
                "local": provider.local,
                "enabled": provider.enabled,
                "operations": list(provider.operations),
            }
            for provider in model_gateway.providers()
        ],
        "routes": routes,
    }


@router.post("/resolve")
async def resolve_model(payload: ResolveModelRequest):
    try:
        route = model_gateway.resolve(
            payload.capability,
            requested_model=payload.model,
            local_only=payload.local_only,
        )
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "capability": route.capability,
        "provider": route.provider,
        "model": route.model,
        "local": route.local,
        "explicit_model": route.explicit_model,
        "route_id": route.route_id,
    }
