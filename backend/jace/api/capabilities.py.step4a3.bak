from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from jace.capabilities import snapshot
from jace.database import SessionLocal

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


class CapabilityResponse(BaseModel):
    id: str
    label: str
    description: str
    category: str
    source: Literal["local_tool", "connection"]
    state: Literal["ready", "blocked", "configured", "planned", "disconnected"]
    risk: str
    provider_id: str | None = None
    connection_id: str | None = None
    tool_name: str | None = None
    permission: str | None = None


class CapabilitySnapshotResponse(BaseModel):
    capabilities: list[CapabilityResponse]
    counts: dict[str, int]
    connection_count: int


@router.get("", response_model=CapabilitySnapshotResponse)
async def capabilities():
    async with SessionLocal() as session:
        return CapabilitySnapshotResponse.model_validate(await snapshot(session))
