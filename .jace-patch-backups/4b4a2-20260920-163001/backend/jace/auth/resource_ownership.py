from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Literal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import DateTime, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from jace.db.models import Base


ResourceKind = Literal[
    "device",
    "workspace",
    "execution_scope",
    "process",
    "terminal",
    "approval",
    "audit",
    "conversation",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResourceOwnership(Base):
    """
    Sidecar ownership registry.

    4B.4A deliberately uses a sidecar table rather than adding actor_id columns
    to every existing runtime table in one migration. This gives every security
    boundary a single ownership primitive while preserving current local data.
    """

    __tablename__ = "resource_ownership"
    __table_args__ = (
        UniqueConstraint(
            "resource_kind",
            "resource_id",
            name="uq_resource_ownership_kind_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    resource_kind: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


async def ownership_for(
    session: AsyncSession,
    resource_kind: ResourceKind,
    resource_id: str,
) -> ResourceOwnership | None:
    result = await session.execute(
        select(ResourceOwnership).where(
            ResourceOwnership.resource_kind
            == resource_kind,
            ResourceOwnership.resource_id
            == resource_id,
        )
    )
    return result.scalar_one_or_none()


async def claim_resource(
    session: AsyncSession,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
    actor_id: str,
    client_id: str | None = None,
) -> ResourceOwnership:
    existing = await ownership_for(
        session,
        resource_kind,
        resource_id,
    )

    if existing is not None:
        if existing.actor_id != actor_id:
            raise HTTPException(
                status_code=404,
                detail="Resource not found.",
            )

        return existing

    row = ResourceOwnership(
        resource_kind=resource_kind,
        resource_id=resource_id,
        actor_id=actor_id,
        client_id=client_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def require_owned_resource(
    session: AsyncSession,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
    actor_id: str,
) -> ResourceOwnership:
    existing = await ownership_for(
        session,
        resource_kind,
        resource_id,
    )

    if (
        existing is None
        or existing.actor_id != actor_id
    ):
        # Return 404 rather than 403 so UUID existence is not leaked across
        # users.
        raise HTTPException(
            status_code=404,
            detail="Resource not found.",
        )

    return existing


async def owned_resource_ids(
    session: AsyncSession,
    *,
    resource_kind: ResourceKind,
    actor_id: str,
) -> set[str]:
    result = await session.execute(
        select(ResourceOwnership.resource_id).where(
            ResourceOwnership.resource_kind
            == resource_kind,
            ResourceOwnership.actor_id
            == actor_id,
        )
    )
    return set(result.scalars().all())


async def filter_owned(
    session: AsyncSession,
    *,
    resource_kind: ResourceKind,
    actor_id: str,
    rows: Iterable,
) -> list:
    owned = await owned_resource_ids(
        session,
        resource_kind=resource_kind,
        actor_id=actor_id,
    )

    return [
        row
        for row in rows
        if str(getattr(row, "id", ""))
        in owned
    ]


async def release_resource(
    session: AsyncSession,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
    actor_id: str,
) -> None:
    existing = await require_owned_resource(
        session,
        resource_kind=resource_kind,
        resource_id=resource_id,
        actor_id=actor_id,
    )

    await session.delete(existing)
    await session.commit()
