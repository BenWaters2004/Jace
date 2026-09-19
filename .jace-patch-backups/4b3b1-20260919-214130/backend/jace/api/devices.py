from __future__ import annotations

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from jace.config import settings
from jace.database import SessionLocal
from jace.devices.schemas import (
    DeviceHeartbeatRequest,
    DeviceListResponse,
    DevicePairRequest,
    DevicePairResponse,
    DevicePairingCreateRequest,
    DevicePairingResponse,
    DeviceResponse,
    DeviceUpdateRequest,
)
from jace.devices.service import (
    authenticate_device,
    create_pairing,
    device_response,
    get_device,
    heartbeat,
    list_devices,
    pair_device,
    rename_device,
    revoke_device,
)
from jace.db.models import utc_now
from jace.devices.connections import device_connections
from jace.runtime import runtime_events


router = APIRouter(prefix="/devices", tags=["devices"])


def _owner_user_id(request: Request) -> str | None:
    if settings.mode != "server":
        return None
    user_id = getattr(request.state, "auth_user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user_id


def _device_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Device authentication required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "device" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Use Authorization: Device <device-token>.",
        )
    return token.strip()


@router.post("/pairing", response_model=DevicePairingResponse, status_code=status.HTTP_201_CREATED)
async def create_device_pairing(payload: DevicePairingCreateRequest, request: Request):
    owner_user_id = _owner_user_id(request)
    async with SessionLocal() as session:
        grant = await create_pairing(
            session,
            owner_user_id=owner_user_id,
            requested_name=payload.requested_name,
            requested_by_client_id=payload.requested_by_client_id,
        )
    return DevicePairingResponse(
        pairing_id=grant.row.id,
        pairing_code=grant.pairing_code,
        expires_at=grant.row.expires_at,
        requested_name=grant.row.requested_name,
    )


@router.post("/pair", response_model=DevicePairResponse, status_code=status.HTTP_201_CREATED)
async def pair(payload: DevicePairRequest):
    async with SessionLocal() as session:
        try:
            paired = await pair_device(
                session,
                pairing_code=payload.pairing_code,
                name=payload.name,
                hostname=payload.hostname,
                platform=payload.platform,
                os_version=payload.os_version,
                architecture=payload.architecture,
                agent_version=payload.agent_version,
                capabilities=payload.capabilities,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await runtime_events.publish(
        "device.paired",
        device_id=paired.row.id,
        name=paired.row.name,
        hostname=paired.row.hostname,
        platform=paired.row.platform,
    )
    return DevicePairResponse(
        device=device_response(paired.row),
        device_token=paired.device_token,
    )


@router.post("/heartbeat", response_model=DeviceResponse)
async def device_heartbeat(
    payload: DeviceHeartbeatRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    token = _device_token(authorization)

    async with SessionLocal() as session:
        device = await authenticate_device(session, token)
        if device is None:
            raise HTTPException(
                status_code=401,
                detail="Device token is invalid or the device has been revoked.",
            )

        was_online = device_response(device).state == "online"
        device = await heartbeat(
            session,
            device=device,
            agent_version=payload.agent_version,
            platform=payload.platform,
            os_version=payload.os_version,
            architecture=payload.architecture,
            capabilities=payload.capabilities,
            metadata=payload.metadata,
        )

    await runtime_events.publish(
        "device.heartbeat",
        device_id=device.id,
        state="online",
        became_online=not was_online,
        agent_version=device.agent_version,
    )
    return device_response(device)


@router.get("", response_model=DeviceListResponse)
async def devices(request: Request):
    owner_user_id = _owner_user_id(request)
    async with SessionLocal() as session:
        rows = await list_devices(
            session,
            owner_user_id=owner_user_id,
            server_mode=settings.mode == "server",
        )

    responses = [device_response(row) for row in rows]
    return DeviceListResponse(
        devices=responses,
        counts={
            "total": len(responses),
            "online": sum(1 for row in responses if row.state == "online"),
            "offline": sum(1 for row in responses if row.state == "offline"),
            "revoked": sum(1 for row in responses if row.state == "revoked"),
        },
    )


@router.get("/{device_id}", response_model=DeviceResponse)
async def device(device_id: str, request: Request):
    owner_user_id = _owner_user_id(request)
    async with SessionLocal() as session:
        row = await get_device(
            session,
            device_id=device_id,
            owner_user_id=owner_user_id,
            server_mode=settings.mode == "server",
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    return device_response(row)


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: str, payload: DeviceUpdateRequest, request: Request):
    owner_user_id = _owner_user_id(request)
    async with SessionLocal() as session:
        row = await get_device(
            session,
            device_id=device_id,
            owner_user_id=owner_user_id,
            server_mode=settings.mode == "server",
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Device not found.")
        if payload.name is not None:
            try:
                row = await rename_device(session, device=row, name=payload.name)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    await runtime_events.publish("device.updated", device_id=row.id, name=row.name)
    return device_response(row)


@router.delete("/{device_id}", response_model=DeviceResponse)
async def remove_device(device_id: str, request: Request):
    owner_user_id = _owner_user_id(request)
    async with SessionLocal() as session:
        row = await get_device(
            session,
            device_id=device_id,
            owner_user_id=owner_user_id,
            server_mode=settings.mode == "server",
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Device not found.")
        row = await revoke_device(session, device=row)

    await runtime_events.publish("device.revoked", device_id=row.id, name=row.name)
    return device_response(row)

# JACE_4BS5_DEVICE_SOCKET
@router.websocket("/connect")
async def connect_device(websocket: WebSocket):
    # Maintain an authenticated outbound Device Agent connection.
    authorization = websocket.headers.get("Authorization")

    try:
        token = _device_token(authorization)
    except HTTPException:
        await websocket.close(code=4401)
        return

    async with SessionLocal() as session:
        device = await authenticate_device(session, token)

    if device is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await device_connections.register(device.id, websocket)
    connected_event_sent = False

    try:
        while True:
            message = await websocket.receive_json()
            message_type = str(message.get("type", ""))

            if message_type in {"hello", "heartbeat"}:
                payload = message.get("device") or {}

                if not isinstance(payload, dict):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error": "device payload must be an object",
                        }
                    )
                    continue

                async with SessionLocal() as session:
                    current = await authenticate_device(session, token)

                    if current is None:
                        await websocket.close(code=4401)
                        return

                    current = await heartbeat(
                        session,
                        device=current,
                        agent_version=payload.get("agent_version"),
                        platform=payload.get("platform"),
                        os_version=payload.get("os_version"),
                        architecture=payload.get("architecture"),
                        capabilities=payload.get("capabilities"),
                        metadata=payload.get("metadata"),
                    )

                if message_type == "hello" and not connected_event_sent:
                    connected_event_sent = True
                    await runtime_events.publish(
                        "device.connected",
                        device_id=current.id,
                        name=current.name,
                        hostname=current.hostname,
                        platform=current.platform,
                        agent_version=current.agent_version,
                    )
                    await websocket.send_json(
                        {
                            "type": "welcome",
                            "device_id": current.id,
                            "heartbeat_interval_seconds": settings.device_socket_heartbeat_seconds,
                            "server_time": utc_now().isoformat(),
                        }
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat_ack",
                            "device_id": current.id,
                            "server_time": utc_now().isoformat(),
                        }
                    )
                continue

            if message_type == "pong":
                continue

            if message_type == "capability.result":
                # JACE_4BS6_DEVICE_RESULT_ROUTING
                from jace.capabilities.device_broker import device_capability_broker

                handled = await device_capability_broker.resolve_result(
                    device_id=device.id,
                    message=message,
                )

                if not handled:
                    await runtime_events.publish(
                        "device.capability.result.unmatched",
                        device_id=device.id,
                        request_id=message.get("request_id"),
                        status=message.get("status"),
                    )

                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "error": (
                        "Unsupported Device Agent message type: "
                        f"{message_type or '<missing>'}"
                    ),
                }
            )

    except WebSocketDisconnect:
        pass

    finally:
        removed = await device_connections.unregister(device.id, websocket)
        if removed:
            await runtime_events.publish(
                "device.disconnected",
                device_id=device.id,
                name=device.name,
            )

