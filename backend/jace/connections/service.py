from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.connections import secrets
from jace.connections.models import ConnectionRecord
from jace.connections.providers import ProviderDefinition, get_provider
from jace.connections.schemas import ConnectionCreate, ConnectionResponse, ConnectionUpdate
from jace.db.models import utc_now

SECRET_KEY = "primary"


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
        has_secret=secrets.exists(row.id, SECRET_KEY),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_verified_at=row.last_verified_at,
        last_error=row.last_error,
    )


async def list_connections(session: AsyncSession) -> list[ConnectionRecord]:
    result = await session.execute(select(ConnectionRecord).order_by(ConnectionRecord.provider_id, ConnectionRecord.label))
    return list(result.scalars())


async def get_connection(session: AsyncSession, connection_id: str) -> ConnectionRecord | None:
    return await session.get(ConnectionRecord, connection_id)


async def create_connection(session: AsyncSession, payload: ConnectionCreate) -> ConnectionRecord:
    provider = _provider_or_error(payload.provider_id)
    if provider.setup_state != "available":
        raise ValueError(
            f"{provider.name} requires the OAuth flow planned for the next 4A step; it cannot be configured manually yet."
        )
    if provider.id != "custom_api":
        raise ValueError("This provider does not support manual setup in 4A.1.")

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
            secrets.write(row.id, SECRET_KEY, payload.secret)
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await session.refresh(row)
    return row


async def update_connection(session: AsyncSession, row: ConnectionRecord, payload: ConnectionUpdate) -> ConnectionRecord:
    provider = _provider_or_error(row.provider_id)
    if provider.id != "custom_api":
        raise ValueError("Only Custom API connections can be edited manually in 4A.1.")

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
        secrets.delete(row.id, SECRET_KEY)
    if payload.secret:
        secrets.write(row.id, SECRET_KEY, payload.secret)
        row.status = "configured"
    elif row.auth_type == "none":
        row.status = "configured"

    await session.commit()
    await session.refresh(row)
    return row


async def disconnect_connection(session: AsyncSession, row: ConnectionRecord) -> ConnectionRecord:
    secrets.delete(row.id, SECRET_KEY)
    row.status = "disconnected"
    row.updated_at = utc_now()
    row.last_error = None
    await session.commit()
    await session.refresh(row)
    return row


async def delete_connection(session: AsyncSession, row: ConnectionRecord) -> None:
    secrets.delete(row.id, SECRET_KEY)
    await session.delete(row)
    await session.commit()
