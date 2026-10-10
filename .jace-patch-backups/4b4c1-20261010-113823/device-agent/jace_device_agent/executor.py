from __future__ import annotations

import asyncio
import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from jace_device_agent import __version__


SUPPORTED_CAPABILITIES = {
    "system.info",
    "process.list",
    "filesystem.list",
}


def advertised_execution_capabilities() -> list[str]:
    return sorted(SUPPORTED_CAPABILITIES)


def _evidence(capability: str, started_at: datetime) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc)
    return {
        "capability": capability,
        "hostname": socket.gethostname(),
        "agent_version": __version__,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round(
            (finished_at - started_at).total_seconds() * 1000,
            3,
        ),
        "read_only": True,
    }


def _system_info() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "platform": platform.system().lower(),
        "platform_detail": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "agent_version": __version__,
        "cpu_logical_count": psutil.cpu_count(logical=True),
        "cpu_physical_count": psutil.cpu_count(logical=False),
        "memory_total_bytes": int(memory.total),
        "memory_available_bytes": int(memory.available),
        "boot_time": datetime.fromtimestamp(
            psutil.boot_time(),
            timezone.utc,
        ).isoformat(),
    }


def _process_list(parameters: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = int(parameters.get("limit", 100))
    except (TypeError, ValueError) as exc:
        raise ValueError("process.list limit must be an integer.") from exc

    limit = max(1, min(limit, 500))
    rows: list[dict[str, Any]] = []

    for process in psutil.process_iter(
        attrs=["pid", "name", "username", "status", "memory_info"]
    ):
        if len(rows) >= limit:
            break

        try:
            info = process.info
            memory_info = info.get("memory_info")
            rows.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "username": info.get("username"),
                    "status": info.get("status"),
                    "rss_bytes": (
                        int(memory_info.rss)
                        if memory_info is not None
                        else None
                    ),
                }
            )
        except (
            psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
        ):
            continue

    return {"processes": rows, "count": len(rows), "limit": limit}


def _filesystem_list(parameters: dict[str, Any]) -> dict[str, Any]:
    raw_path = parameters.get("path")
    if not isinstance(raw_path, str):
        raise ValueError("filesystem.list requires a string 'path'.")

    path = Path(
        os.path.expandvars(os.path.expanduser(raw_path))
    ).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Directory does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    try:
        limit = int(parameters.get("limit", 200))
    except (TypeError, ValueError) as exc:
        raise ValueError("filesystem.list limit must be an integer.") from exc

    limit = max(1, min(limit, 500))
    entries: list[dict[str, Any]] = []

    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if len(entries) >= limit:
            break

        try:
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "kind": (
                        "directory"
                        if child.is_dir()
                        else "file"
                        if child.is_file()
                        else "other"
                    ),
                    "size_bytes": int(stat.st_size) if child.is_file() else None,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime,
                        timezone.utc,
                    ).isoformat(),
                }
            )
        except (OSError, PermissionError):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "kind": "unavailable",
                    "size_bytes": None,
                    "modified_at": None,
                }
            )

    return {
        "path": str(path),
        "entries": entries,
        "count": len(entries),
        "limit": limit,
    }


async def execute_capability(
    capability: str,
    parameters: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    if capability not in SUPPORTED_CAPABILITIES:
        raise PermissionError(
            f"Device capability '{capability}' is not enabled."
        )

    started_at = datetime.now(timezone.utc)

    if capability == "system.info":
        result = await asyncio.to_thread(_system_info)
    elif capability == "process.list":
        result = await asyncio.to_thread(_process_list, parameters)
    elif capability == "filesystem.list":
        result = await asyncio.to_thread(_filesystem_list, parameters)
    else:
        raise PermissionError(f"Unsupported device capability: {capability}")

    return result, _evidence(capability, started_at)
