from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DeviceCapabilityStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "timed_out",
    "cancelled",
]


class DeviceCapabilityExecuteRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    capability: str = Field(min_length=1, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    project_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)
    agent_id: str | None = Field(default=None, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=160)


class DeviceCapabilityRequestResponse(BaseModel):
    request_id: str
    device_id: str
    capability: str
    parameters: dict[str, Any]
    status: DeviceCapabilityStatus
    result: Any | None = None
    error: str | None = None
    evidence: dict[str, Any] | None = None
    project_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    idempotency_key: str | None = None
    timeout_seconds: int
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class DeviceCapabilityCatalogItem(BaseModel):
    id: str
    title: str
    description: str
    risk: Literal["low", "medium", "high"]
    enabled: bool
    read_only: bool


class DeviceCapabilityCatalogResponse(BaseModel):
    capabilities: list[DeviceCapabilityCatalogItem]
