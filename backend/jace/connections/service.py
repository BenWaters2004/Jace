from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.connections import secrets
from jace.connections.models import ConnectionRecord, OAuthClientConfigRecord
from jace.connections.providers import OAUTH_PROVIDERS, ProviderDefinition, get_provider
from jace.connections.schemas import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    OAuthClientConfigResponse,
    OAuthClientConfigUpdate,
)
from jace.db.models import utc_now

PRIMARY_SECRET_KEY = "primary"
OAUTH_TOKEN_KEY = "oauth_tokens"
OAUTH_CLIENT_SECRET_KEY = "oauth_client_secret"
OAUTH_CLIENT_TARGET_PREFIX = "oauth-client"


def _loads_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _provider_or_error(provider_id: str) -> ProviderDefinition:
    provider = get_provider(provider_id)
    if provider is None:
        raise ValueError(f"Unknown connection provider: {provider_id}")
    return provider


def _safe_config(payload: ConnectionCreate | ConnectionUpdate, existing: dict | None = None) -> dict:
    config = dict(existing or {})
    if getattr(payload, "base_url", None) is not None:
        config["base_url"] = str(payload.base_url).rstrip("/")
    if getattr(payload, "auth_mode", None) is not None:
        config["auth_mode"] = payload.auth_mode
    if getattr(payload, "header_name", None) is not None:
        config["header_name"] = payload.header_name
    if config.get("auth_mode") != "header":
        config.pop("header_name", None)
    return config


def _account_hint(config: dict) -> str | None:
    base_url = config.get("base_url")
    if not isinstance(base_url, str):
        return None
    parsed = urlparse(base_url)
    return parsed.netloc or None


def oauth_client_target(provider_id: str) -> str:
    return f"{OAUTH_CLIENT_TARGET_PREFIX}-{provider_id}"


def connection_has_secret(row: ConnectionRecord) -> bool:
    return secrets.exists(row.id, PRIMARY_SECRET_KEY) or secrets.exists(row.id, OAUTH_TOKEN_KEY)


def to_response(row: ConnectionRecord) -> ConnectionResponse:
    provider = _provider_or_error(row.provider_id)
    return ConnectionResponse(
        id=row.id,
        provider_id=row.provider_id,
        provider_name=provider.name,
        label=row.label,
        status=row.status,
        auth_type=row.auth_type,
        config=_loads_object(row.config_json),
        capabilities=_loads_list(row.capabilities_json),
        account_hint=row.account_hint,
        has_secret=connection_has_secret(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_verified_at=row.last_verified_at,
        last_error=row.last_error,
    )


async def list_connections(session: AsyncSession) -> list[ConnectionRecord]:
    result = await session.execute(select(ConnectionRecord).order_by(ConnectionRecord.provider_id, ConnectionRecord.label))
    return list(result.scalars())


async def list_provider_connections(session: AsyncSession, provider_id: str) -> list[ConnectionRecord]:
    result = await session.execute(
        select(ConnectionRecord)
        .where(ConnectionRecord.provider_id == provider_id)
        .order_by(ConnectionRecord.updated_at.desc())
    )
    return list(result.scalars())


async def get_connection(session: AsyncSession, connection_id: str) -> ConnectionRecord | None:
    return await session.get(ConnectionRecord, connection_id)


async def create_connection(session: AsyncSession, payload: ConnectionCreate) -> ConnectionRecord:
    provider = _provider_or_error(payload.provider_id)
    if provider.id != "custom_api":
        raise ValueError(f"{provider.name} connections are created through OAuth in Step 4A.2.")

    config = _safe_config(payload)
    row = ConnectionRecord(
        provider_id=provider.id,
        label=payload.label.strip(),
        status="configured",
        auth_type=payload.auth_mode,
        config_json=json.dumps(config, separators=(",", ":")),
        capabilities_json=json.dumps([cap.id for cap in provider.capabilities]),
        account_hint=_account_hint(config),
        updated_at=utc_now(),
    )
    session.add(row)
    await session.flush()

    if payload.secret:
        try:
            secrets.write(row.id, PRIMARY_SECRET_KEY, payload.secret)
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await session.refresh(row)
    return row


async def update_connection(session: AsyncSession, row: ConnectionRecord, payload: ConnectionUpdate) -> ConnectionRecord:
    provider = _provider_or_error(row.provider_id)
    if provider.id != "custom_api":
        raise ValueError("OAuth account connections are refreshed through their provider flow, not edited manually.")

    config = _safe_config(payload, _loads_object(row.config_json))
    if payload.label is not None:
        row.label = payload.label.strip()
    if payload.auth_mode is not None:
        row.auth_type = payload.auth_mode
    row.config_json = json.dumps(config, separators=(",", ":"))
    row.account_hint = _account_hint(config)
    row.updated_at = utc_now()
    row.last_error = None

    if payload.clear_secret:
        secrets.delete(row.id, PRIMARY_SECRET_KEY)
    if payload.secret:
        secrets.write(row.id, PRIMARY_SECRET_KEY, payload.secret)
        row.status = "configured"
    elif row.auth_type == "none":
        row.status = "configured"

    await session.commit()
    await session.refresh(row)
    return row


async def disconnect_connection(session: AsyncSession, row: ConnectionRecord) -> ConnectionRecord:
    secrets.delete(row.id, PRIMARY_SECRET_KEY)
    secrets.delete(row.id, OAUTH_TOKEN_KEY)
    row.status = "disconnected"
    row.updated_at = utc_now()
    row.last_error = None
    await session.commit()
    await session.refresh(row)
    return row


async def delete_connection(session: AsyncSession, row: ConnectionRecord) -> None:
    secrets.delete(row.id, PRIMARY_SECRET_KEY)
    secrets.delete(row.id, OAUTH_TOKEN_KEY)
    await session.delete(row)
    await session.commit()


async def get_oauth_client_config(session: AsyncSession, provider_id: str) -> OAuthClientConfigRecord | None:
    return await session.get(OAuthClientConfigRecord, provider_id)


async def save_oauth_client_config(
    session: AsyncSession,
    provider_id: str,
    payload: OAuthClientConfigUpdate,
) -> OAuthClientConfigRecord:
    provider = _provider_or_error(provider_id)
    if provider.oauth_flow is None:
        raise ValueError(f"{provider.name} does not use OAuth application configuration.")

    row = await get_oauth_client_config(session, provider_id)
    now = utc_now()
    config: dict[str, str] = {}
    if row is not None:
        config = _loads_object(row.config_json)
    if provider.oauth_tenant_supported:
        config["tenant"] = payload.tenant or config.get("tenant") or "common"
    else:
        config.pop("tenant", None)

    if row is None:
        row = OAuthClientConfigRecord(
            provider_id=provider_id,
            client_id=payload.client_id,
            config_json=json.dumps(config, separators=(",", ":")),
            updated_at=now,
        )
        session.add(row)
    else:
        row.client_id = payload.client_id
        row.config_json = json.dumps(config, separators=(",", ":"))
        row.updated_at = now

    target = oauth_client_target(provider_id)
    if payload.clear_client_secret:
        secrets.delete(target, OAUTH_CLIENT_SECRET_KEY)
    if payload.client_secret:
        if not provider.oauth_client_secret_supported:
            raise ValueError(f"{provider.name} does not use a client secret in Jace's OAuth flow.")
        secrets.write(target, OAUTH_CLIENT_SECRET_KEY, payload.client_secret)

    await session.commit()
    await session.refresh(row)
    return row


async def delete_oauth_client_config(session: AsyncSession, provider_id: str) -> None:
    provider = _provider_or_error(provider_id)
    if provider.oauth_flow is None:
        raise ValueError(f"{provider.name} does not use OAuth application configuration.")
    row = await get_oauth_client_config(session, provider_id)
    secrets.delete(oauth_client_target(provider_id), OAUTH_CLIENT_SECRET_KEY)
    if row is not None:
        await session.delete(row)
        await session.commit()


def oauth_client_secret(provider_id: str) -> str | None:
    return secrets.read(oauth_client_target(provider_id), OAUTH_CLIENT_SECRET_KEY)


def oauth_config_response(provider: ProviderDefinition, row: OAuthClientConfigRecord | None) -> OAuthClientConfigResponse:
    if provider.oauth_flow is None:
        raise ValueError("Provider does not use OAuth.")
    config = _loads_object(row.config_json) if row else {}
    if provider.id == "google":
        redirect_uri = "http://127.0.0.1:8000"
    elif provider.id == "microsoft":
        redirect_uri = "http://localhost:8000"
    else:
        redirect_uri = None
    has_secret = secrets.exists(oauth_client_target(provider.id), OAUTH_CLIENT_SECRET_KEY)
    return OAuthClientConfigResponse(
        provider_id=provider.id,
        provider_name=provider.name,
        configured=bool(row and row.client_id.strip()),
        client_id=row.client_id if row else None,
        has_client_secret=has_secret,
        client_secret_supported=provider.oauth_client_secret_supported,
        tenant=(config.get("tenant") if isinstance(config.get("tenant"), str) else None),
        tenant_supported=provider.oauth_tenant_supported,
        flow_kind=provider.oauth_flow,
        redirect_uri=redirect_uri,
        scopes=list(provider.oauth_scopes),
    )


async def oauth_config_responses(session: AsyncSession) -> list[OAuthClientConfigResponse]:
    return [oauth_config_response(provider, await get_oauth_client_config(session, provider.id)) for provider in OAUTH_PROVIDERS]
