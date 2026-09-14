from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from jace.connections import secrets
from jace.connections.providers import PROVIDERS
from jace.connections.schemas import (
    ConnectionCreate,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionUpdate,
    ProviderCapabilityResponse,
    ProviderListResponse,
    ProviderResponse,
    SecretStoreStatusResponse,
)
from jace.connections.service import (
    create_connection,
    delete_connection,
    disconnect_connection,
    get_connection,
    list_connections,
    to_response,
    update_connection,
)
from jace.database import SessionLocal

router = APIRouter(prefix="/connections", tags=["connections"])


def _provider_response(provider) -> ProviderResponse:
    return ProviderResponse(
        id=provider.id,
        name=provider.name,
        description=provider.description,
        auth_kind=provider.auth_kind,
        setup_state=provider.setup_state,
        connection_label=provider.connection_label,
        capabilities=[
            ProviderCapabilityResponse(
                id=capability.id,
                label=capability.label,
                description=capability.description,
                category=capability.category,
                risk=capability.risk,
            )
            for capability in provider.capabilities
        ],
    )


def _secret_store_response() -> SecretStoreStatusResponse:
    current = secrets.status()
    return SecretStoreStatusResponse(
        available=current.available,
        backend=current.backend,
        reason=current.reason,
    )


@router.get("/providers", response_model=ProviderListResponse)
async def providers():
    return ProviderListResponse(providers=[_provider_response(provider) for provider in PROVIDERS])


@router.get("", response_model=ConnectionListResponse)
async def connections():
    async with SessionLocal() as session:
        rows = await list_connections(session)
        return ConnectionListResponse(
            secret_store=_secret_store_response(),
            connections=[to_response(row) for row in rows],
        )


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create(request: ConnectionCreate):
    async with SessionLocal() as session:
        try:
            row = await create_connection(session, request)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return to_response(row)


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update(connection_id: str, request: ConnectionUpdate):
    async with SessionLocal() as session:
        row = await get_connection(session, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        try:
            row = await update_connection(session, row, request)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return to_response(row)


@router.post("/{connection_id}/disconnect", response_model=ConnectionResponse)
async def disconnect(connection_id: str):
    async with SessionLocal() as session:
        row = await get_connection(session, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        row = await disconnect_connection(session, row)
        return to_response(row)


@router.delete("/{connection_id}")
async def remove(connection_id: str):
    async with SessionLocal() as session:
        row = await get_connection(session, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        await delete_connection(session, row)
    return {"success": True}
