from __future__ import annotations

from typing import Any


PROTOCOL_VERSION = 1


class DeviceTransportProtocolError(ValueError):
    pass


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_device_hello(
    message: Any,
    *,
    expected_device_id: str,
) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise DeviceTransportProtocolError(
            "Device hello must be a JSON object."
        )

    if message.get("type") != "hello":
        raise DeviceTransportProtocolError(
            "The first Device Agent message must be hello."
        )

    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise DeviceTransportProtocolError(
            "Unsupported Device Agent transport protocol version."
        )

    if _clean(message.get("device_id")) != expected_device_id:
        raise DeviceTransportProtocolError(
            "Device hello identity does not match the authenticated token."
        )

    payload = message.get("device")
    if not isinstance(payload, dict):
        raise DeviceTransportProtocolError(
            "Device hello payload must contain a device object."
        )

    return payload


def validate_device_heartbeat(
    message: Any,
    *,
    expected_device_id: str,
    expected_connection_id: str,
) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise DeviceTransportProtocolError(
            "Device heartbeat must be a JSON object."
        )

    if message.get("type") != "heartbeat":
        raise DeviceTransportProtocolError(
            "Expected a Device Agent heartbeat."
        )

    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise DeviceTransportProtocolError(
            "Unsupported Device Agent transport protocol version."
        )

    if _clean(message.get("device_id")) != expected_device_id:
        raise DeviceTransportProtocolError(
            "Heartbeat device identity does not match the session."
        )

    if _clean(message.get("connection_id")) != expected_connection_id:
        raise DeviceTransportProtocolError(
            "Heartbeat connection identity does not match the session."
        )

    payload = message.get("device")
    if not isinstance(payload, dict):
        raise DeviceTransportProtocolError(
            "Device heartbeat payload must contain a device object."
        )

    return payload
