import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from jace.runtime import runtime_events


router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/snapshot")
async def runtime_snapshot():
    return runtime_events.snapshot()


@router.websocket("/events")
async def runtime_event_stream(websocket: WebSocket):
    await websocket.accept()
    subscriber = await runtime_events.subscribe()

    try:
        await websocket.send_json({"type": "runtime.snapshot", **runtime_events.snapshot()})
        while True:
            try:
                event = await asyncio.wait_for(subscriber.queue.get(), timeout=20.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "runtime.heartbeat", **runtime_events.snapshot()})
    except WebSocketDisconnect:
        pass
    finally:
        await runtime_events.unsubscribe(subscriber)
