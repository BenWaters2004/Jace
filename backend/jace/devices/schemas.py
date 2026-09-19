from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DeviceResponse(BaseModel):
    id: str
    owner_user_id: str | None
    name: str
    hostname: str
    platform: str
    os_version: str | None
    architecture: str | None
    agent_version: str | None
    capabilities: list[str]
    metadata: dict[str, Any]
    state: Literal["online", "offline", "revoked"]
    is_active: bool
    paired_at: datetime
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


class DeviceListResponse(BaseModel):
    devices: list[DeviceResponse]
    counts: dict[str, int]


class DevicePairingCreateRequest(BaseModel):
    requested_name: str | None = Field(default=None, max_length=160)
    requested_by_client_id: str | None = Field(default=None, max_length=160)


class DevicePairingResponse(BaseModel):
    pairing_id: str
    pairing_code: str
    expires_at: datetime
    requested_name: str | None = None


class DevicePairRequest(BaseModel):
    pairing_code: str = Field(min_length=20, max_length=500)
    name: str = Field(min_length=1, max_length=160)
    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=80)
    os_version: str | None = Field(default=None, max_length=160)
    architecture: str | None = Field(default=None, max_length=80)
    agent_version: str | None = Field(default=None, max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DevicePairResponse(BaseModel):
    device: DeviceResponse
    device_token: str


class DeviceHeartbeatRequest(BaseModel):
    agent_version: str | None = Field(default=None, max_length=80)
    platform: str | None = Field(default=None, max_length=80)
    os_version: str | None = Field(default=None, max_length=160)
    architecture: str | None = Field(default=None, max_length=80)
    capabilities: list[str] | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] | None = None


class DeviceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
