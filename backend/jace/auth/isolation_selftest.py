from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jace.auth.resource_ownership import (
    ResourceOwnership,
    claim_resource,
    filter_or_claim_local,
    ownership_for,
    require_or_claim_local,
    require_owned_resource,
)


@dataclass
class _Row:
    id: str


async def run_cross_user_isolation_selftest() -> dict[str, bool]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
    )

    async with engine.begin() as connection:
        await connection.run_sync(
            ResourceOwnership.__table__.create
        )

    sessions = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    actor_a = "4b4a3-actor-a"
    actor_b = "4b4a3-actor-b"
    resource_a = "4b4a3-resource-a"
    resource_b = "4b4a3-resource-b"
    unowned = "4b4a3-unowned"

    async with sessions() as session:
        await claim_resource(
            session,
            resource_kind="workspace",
            resource_id=resource_a,
            actor_id=actor_a,
            client_id="client-a",
        )
        await claim_resource(
            session,
            resource_kind="workspace",
            resource_id=resource_b,
            actor_id=actor_b,
            client_id="client-b",
        )

        owned_a = await require_owned_resource(
            session,
            resource_kind="workspace",
            resource_id=resource_a,
            actor_id=actor_a,
        )
        assert owned_a.actor_id == actor_a

        cross_user_404 = False
        try:
            await require_owned_resource(
                session,
                resource_kind="workspace",
                resource_id=resource_a,
                actor_id=actor_b,
            )
        except HTTPException as exc:
            cross_user_404 = exc.status_code == 404

        assert cross_user_404

        server_unowned_fail_closed = False
        try:
            await require_or_claim_local(
                session,
                resource_kind="workspace",
                resource_id=unowned,
                actor_id=actor_a,
                client_id="client-a",
                server_mode=True,
            )
        except HTTPException as exc:
            server_unowned_fail_closed = (
                exc.status_code == 404
            )

        assert server_unowned_fail_closed
        assert (
            await ownership_for(
                session,
                "workspace",
                unowned,
            )
            is None
        )

        visible_a = await filter_or_claim_local(
            session,
            resource_kind="workspace",
            actor_id=actor_a,
            client_id="client-a",
            server_mode=True,
            rows=[
                _Row(resource_a),
                _Row(resource_b),
                _Row(unowned),
            ],
        )
        assert [
            row.id
            for row in visible_a
        ] == [resource_a]

        visible_b = await filter_or_claim_local(
            session,
            resource_kind="workspace",
            actor_id=actor_b,
            client_id="client-b",
            server_mode=True,
            rows=[
                _Row(resource_a),
                _Row(resource_b),
                _Row(unowned),
            ],
        )
        assert [
            row.id
            for row in visible_b
        ] == [resource_b]

        local_row = "4b4a3-local-history"
        adopted = await require_or_claim_local(
            session,
            resource_kind="conversation",
            resource_id=local_row,
            actor_id="local",
            client_id="local-desktop",
            server_mode=False,
        )
        assert adopted.actor_id == "local"

    await engine.dispose()

    return {
        "cross_user_404": True,
        "server_unowned_fail_closed": True,
        "actor_a_filter": True,
        "actor_b_filter": True,
        "local_adoption": True,
    }


def main() -> int:
    result = asyncio.run(
        run_cross_user_isolation_selftest()
    )

    for key, passed in result.items():
        print(
            "[PASS]" if passed else "[FAIL]",
            key,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
