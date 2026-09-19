from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Any

import httpx
from websockets.asyncio.client import connect

from jace_device_agent.config import (
    AgentConfig,
    ensure_transport_allowed,
    websocket_url,
)
from jace_device_agent.credentials import credential_store
from jace_device_agent.identity import collect_identity


class DeviceAgentClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run_forever(self) -> None:
        ensure_transport_allowed(
            self.config.server_url,
            allow_insecure_remote=self.config.allow_insecure_remote,
        )

        token = credential_store.get_device_token(
            self.config.device_id
        )

        if not token:
            raise RuntimeError(
                "The paired device credential was not found in the "
                "operating-system credential store. Pair this computer again."
            )

        delay = self.config.reconnect_min_seconds

        while not self._stopping.is_set():
            try:
                await self._run_connection(token)
                delay = self.config.reconnect_min_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopping.is_set():
                    break

                print(
                    f"[device-agent] Connection lost: {exc}"
                )

                jitter = random.uniform(0.0, min(1.0, delay * 0.2))
                wait_seconds = min(
                    self.config.reconnect_max_seconds,
                    delay + jitter,
                )

                print(
                    "[device-agent] Reconnecting in "
                    f"{wait_seconds:.1f}s..."
                )

                try:
                    await asyncio.wait_for(
                        self._stopping.wait(),
                        timeout=wait_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

                delay = min(
                    self.config.reconnect_max_seconds,
                    max(
                        self.config.reconnect_min_seconds,
                        delay * 2,
                    ),
                )

    async def _run_connection(self, token: str) -> None:
        url = websocket_url(
            self.config.server_url,
            "/devices/connect",
        )

        identity = collect_identity(
            device_name=self.config.device_name
        )

        print(
            "[device-agent] Connecting to "
            f"{url} as {identity['name']}..."
        )

        async with connect(
            url,
            additional_headers={
                "Authorization": f"Device {token}",
            },
            open_timeout=15,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=1_000_000,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "device": identity,
                    }
                )
            )

            welcome_raw = await asyncio.wait_for(
                websocket.recv(),
                timeout=15,
            )
            welcome = json.loads(welcome_raw)

            if welcome.get("type") != "welcome":
                raise RuntimeError(
                    "Jace Core did not accept the Device Agent hello."
                )

            heartbeat_seconds = int(
                welcome.get(
                    "heartbeat_interval_seconds",
                    self.config.heartbeat_seconds,
                )
            )
            heartbeat_seconds = max(5, heartbeat_seconds)

            print(
                "[device-agent] Connected. Device ID: "
                f"{self.config.device_id}"
            )

            receiver = asyncio.create_task(
                self._receiver(websocket)
            )
            heartbeat = asyncio.create_task(
                self._heartbeat_loop(
                    websocket,
                    heartbeat_seconds,
                )
            )
            stopper = asyncio.create_task(
                self._stopping.wait()
            )

            done, pending = await asyncio.wait(
                {receiver, heartbeat, stopper},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                *pending,
                return_exceptions=True,
            )

            for task in done:
                if task is stopper:
                    continue

                error = task.exception()
                if error is not None:
                    raise error

    async def _heartbeat_loop(
        self,
        websocket,
        heartbeat_seconds: int,
    ) -> None:
        while not self._stopping.is_set():
            identity = collect_identity(
                device_name=self.config.device_name
            )

            await websocket.send(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "device": identity,
                        "sent_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                )
            )

            await asyncio.sleep(heartbeat_seconds)

    async def _receiver(self, websocket) -> None:
        async for raw in websocket:
            message: dict[str, Any] = json.loads(raw)
            message_type = str(message.get("type", ""))

            if message_type == "heartbeat_ack":
                continue

            if message_type == "ping":
                await websocket.send(
                    json.dumps(
                        {
                            "type": "pong",
                            "request_id": message.get(
                                "request_id"
                            ),
                        }
                    )
                )
                continue

            if message_type == "capability.request":
                # The transport is ready for 4B.S6, but this phase does not
                # execute remote capabilities.
                await websocket.send(
                    json.dumps(
                        {
                            "type": "capability.result",
                            "request_id": message.get(
                                "request_id"
                            ),
                            "status": "unsupported",
                            "error": (
                                "Remote capability execution "
                                "requires Jace Phase 4B.S6."
                            ),
                        }
                    )
                )
                continue

            if message_type == "server.shutdown":
                raise RuntimeError(
                    "Jace Core requested a reconnect."
                )

            print(
                "[device-agent] Ignoring unknown server message: "
                f"{message_type or '<missing type>'}"
            )


async def pair_with_core(
    *,
    server_url: str,
    pairing_code: str,
    device_name: str | None,
    allow_insecure_remote: bool,
) -> AgentConfig:
    ensure_transport_allowed(
        server_url,
        allow_insecure_remote=allow_insecure_remote,
    )

    identity = collect_identity(device_name=device_name)

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=False,
    ) as client:
        response = await client.post(
            f"{server_url}/devices/pair",
            json={
                "pairing_code": pairing_code,
                **identity,
            },
        )

    if response.status_code >= 400:
        try:
            detail = response.json().get(
                "detail",
                response.text,
            )
        except Exception:
            detail = response.text

        raise RuntimeError(
            "Device pairing failed "
            f"({response.status_code}): {detail}"
        )

    body = response.json()
    device = body["device"]
    token = body["device_token"]

    config = AgentConfig(
        server_url=server_url,
        device_id=device["id"],
        device_name=device["name"],
        allow_insecure_remote=allow_insecure_remote,
    )

    credential_store.set_device_token(
        config.device_id,
        token,
    )
    config.save()

    return config
