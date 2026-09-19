from __future__ import annotations

import asyncio
import json
import os
import sys

from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.base import ToolContext
from jace.tools.registry import registry
from jace.tools.shell_reliability import (
    ShellCommandInput,
    run_shell_command_tool,
)


def static_tests() -> None:
    import inspect
    import jace.tools.shell_reliability as shell_module

    source = inspect.getsource(
        shell_module
    )

    if "asyncio.create_subprocess_exec" in source:
        raise RuntimeError(
            "v4 shell runner still references asyncio.create_subprocess_exec."
        )

    if "subprocess.Popen" not in source:
        raise RuntimeError(
            "v4 shell runner is not using subprocess.Popen."
        )

    if "asyncio.to_thread" not in source:
        raise RuntimeError(
            "v4 shell runner is not bridging blocking subprocess work via asyncio.to_thread."
        )

    print("No asyncio subprocess dependency: PASS")
    print("subprocess.Popen execution backend: PASS")
    print("Async worker-thread bridge: PASS")


def registration_tests() -> None:
    ensure_tools_registered()

    shell = registry.get(
        "run_shell_command"
    )

    if shell is None:
        raise RuntimeError(
            "run_shell_command is not registered."
        )

    if (
        shell.risk != "execute"
        or shell.default_permission != "ask"
    ):
        raise RuntimeError(
            "run_shell_command must remain execute/Ask."
        )

    if (
        getattr(
            shell.handler,
            "__module__",
            "",
        )
        != "jace.tools.shell_reliability"
    ):
        raise RuntimeError(
            "run_shell_command is not using shell_reliability.py."
        )

    print("Shell tool registration: PASS")
    print("Shell execution remains execute/Ask: PASS")


async def windows_loop_regression_test() -> None:
    if os.name != "nt":
        print(
            "Windows NotImplementedError regression: SKIP "
            "(non-Windows test host)"
        )
        return

    original = asyncio.create_subprocess_exec

    async def broken_asyncio_subprocess(*args, **kwargs):
        raise NotImplementedError(
            "Regression fixture: asyncio subprocess unavailable."
        )

    asyncio.create_subprocess_exec = broken_asyncio_subprocess

    try:
        async with SessionLocal() as session:
            context = ToolContext(
                session=session,
                conversation_id=None,
                user_message=(
                    "Use cmd to print the v4 regression marker."
                ),
            )

            result = await run_shell_command_tool(
                ShellCommandInput(
                    shell="cmd",
                    command="echo jace-v4-shell-ok",
                    timeout_seconds=20,
                ),
                context,
            )
    finally:
        asyncio.create_subprocess_exec = original

    data = json.loads(
        result.content
    )

    if data["exit_code"] != 0:
        raise RuntimeError(
            f"cmd regression fixture failed: {data!r}"
        )

    if "jace-v4-shell-ok" not in data["stdout"].casefold():
        raise RuntimeError(
            "cmd regression fixture stdout was not captured."
        )

    if (
        data.get(
            "execution_backend"
        )
        != "subprocess.Popen via asyncio.to_thread"
    ):
        raise RuntimeError(
            "Unexpected execution backend."
        )

    print(
        "Windows NotImplementedError regression: PASS "
        "(asyncio.create_subprocess_exec was deliberately broken)"
    )


async def powershell_test() -> None:
    if os.name != "nt":
        print(
            "PowerShell execution: SKIP (non-Windows test host)"
        )
        return

    async with SessionLocal() as session:
        context = ToolContext(
            session=session,
            conversation_id=None,
            user_message=(
                "Use PowerShell to print the v4 marker."
            ),
        )

        result = await run_shell_command_tool(
            ShellCommandInput(
                shell="powershell",
                command="Write-Output 'jace-v4-powershell-ok'",
                timeout_seconds=20,
            ),
            context,
        )

    data = json.loads(
        result.content
    )

    if data["exit_code"] != 0:
        raise RuntimeError(
            f"PowerShell regression fixture failed: {data!r}"
        )

    if (
        "jace-v4-powershell-ok"
        not in data["stdout"].casefold()
    ):
        raise RuntimeError(
            "PowerShell stdout did not contain the expected marker."
        )

    if not data.get(
        "resolved_executable"
    ):
        raise RuntimeError(
            "PowerShell result did not report the resolved executable."
        )

    print(
        "PowerShell execution through Popen: PASS "
        f"({data['resolved_executable']})"
    )


async def main() -> int:
    print()
    print(
        "Jace Step 4B.2 v4 Windows Shell Subprocess Fix test"
    )
    print(
        "===================================================="
    )
    print()

    static_tests()
    registration_tests()
    await windows_loop_regression_test()
    await powershell_test()

    print()
    print(
        "PASS - shell execution no longer depends on Windows asyncio "
        "subprocess support."
    )
    print(
        "Only harmless echo/Write-Output commands were executed."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            asyncio.run(
                main()
            )
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
