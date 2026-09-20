from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from jace.config import settings


_LOCAL_ACTOR_ID = "local"
_LOCAL_CLIENT_ID = "local-desktop"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated identity used by ownership-sensitive Jace operations."""

    actor_id: str
    client_id: str | None
    source: str
    server_mode: bool


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def _mapping_value(
    value: Any,
    keys: tuple[str, ...],
) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = _clean(value.get(key))
            if candidate:
                return candidate

    for key in keys:
        candidate = _clean(getattr(value, key, None))
        if candidate:
            return candidate

    return None


def actor_from_state(
    state: Any,
    *,
    server_mode: bool,
) -> ActorContext | None:
    """
    Resolve identity exclusively from server-populated request.state.

    Deliberately does not inspect user-controlled identity headers. The existing
    4B.S3 authentication layer must authenticate the request first and place
    its principal/identity on request.state.
    """

    if not server_mode:
        return ActorContext(
            actor_id=_LOCAL_ACTOR_ID,
            client_id=_LOCAL_CLIENT_ID,
            source="local-runtime",
            server_mode=False,
        )

    direct_actor_keys = (
        "actor_id",
        "user_id",
        "authenticated_user_id",
        "principal_id",
        "subject",
        "sub",
    )
    direct_client_keys = (
        "client_id",
        "authenticated_client_id",
        "session_id",
    )

    actor_id = _mapping_value(
        state,
        direct_actor_keys,
    )
    client_id = _mapping_value(
        state,
        direct_client_keys,
    )

    if actor_id:
        return ActorContext(
            actor_id=actor_id,
            client_id=client_id,
            source="request.state",
            server_mode=True,
        )

    nested_names = (
        "actor",
        "user",
        "current_user",
        "principal",
        "identity",
        "auth",
        "authentication",
    )

    for name in nested_names:
        nested = (
            state.get(name)
            if isinstance(state, dict)
            else getattr(state, name, None)
        )

        if nested is None:
            continue

        actor_id = _mapping_value(
            nested,
            (
                "actor_id",
                "user_id",
                "id",
                "subject",
                "sub",
            ),
        )

        if not actor_id:
            continue

        nested_client_id = _mapping_value(
            nested,
            (
                "client_id",
                "session_id",
            ),
        )

        return ActorContext(
            actor_id=actor_id,
            client_id=client_id or nested_client_id,
            source=f"request.state.{name}",
            server_mode=True,
        )

    return None


async def require_actor(
    request: Request,
) -> ActorContext:
    actor = actor_from_state(
        request.state,
        server_mode=(
            settings.mode == "server"
        ),
    )

    if actor is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Authenticated actor identity is unavailable. "
                "4B.4A requires the existing authentication layer "
                "to bind its verified principal to request.state."
            ),
        )

    return actor
