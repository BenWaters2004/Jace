from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.config import settings
from jace.db.models import Device, DevicePairing, utc_now


@dataclass(slots=True)
class PairingGrant:
    row: DevicePairing
    pairing_code: str


@dataclass(slots=True)
class PairedDevice:
    row: Device
    device_token: str


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_pairing_code() -> str:
    return "jace_pair_" + secrets.token_urlsafe(40)


def _new_device_token() -> str:
    return "jace_dev_" + secrets.token_urlsafe(64)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalise_capabilities(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if len(value) > 160:
            raise ValueError("Device capability identifiers must be 160 characters or fewer.")
        if value not in result:
            result.append(value)
    return sorted(result)


def _json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def device_state(device: Device, *, now: datetime | None = None) -> str:
    if not device.is_active or device.revoked_at is not None:
        return "revoked"
    if device.last_seen_at is None:
        return "offline"

    current = now or utc_now()
    age = current - _as_utc(device.last_seen_at)
    if age.total_seconds() <= settings.device_online_window_seconds:
        return "online"
    return "offline"


def device_response(device: Device):
    from jace.devices.schemas import DeviceResponse

    return DeviceResponse(
        id=device.id,
        owner_user_id=device.owner_user_id,
        name=device.name,
        hostname=device.hostname,
        platform=device.platform,
        os_version=device.os_version,
        architecture=device.architecture,
        agent_version=device.agent_version,
        capabilities=_json_list(device.capabilities_json),
        metadata=_json_object(device.metadata_json),
        state=device_state(device),
        is_active=device.is_active,
        paired_at=device.paired_at,
        created_at=device.created_at,
        updated_at=device.updated_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
    )


async def create_pairing(
    session: AsyncSession,
    *,
    owner_user_id: str | None,
    requested_name: str | None,
    requested_by_client_id: str | None,
) -> PairingGrant:
    now = utc_now()
    pairing_code = _new_pairing_code()

    row = DevicePairing(
        owner_user_id=owner_user_id,
        pairing_code_hash=_hash_secret(pairing_code),
        requested_name=(requested_name.strip() if requested_name else None),
        requested_by_client_id=(
            requested_by_client_id.strip() if requested_by_client_id else None
        ),
        expires_at=now + timedelta(minutes=settings.device_pairing_minutes),
        created_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return PairingGrant(row=row, pairing_code=pairing_code)


async def pair_device(
    session: AsyncSession,
    *,
    pairing_code: str,
    name: str,
    hostname: str,
    platform: str,
    os_version: str | None,
    architecture: str | None,
    agent_version: str | None,
    capabilities: list[str],
    metadata: dict[str, Any],
) -> PairedDevice:
    now = utc_now()
    code_hash = _hash_secret(pairing_code)

    result = await session.execute(
        select(DevicePairing).where(DevicePairing.pairing_code_hash == code_hash)
    )
    pairing = result.scalar_one_or_none()

    if pairing is None:
        raise ValueError("Pairing code is invalid.")
    if pairing.used_at is not None:
        raise ValueError("Pairing code has already been used.")
    if _as_utc(pairing.expires_at) <= now:
        raise ValueError("Pairing code has expired.")

    clean_name = name.strip()
    clean_hostname = hostname.strip()
    clean_platform = platform.strip()
    if not clean_name or not clean_hostname or not clean_platform:
        raise ValueError("Device name, hostname and platform are required.")

    device_token = _new_device_token()
    device = Device(
        owner_user_id=pairing.owner_user_id,
        name=clean_name,
        hostname=clean_hostname,
        platform=clean_platform,
        os_version=(os_version.strip() if os_version else None),
        architecture=(architecture.strip() if architecture else None),
        agent_version=(agent_version.strip() if agent_version else None),
        device_token_hash=_hash_secret(device_token),
        capabilities_json=_json_dump(_normalise_capabilities(capabilities)),
        metadata_json=_json_dump(metadata),
        is_active=True,
        paired_at=now,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )

    pairing.used_at = now
    session.add(device)
    await session.commit()
    await session.refresh(device)

    return PairedDevice(row=device, device_token=device_token)


async def authenticate_device(session: AsyncSession, device_token: str) -> Device | None:
    token_hash = _hash_secret(device_token)
    result = await session.execute(
        select(Device).where(Device.device_token_hash == token_hash)
    )
    device = result.scalar_one_or_none()
    if device is None or not device.is_active or device.revoked_at is not None:
        return None
    return device


async def heartbeat(
    session: AsyncSession,
    *,
    device: Device,
    agent_version: str | None,
    platform: str | None,
    os_version: str | None,
    architecture: str | None,
    capabilities: list[str] | None,
    metadata: dict[str, Any] | None,
) -> Device:
    now = utc_now()

    if agent_version is not None:
        device.agent_version = agent_version.strip() or None
    if platform is not None:
        device.platform = platform.strip() or device.platform
    if os_version is not None:
        device.os_version = os_version.strip() or None
    if architecture is not None:
        device.architecture = architecture.strip() or None
    if capabilities is not None:
        device.capabilities_json = _json_dump(_normalise_capabilities(capabilities))
    if metadata is not None:
        device.metadata_json = _json_dump(metadata)

    device.last_seen_at = now
    device.updated_at = now
    await session.commit()
    await session.refresh(device)
    return device


async def list_devices(
    session: AsyncSession,
    *,
    owner_user_id: str | None,
    server_mode: bool,
) -> list[Device]:
    statement = select(Device).order_by(Device.name.asc(), Device.created_at.asc())
    if server_mode:
        statement = statement.where(Device.owner_user_id == owner_user_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_device(
    session: AsyncSession,
    *,
    device_id: str,
    owner_user_id: str | None,
    server_mode: bool,
) -> Device | None:
    statement = select(Device).where(Device.id == device_id)
    if server_mode:
        statement = statement.where(Device.owner_user_id == owner_user_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def rename_device(session: AsyncSession, *, device: Device, name: str) -> Device:
    clean = name.strip()
    if not clean:
        raise ValueError("Device name cannot be empty.")
    device.name = clean
    device.updated_at = utc_now()
    await session.commit()
    await session.refresh(device)
    return device


async def revoke_device(session: AsyncSession, *, device: Device) -> Device:
    now = utc_now()
    device.is_active = False
    device.revoked_at = now
    device.updated_at = now
    await session.commit()
    await session.refresh(device)
    return device
