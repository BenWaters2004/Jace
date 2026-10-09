from __future__ import annotations

import asyncio

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
from jace.devices.transport import (
    PROTOCOL_VERSION,
    DeviceTransportProtocolError,
    validate_device_heartbeat,
    validate_device_hello,
)
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

    await device_connections.disconnect(
        row.id,
        code=4003,
        reason="Device revoked by its owner.",
    )

    await runtime_events.publish("device.revoked", device_id=row.id, name=row.name)
    return device_response(row)

# JACE_4BS5_DEVICE_SOCKET
# JACE_4B4B_SECURE_REMOTE_DEVICE_TRANSPORT
@router.websocket("/connect")
async def connect_device(websocket: WebSocket):
    """Accept one authenticated, owner-bound Device Agent transport session."""

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

    if settings.mode == "server" and not device.owner_user_id:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    connection = None

    try:
        try:
            hello = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=settings.device_socket_hello_timeout_seconds,
            )
        except asyncio.TimeoutError:
            await websocket.close(
                code=4408,
                reason="Device Agent hello timed out.",
            )
            return

        try:
            payload = validate_device_hello(
                hello,
                expected_device_id=device.id,
            )
        except DeviceTransportProtocolError as exc:
            await websocket.send_json({"type": "error", "error": str(exc)})
            await websocket.close(code=4400, reason=str(exc)[:120])
            return

        async with SessionLocal() as session:
            current = await authenticate_device(session, token)
            if current is None:
                await websocket.close(code=4401)
                return

            if (
                settings.mode == "server"
                and current.owner_user_id != device.owner_user_id
            ):
                await websocket.close(code=4403)
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

        connection = await device_connections.register(
            device_id=current.id,
            owner_user_id=current.owner_user_id,
            websocket=websocket,
        )

        await runtime_events.publish(
            "device.connected",
            device_id=current.id,
            owner_user_id=current.owner_user_id,
            connection_id=connection.connection_id,
            name=current.name,
            hostname=current.hostname,
            platform=current.platform,
            agent_version=current.agent_version,
            protocol_version=PROTOCOL_VERSION,
        )

        sent = await device_connections.send(
            current.id,
            {
                "type": "welcome",
                "protocol_version": PROTOCOL_VERSION,
                "device_id": current.id,
                "connection_id": connection.connection_id,
                "heartbeat_interval_seconds": settings.device_socket_heartbeat_seconds,
                "server_time": utc_now().isoformat(),
            },
            owner_user_id=current.owner_user_id,
        )
        if not sent:
            return

        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                await device_connections.send(
                    current.id,
                    {
                        "type": "error",
                        "error": "Device Agent message must be a JSON object.",
                    },
                    owner_user_id=current.owner_user_id,
                )
                continue

            message_type = str(message.get("type", ""))

            if message_type == "hello":
                await websocket.close(
                    code=4400,
                    reason="Device hello may only be sent once.",
                )
                return

            if message_type == "heartbeat":
                try:
                    payload = validate_device_heartbeat(
                        message,
                        expected_device_id=current.id,
                        expected_connection_id=connection.connection_id,
                    )
                except DeviceTransportProtocolError as exc:
                    await websocket.close(code=4400, reason=str(exc)[:120])
                    return

                async with SessionLocal() as session:
                    refreshed = await authenticate_device(session, token)
                    if refreshed is None:
                        await websocket.close(
                            code=4401,
                            reason="Device credential revoked or invalid.",
                        )
                        return

                    if (
                        settings.mode == "server"
                        and refreshed.owner_user_id != current.owner_user_id
                    ):
                        await websocket.close(
                            code=4403,
                            reason="Device ownership changed.",
                        )
                        return

                    current = await heartbeat(
                        session,
                        device=refreshed,
                        agent_version=payload.get("agent_version"),
                        platform=payload.get("platform"),
                        os_version=payload.get("os_version"),
                        architecture=payload.get("architecture"),
                        capabilities=payload.get("capabilities"),
                        metadata=payload.get("metadata"),
                    )

                await device_connections.send(
                    current.id,
                    {
                        "type": "heartbeat_ack",
                        "protocol_version": PROTOCOL_VERSION,
                        "device_id": current.id,
                        "connection_id": connection.connection_id,
                        "server_time": utc_now().isoformat(),
                    },
                    owner_user_id=current.owner_user_id,
                )
                continue

            if message_type == "pong":
                continue

            if message_type.startswith("terminal."):
                from jace.terminal_runtime import terminal_runtime

                handled = await terminal_runtime.handle_device_message(
                    device_id=current.id,
                    message=message,
                )
                if not handled:
                    await runtime_events.publish(
                        "device.terminal.message.unmatched",
                        device_id=current.id,
                        terminal_id=message.get("terminal_id"),
                        message_type=message_type,
                    )
                continue

            if message_type.startswith("process."):
                from jace.process_runtime import process_runtime

                handled = await process_runtime.handle_device_message(
                    device_id=current.id,
                    message=message,
                )
                if not handled:
                    await runtime_events.publish(
                        "device.process.message.unmatched",
                        device_id=current.id,
                        process_id=message.get("process_id"),
                        message_type=message_type,
                    )
                continue

            if message_type == "capability.result":
                from jace.capabilities.device_broker import device_capability_broker

                handled = await device_capability_broker.resolve_result(
                    device_id=current.id,
                    message=message,
                )
                if not handled:
                    await runtime_events.publish(
                        "device.capability.result.unmatched",
                        device_id=current.id,
                        request_id=message.get("request_id"),
                        status=message.get("status"),
                    )
                continue

            await device_connections.send(
                current.id,
                {
                    "type": "error",
                    "error": (
                        "Unsupported Device Agent message type: "
                        f"{message_type or '<missing>'}"
                    ),
                },
                owner_user_id=current.owner_user_id,
            )

    except WebSocketDisconnect:
        pass

    finally:
        if connection is not None:
            removed = await device_connections.unregister(
                device.id,
                websocket,
            )
            if removed:
                await runtime_events.publish(
                    "device.disconnected",
                    device_id=device.id,
                    owner_user_id=device.owner_user_id,
                    connection_id=connection.connection_id,
                    name=device.name,
                )
