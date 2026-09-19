from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


def data_directory() -> Path:
    override = os.getenv("JACE_DEVICE_AGENT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(
            os.getenv(
                "APPDATA",
                str(Path.home() / "AppData" / "Roaming"),
            )
        )
        return base / "Jace" / "DeviceAgent"

    return Path.home() / ".config" / "jace" / "device-agent"


def config_path() -> Path:
    return data_directory() / "config.json"


@dataclass(slots=True)
class AgentConfig:
    server_url: str
    device_id: str
    device_name: str
    heartbeat_seconds: int = 20
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    allow_insecure_remote: bool = False

    @classmethod
    def load(cls) -> "AgentConfig":
        path = config_path()

        if not path.is_file():
            raise RuntimeError(
                "This computer is not paired with Jace Core. "
                "Run `python -m jace_device_agent pair ...` first."
            )

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self) -> None:
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)

        path = config_path()
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                asdict(self),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp.replace(path)


def normalise_server_url(value: str) -> str:
    value = value.strip().rstrip("/")

    if not value:
        raise ValueError("Jace Core URL cannot be empty.")

    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Jace Core URL must begin with http:// or https://."
        )

    if not parsed.hostname:
        raise ValueError("Jace Core URL must include a hostname.")

    return value


def is_loopback_server(server_url: str) -> bool:
    parsed = urlparse(server_url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def ensure_transport_allowed(
    server_url: str,
    *,
    allow_insecure_remote: bool,
) -> None:
    parsed = urlparse(server_url)

    if parsed.scheme == "https":
        return

    if is_loopback_server(server_url):
        return

    if allow_insecure_remote:
        return

    raise RuntimeError(
        "Refusing to send Device Agent credentials over insecure remote HTTP. "
        "Use HTTPS for a VPS. --allow-insecure-remote exists only for "
        "controlled development networks."
    )


def websocket_url(server_url: str, path: str) -> str:
    parsed = urlparse(server_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    suffix = path if path.startswith("/") else f"/{path}"

    port = f":{parsed.port}" if parsed.port else ""
    host = parsed.hostname or ""

    return f"{scheme}://{host}{port}{suffix}"
