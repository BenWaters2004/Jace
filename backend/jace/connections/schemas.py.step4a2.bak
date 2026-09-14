from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

ConnectionStatus = Literal["configured", "disconnected", "error"]
AuthMode = Literal["none", "bearer", "header"]


class ProviderCapabilityResponse(BaseModel):
    id: str
    label: str
    description: str
    category: str
    risk: str


class ProviderResponse(BaseModel):
    id: str
    name: str
    description: str
    auth_kind: str
    setup_state: str
    connection_label: str
    capabilities: list[ProviderCapabilityResponse]


class ProviderListResponse(BaseModel):
    providers: list[ProviderResponse]


class SecretStoreStatusResponse(BaseModel):
    available: bool
    backend: str
    reason: str | None = None


class ConnectionCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    base_url: AnyHttpUrl | None = None
    auth_mode: AuthMode = "none"
    header_name: str | None = Field(default=None, min_length=1, max_length=120)
    secret: str | None = Field(default=None, min_length=1, max_length=8000)

    @field_validator("header_name")
    @classmethod
    def clean_header_name(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_custom_api(self):
        if self.provider_id == "custom_api" and self.base_url is None:
            raise ValueError("Custom API connections require a base URL.")
        if self.auth_mode == "header" and not self.header_name:
            raise ValueError("Header authentication requires a header name.")
        if self.provider_id == "custom_api" and self.auth_mode != "none" and not self.secret:
            raise ValueError("This authentication mode requires an API secret.")
        return self


class ConnectionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: AnyHttpUrl | None = None
    auth_mode: AuthMode | None = None
    header_name: str | None = Field(default=None, min_length=1, max_length=120)
    secret: str | None = Field(default=None, min_length=1, max_length=8000)
    clear_secret: bool = False


class ConnectionResponse(BaseModel):
    id: str
    provider_id: str
    provider_name: str
    label: str
    status: ConnectionStatus
    auth_type: str
    config: dict[str, Any]
    capabilities: list[str]
    account_hint: str | None
    has_secret: bool
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None
    last_error: str | None


class ConnectionListResponse(BaseModel):
    secret_store: SecretStoreStatusResponse
    connections: list[ConnectionResponse]
