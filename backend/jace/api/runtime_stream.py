from __future__ import annotations

import asyncio

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from jace.config import settings
from jace.runtime import runtime_events
from jace.runtime.tickets import (
    runtime_stream_tickets,
)


router = APIRouter(
    prefix="/runtime",
    tags=["runtime"],
)


@router.post("/stream-ticket")
async def create_runtime_stream_ticket(
    request: Request,
):
    user_id = getattr(
        request.state,
        "auth_user_id",
        None,
    )

    if (
        settings.mode == "server"
        and settings.auth_enabled
        and not user_id
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    token, expires_at = (
        await runtime_stream_tickets.issue(
            user_id=user_id,
            ttl_seconds=60,
        )
    )

    return {
        "ticket": token,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/events/replay")
async def replay_events(
    after_sequence: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=200,
        ge=1,
    ),
):
    bounded = min(
        limit,
        settings.runtime_event_replay_limit,
    )

    events = await runtime_events.replay(
        after_sequence=after_sequence,
        limit=bounded,
    )

    return {
        "events": events,
        "count": len(events),
        "after_sequence": after_sequence,
        "latest_sequence": (
            runtime_events.snapshot().get(
                "durable_sequence",
                0,
            )
        ),
    }


@router.websocket("/stream")
async def runtime_stream(
    websocket: WebSocket,
):
    after_sequence_raw = (
        websocket.query_params.get(
            "after_sequence",
            "0",
        )
    )

    try:
        after_sequence = max(
            0,
            int(
                after_sequence_raw
            ),
        )
    except ValueError:
        await websocket.close(
            code=4400
        )
        return

    if (
        settings.mode == "server"
        and settings.auth_enabled
    ):
        ticket = (
            await runtime_stream_tickets.consume(
                websocket.query_params.get(
                    "ticket"
                )
            )
        )

        if ticket is None:
            await websocket.close(
                code=4401
            )
            return
    else:
        # Local mode may use a ticket for symmetry, but does not require it.
        supplied = websocket.query_params.get(
            "ticket"
        )

        if supplied:
            await runtime_stream_tickets.consume(
                supplied
            )

    await websocket.accept()

    subscriber = (
        await runtime_events.subscribe()
    )

    try:
        # Subscribe before taking the watermark. Events which arrive while
        # replay is being sent are queued, then de-duplicated by sequence.
        watermark = int(
            runtime_events.snapshot().get(
                "durable_sequence",
                0,
            )
            or 0
        )

        await websocket.send_json(
            {
                "type": "runtime.snapshot",
                **runtime_events.snapshot(),
                "replay_after_sequence": (
                    after_sequence
                ),
            }
        )

        cursor = after_sequence

        while cursor < watermark:
            batch = await runtime_events.replay(
                after_sequence=cursor,
                through_sequence=watermark,
                limit=settings.runtime_event_replay_limit,
            )

            if not batch:
                break

            for event in batch:
                await websocket.send_json(
                    {
                        **event,
                        "replayed": True,
                    }
                )

            cursor = int(
                batch[-1]["sequence"]
            )

        while True:
            try:
                event = await asyncio.wait_for(
                    subscriber.queue.get(),
                    timeout=20.0,
                )

                sequence = event.get(
                    "sequence"
                )

                if (
                    event.get("durable")
                    and isinstance(
                        sequence,
                        int,
                    )
                    and sequence <= watermark
                ):
                    # Already delivered through replay.
                    continue

                await websocket.send_json(
                    event
                )

            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "runtime.heartbeat",
                        **runtime_events.snapshot(),
                    }
                )

    except WebSocketDisconnect:
        pass

    finally:
        await runtime_events.unsubscribe(
            subscriber
        )
