"""No-network smoke checks for Jace Phase 10A Command Center runtime events."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.config import settings  # noqa: E402
from jace.runtime.events import RuntimeEventBus  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


async def check_runtime_bus() -> None:
    bus = RuntimeEventBus()
    subscriber = await bus.subscribe()
    event = await bus.publish("jace.state.changed", state="thinking", reason="smoke")
    received = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
    require(event["type"] == "jace.state.changed", "runtime event type is preserved")
    require(received["state"] == "thinking", "runtime subscriber receives state changes")
    require(bus.snapshot()["state"] == "thinking", "runtime snapshot tracks current Jace state")
    require(received["sequence"] == 1, "runtime event sequence starts deterministically")
    await bus.unsubscribe(subscriber)


async def main() -> int:
    print(f"Jace version: {settings.app_version}")
    require(settings.app_version == "0.10.0-beta.1", "version is 0.10.0-beta.1")
    require(settings.ollama_keep_alive == "-1m", "Ollama keep_alive regression remains fixed")
    await check_runtime_bus()
    print("PASS: Jace Phase 10A Command Center runtime checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
