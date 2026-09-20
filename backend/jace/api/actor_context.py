from __future__ import annotations

from fastapi import APIRouter, Depends

from jace.auth.actor_context import (
    ActorContext,
    require_actor,
)


router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.get("/actor-context")
async def actor_context(
    actor: ActorContext = Depends(require_actor),
):
    """
    Security diagnostic for 4B.4A.

    It exposes only the already-authenticated actor/client identifiers that the
    server resolved from request.state. It never accepts an identity from query
    parameters or headers itself.
    """

    return {
        "actor_id": actor.actor_id,
        "client_id": actor.client_id,
        "source": actor.source,
        "server_mode": actor.server_mode,
    }
