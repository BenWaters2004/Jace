from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from jace.connections import secrets
from jace.connections.oauth import (
    callback_html,
    complete_callback,
    oauth_session_status,
    start_oauth,
    verify_oauth_connection,
)
from jace.connections.providers import OAUTH_PROVIDERS, PROVIDERS
from jace.connections.schemas import (
    ConnectionCreate,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionUpdate,
    OAuthClientConfigListResponse,
    OAuthClientConfigResponse,
    OAuthClientConfigUpdate,
    OAuthSessionResponse,
    OAuthStartResponse,
    ProviderCapabilityResponse,
    ProviderListResponse,
    ProviderResponse,
    SecretStoreStatusResponse,
)
from jace.connections.service import (
    create_connection,
    delete_connection,
    delete_oauth_client_config,
    disconnect_connection,
    get_connection,
    get_oauth_client_config,
    list_connections,
    oauth_config_response,
    oauth_config_responses,
    save_oauth_client_config,
    to_response,
    update_connection,
)
from jace.database import SessionLocal

router = APIRouter(prefix="/connections", tags=["connections"])
callback_router = APIRouter(tags=["connections"])


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
    return SecretStoreStatusResponse(available=current.available, backend=current.backend, reason=current.reason)


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


@router.post("/{connection_id}/verify", response_model=ConnectionResponse)
async def verify(connection_id: str):
    async with SessionLocal() as session:
        row = await get_connection(session, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        try:
            row = await verify_oauth_connection(session, row)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return to_response(row)


@router.delete("/{connection_id}")
async def remove(connection_id: str):
    async with SessionLocal() as session:
        row = await get_connection(session, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        await delete_connection(session, row)
    return {"success": True}


@router.get("/oauth/config", response_model=OAuthClientConfigListResponse)
async def oauth_configs():
    async with SessionLocal() as session:
        return OAuthClientConfigListResponse(configs=await oauth_config_responses(session))


@router.put("/oauth/config/{provider_id}", response_model=OAuthClientConfigResponse)
async def save_oauth_config(provider_id: str, request: OAuthClientConfigUpdate):
    provider = next((item for item in OAUTH_PROVIDERS if item.id == provider_id), None)
    if provider is None:
        raise HTTPException(status_code=404, detail="OAuth provider not found.")
    async with SessionLocal() as session:
        try:
            row = await save_oauth_client_config(session, provider_id, request)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return oauth_config_response(provider, row)


@router.delete("/oauth/config/{provider_id}")
async def remove_oauth_config(provider_id: str):
    async with SessionLocal() as session:
        try:
            await delete_oauth_client_config(session, provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True}


@router.post("/oauth/{provider_id}/start", response_model=OAuthStartResponse)
async def begin_oauth(provider_id: str):
    async with SessionLocal() as session:
        try:
            return await start_oauth(session, provider_id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/session/{session_id}", response_model=OAuthSessionResponse)
async def oauth_status(session_id: str):
    async with SessionLocal() as session:
        try:
            return await oauth_session_status(session, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@callback_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def oauth_callback(
    state: str | None = Query(default=None),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    if not state and not code and not error:
        return HTMLResponse(callback_html(None))
    async with SessionLocal() as session:
        try:
            flow = await complete_callback(
                session,
                state=state,
                code=code,
                error=error,
                error_description=error_description,
            )
            return HTMLResponse(callback_html(flow), status_code=200)
        except ValueError as exc:
            return HTMLResponse(callback_html(None, str(exc)), status_code=400)
