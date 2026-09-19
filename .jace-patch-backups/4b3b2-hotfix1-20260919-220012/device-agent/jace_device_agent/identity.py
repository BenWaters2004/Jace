from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from typing import Any

from jace_device_agent import __version__
from jace_device_agent.executor import advertised_execution_capabilities


def discover_capabilities(
    process_runtime_enabled: bool = False,
    terminal_runtime_enabled: bool = False,
) -> list[str]:
    """Advertise host capabilities that later phases may broker.

    4B.S5 does not execute these capabilities remotely yet.
    """

    capabilities = {
        "device.heartbeat",
        "system.info",
        "filesystem.local",
        "process.local",
        "applications.local",
    }

    system = platform.system().lower()

    if system == "windows":
        capabilities.add("screen.local")

        if shutil.which("powershell.exe") or shutil.which("powershell"):
            capabilities.add("terminal.powershell")

        if shutil.which("cmd.exe") or shutil.which("cmd"):
            capabilities.add("terminal.cmd")

        if shutil.which("wsl.exe") or shutil.which("wsl"):
            capabilities.add("terminal.wsl")

    else:
        if shutil.which("bash"):
            capabilities.add("terminal.bash")

    if shutil.which("ollama"):
        capabilities.add("model.ollama")

    # JACE_4B3B1_PROCESS_RUNTIME_CAPABILITY
    if process_runtime_enabled:
        capabilities.add("process.runtime")

    # JACE_4B3B2_TERMINAL_RUNTIME_CAPABILITY
    if terminal_runtime_enabled:
        capabilities.add("terminal.runtime")

    # JACE_4BS6_DEVICE_EXECUTION_CAPABILITIES
    capabilities.update(advertised_execution_capabilities())
    return sorted(capabilities)


def collect_identity(
    *,
    device_name: str | None = None,
    process_runtime_enabled: bool = False,
    terminal_runtime_enabled: bool = False,
) -> dict[str, Any]:
    hostname = socket.gethostname().strip() or "unknown-device"
    name = (device_name or hostname).strip()

    return {
        "name": name,
        "hostname": hostname,
        "platform": platform.system().lower() or os.name,
        "os_version": platform.platform(),
        "architecture": platform.machine() or None,
        "agent_version": __version__,
        "capabilities": discover_capabilities(
            process_runtime_enabled=process_runtime_enabled,
            terminal_runtime_enabled=terminal_runtime_enabled,
        ),
        "metadata": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
    }
