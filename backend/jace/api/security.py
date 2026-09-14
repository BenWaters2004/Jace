from __future__ import annotations

# JACE_STEP4A6_SECURITY_API

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jace.capabilities.access import (
    external_access_policy,
    update_external_access_policy,
)
from jace.connections.providers import PROVIDERS
from jace.database import SessionLocal


router = APIRouter(
    prefix="/security",
    tags=["security"],
)


class ExternalAccessPolicyResponse(BaseModel):
    external_services_enabled: bool
    providers: dict[str, bool]
    provider_names: dict[str, str]


class ExternalAccessPolicyUpdate(BaseModel):
    external_services_enabled: bool | None = None
    providers: dict[str, bool] | None = Field(
        default=None,
    )


def _response(policy) -> ExternalAccessPolicyResponse:
    return ExternalAccessPolicyResponse(
        external_services_enabled=policy.external_services_enabled,
        providers=policy.providers,
        provider_names={
            provider.id: provider.name
            for provider in PROVIDERS
        },
    )


@router.get(
    "/external-access",
    response_model=ExternalAccessPolicyResponse,
)
async def get_external_access():
    async with SessionLocal() as session:
        return _response(
            await external_access_policy(session)
        )


@router.patch(
    "/external-access",
    response_model=ExternalAccessPolicyResponse,
)
async def patch_external_access(
    request: ExternalAccessPolicyUpdate,
):
    async with SessionLocal() as session:
        try:
            policy = await update_external_access_policy(
                session,
                external_services_enabled=request.external_services_enabled,
                providers=request.providers,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        return _response(policy)


@router.post(
    "/external-access/emergency-stop",
    response_model=ExternalAccessPolicyResponse,
)
async def emergency_stop_external_access():
    async with SessionLocal() as session:
        policy = await update_external_access_policy(
            session,
            external_services_enabled=False,
        )
        return _response(policy)
