from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jace.capabilities import snapshot
from jace.capabilities.permissions import set_permission
from jace.database import SessionLocal

router = APIRouter(
    prefix="/capabilities",
    tags=["capabilities"],
)


class CapabilityResponse(BaseModel):
    id: str
    label: str
    description: str
    category: str
    source: Literal["local_tool", "connection"]
    state: Literal[
        "ready",
        "blocked",
        "configured",
        "planned",
        "disconnected",
    ]
    risk: str

    provider_id: str | None = None
    provider_capability_id: str | None = None

    connection_id: str | None = None
    connection_status: str | None = None
    account_hint: str | None = None

    tool_name: str | None = None
    permission: str | None = None

    required_scopes: list[str] = []
    granted_scopes: list[str] = []
    missing_scopes: list[str] = []

    availability_reason: str | None = None


class CapabilitySnapshotResponse(BaseModel):
    capabilities: list[CapabilityResponse]
    counts: dict[str, int]
    connection_count: int


class CapabilityPermissionUpdate(BaseModel):
    permission: Literal[
        "allow",
        "ask",
        "deny",
    ]


@router.get(
    "",
    response_model=CapabilitySnapshotResponse,
)
async def capabilities():
    async with SessionLocal() as session:
        return CapabilitySnapshotResponse.model_validate(
            await snapshot(session)
        )


@router.patch(
    "/connections/{connection_id}/{capability_id}/permission",
    response_model=CapabilitySnapshotResponse,
)
async def update_connection_capability_permission(
    connection_id: str,
    capability_id: str,
    request: CapabilityPermissionUpdate,
):
    async with SessionLocal() as session:
        try:
            await set_permission(
                session,
                connection_id,
                capability_id,
                request.permission,
            )

            return CapabilitySnapshotResponse.model_validate(
                await snapshot(session)
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc
