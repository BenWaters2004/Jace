from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jace.db.models import Base, new_id, utc_now


class ConnectionRecord(Base):
    """Non-secret account/API metadata. Credentials and OAuth tokens stay in the OS credential vault."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="configured", index=True)
    auth_type: Mapped[str] = mapped_column(String(40), nullable=False, default="none")
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    account_hint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthClientConfigRecord(Base):
    """Non-secret OAuth application configuration. Provider client secrets remain in Credential Manager."""

    __tablename__ = "oauth_client_configs"

    provider_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(500), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

class CapabilityPermissionRecord(Base):
    """Per-connection provider capability policy. Contains no provider secret."""
    __tablename__ = "connection_capability_permissions"
    id: Mapped[str] = mapped_column(String(500), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    capability_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="ask")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

class ExternalAccessPolicyRecord(Base):
    """Runtime kill switches for connected external services."""

    __tablename__ = "external_access_policy"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default="default",
    )
    external_services_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    provider_states_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="{}",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

