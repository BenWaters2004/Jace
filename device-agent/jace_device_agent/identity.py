from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from typing import Any

from jace_device_agent import __version__
from jace_device_agent.executor import advertised_execution_capabilities
from jace_device_agent.host_policy import host_policy_registry


from jace_device_agent.config import (
    AgentConfig,
    normalise_process_execution_mode,
)
def discover_capabilities(
    process_runtime_enabled: bool = False,
    terminal_runtime_enabled: bool = False,
    strong_isolation_ready: bool = False,
    require_strong_host_isolation: bool = True,
    process_execution_mode: str = "native",
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
        "host.policy",
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

    # JACE_4B4C3_TRUSTED_HOST_CAPABILITIES
    process_mode = normalise_process_execution_mode(
        process_execution_mode
    )

    process_security_ready = (
        process_mode == "native"
        or (
            process_mode == "sandbox"
            and host_policy_registry.process_isolation_ready
        )
    )

    # Interactive terminals remain on the earlier fail-closed gate until the
    # dedicated native-terminal phase.
    terminal_security_ready = (
        host_policy_registry.terminal_isolation_ready
        or not require_strong_host_isolation
    )

    if process_runtime_enabled and process_security_ready:
        capabilities.add("process.runtime")

    if terminal_runtime_enabled and terminal_security_ready:
        capabilities.add("terminal.runtime")

    if process_mode == "native":
        capabilities.add("host.execution.native")
    elif host_policy_registry.process_isolation_ready:
        capabilities.add("host.execution.sandbox")

    # Preserve Sandbox as an optional locally selectable backend.
    if host_policy_registry.process_isolation_ready:
        capabilities.add("host.isolation.windows-sandbox")

    # JACE_4BS6_DEVICE_EXECUTION_CAPABILITIES
    capabilities.update(advertised_execution_capabilities())
    return sorted(capabilities)


def collect_identity(
    *,
    device_name: str | None = None,
    process_runtime_enabled: bool | None = None,
    terminal_runtime_enabled: bool | None = None,
) -> dict[str, Any]:
    # JACE_4B3B2_RUNTIME_CAPABILITY_CONFIG_FALLBACK
    # The saved local Device Agent config is the authority for
    # high-risk runtime opt-ins when a caller omits these flags.
    if (
        process_runtime_enabled is None
        or terminal_runtime_enabled is None
    ):
        local_config = AgentConfig.load()

        if process_runtime_enabled is None:
            process_runtime_enabled = (
                local_config.allow_process_execution
            )

        if terminal_runtime_enabled is None:
            terminal_runtime_enabled = (
                local_config.allow_terminal_sessions
            )

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
            strong_isolation_ready=host_policy_registry.strong_isolation_ready,
            require_strong_host_isolation=(
                AgentConfig.load().require_strong_host_isolation
            ),
            process_execution_mode=(
                AgentConfig.load().process_execution_mode
            ),
        ),
        "metadata": {
            "host_security": {
                "approved_root_count": (
                    host_policy_registry.status()["approved_root_count"]
                ),
                "process_execution_mode": (
                    AgentConfig.load().process_execution_mode
                ),
                "strong_isolation_backend": (
                    host_policy_registry.strong_isolation_backend
                ),
                "strong_isolation_ready": (
                    host_policy_registry.strong_isolation_ready
                ),
                "process_isolation_ready": (
                    host_policy_registry.process_isolation_ready
                ),
                "terminal_isolation_ready": (
                    host_policy_registry.terminal_isolation_ready
                ),
                "isolated_process_shells": (
                    host_policy_registry.isolated_process_shells
                ),
            },
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
    }
