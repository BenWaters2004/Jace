from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AuthStatusResponse(BaseModel):
    mode: str
    auth_required: bool
    bootstrap_required: bool
    bootstrap_available: bool


class AuthUserResponse(BaseModel):
    id: str
    email: str | None
    display_name: str
    is_active: bool
    is_admin: bool
    local: bool = False
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class AuthBootstrapRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=512)
    client_id: str = Field(min_length=1, max_length=160)
    client_name: str | None = Field(default=None, max_length=200)


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)
    client_id: str = Field(min_length=1, max_length=160)
    client_name: str | None = Field(default=None, max_length=200)


class AuthRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=500)
    client_id: str = Field(min_length=1, max_length=160)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: str
    user: AuthUserResponse


class AuthSessionResponse(BaseModel):
    id: str
    client_id: str
    client_name: str | None
    created_at: datetime
    last_seen_at: datetime
    access_expires_at: datetime
    refresh_expires_at: datetime
    revoked_at: datetime | None
    current: bool = False


class AuthSessionListResponse(BaseModel):
    sessions: list[AuthSessionResponse]
