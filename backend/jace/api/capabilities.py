from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from jace.capabilities import resolve_runtime_capabilities, snapshot
from jace.capabilities.permissions import set_permission
from jace.database import SessionLocal
from jace.capabilities.device_broker import device_capability_broker
from jace.capabilities.device_policy import DEVICE_CAPABILITY_CATALOG
from jace.capabilities.device_schemas import (
    DeviceCapabilityCatalogItem,
    DeviceCapabilityCatalogResponse,
    DeviceCapabilityExecuteRequest,
    DeviceCapabilityRequestResponse,
)
from jace.config import settings
from jace.db.models import DeviceCapabilityRequest


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
    permission: Literal["allow", "ask", "deny"]


class CapabilityResolveRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=20_000,
        description=(
            "Natural-language user request to resolve against Jace's "
            "external capability registry."
        ),
    )


@router.get("", response_model=CapabilitySnapshotResponse)
async def capabilities():
    async with SessionLocal() as session:
        return CapabilitySnapshotResponse.model_validate(
            await snapshot(session)
        )


@router.post("/resolve")
async def resolve_capabilities(request: CapabilityResolveRequest):
    async with SessionLocal() as session:
        plan = await resolve_runtime_capabilities(
            session,
            request.message,
        )
        return plan.as_dict()


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

# JACE_4BS6_DEVICE_CAPABILITY_API
def _device_capability_user_id(request: Request) -> str | None:
    if settings.mode != "server":
        return None

    user_id = getattr(request.state, "auth_user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    return user_id


def _device_json(value: str | None, default):
    if not value:
        return default

    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _device_request_response(
    row: DeviceCapabilityRequest,
) -> DeviceCapabilityRequestResponse:
    return DeviceCapabilityRequestResponse(
        request_id=row.id,
        device_id=row.device_id,
        capability=row.capability,
        parameters=_device_json(row.parameters_json, {}),
        status=row.status,
        result=_device_json(row.result_json, None),
        error=row.error,
        evidence=_device_json(row.evidence_json, None),
        project_id=row.project_id,
        task_id=row.task_id,
        agent_id=row.agent_id,
        idempotency_key=row.idempotency_key,
        timeout_seconds=row.timeout_seconds,
        requested_at=row.requested_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        cancelled_at=row.cancelled_at,
    )


@router.get(
    "/device/catalog",
    response_model=DeviceCapabilityCatalogResponse,
)
async def device_capability_catalog():
    return DeviceCapabilityCatalogResponse(
        capabilities=[
            DeviceCapabilityCatalogItem(
                id=item.id,
                title=item.title,
                description=item.description,
                risk=item.risk,
                enabled=item.enabled,
                read_only=item.read_only,
            )
            for item in DEVICE_CAPABILITY_CATALOG.values()
        ]
    )


@router.post(
    "/device/execute",
    response_model=DeviceCapabilityRequestResponse,
)
async def execute_device_capability(
    payload: DeviceCapabilityExecuteRequest,
    request: Request,
):
    user_id = _device_capability_user_id(request)

    try:
        row = await device_capability_broker.execute(
            user_id=user_id,
            device_id=payload.device_id,
            capability=payload.capability,
            parameters=payload.parameters,
            timeout_seconds=payload.timeout_seconds,
            project_id=payload.project_id,
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            idempotency_key=payload.idempotency_key,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _device_request_response(row)


@router.get(
    "/device/requests/{request_id}",
    response_model=DeviceCapabilityRequestResponse,
)
async def get_device_capability_request(
    request_id: str,
    request: Request,
):
    user_id = _device_capability_user_id(request)

    try:
        row = await device_capability_broker.get_request(
            request_id,
            user_id=user_id,
            server_mode=settings.mode == "server",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _device_request_response(row)


@router.post(
    "/device/requests/{request_id}/cancel",
    response_model=DeviceCapabilityRequestResponse,
)
async def cancel_device_capability_request(
    request_id: str,
    request: Request,
):
    user_id = _device_capability_user_id(request)

    try:
        row = await device_capability_broker.cancel(
            request_id,
            user_id=user_id,
            server_mode=settings.mode == "server",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _device_request_response(row)

