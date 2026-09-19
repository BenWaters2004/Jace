from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.base import ToolContext
from jace.tools.host_computer import (
    HostDeleteInput,
    HostListInput,
    HostMoveInput,
    HostReadInput,
    HostReplaceInput,
    HostWriteInput,
    ShellCommandInput,
    delete_host_path_tool,
    list_host_directory_tool,
    move_host_path_tool,
    read_host_file_tool,
    replace_host_text_tool,
    run_shell_command_tool,
    write_host_file_tool,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


HOST_TOOLS = {
    "computer_locations",
    "list_host_directory",
    "read_host_file",
    "host_file_info",
    "search_host_files",
    "write_host_file",
    "replace_host_text",
    "move_host_path",
    "delete_host_path",
    "run_shell_command",
}


def registration_tests() -> None:
    ensure_tools_registered()

    for name in HOST_TOOLS:
        tool = registry.get(name)
        if tool is None:
            raise RuntimeError(f"{name} was not registered.")

    shell = registry.get("run_shell_command")
    if shell is None:
        raise RuntimeError("run_shell_command was not registered.")

    if shell.risk != "execute" or shell.default_permission != "ask":
        raise RuntimeError(
            "Shell execution must remain execute/Ask."
        )

    for name in {
        "computer_locations",
        "list_host_directory",
        "read_host_file",
        "host_file_info",
        "search_host_files",
    }:
        tool = registry.get(name)
        if tool is None or tool.risk != "read":
            raise RuntimeError(
                f"{name} should be a host read tool."
            )

    for name in {
        "write_host_file",
        "replace_host_text",
        "move_host_path",
        "delete_host_path",
    }:
        tool = registry.get(name)
        if (
            tool is None
            or tool.risk != "write"
            or tool.default_permission != "ask"
        ):
            raise RuntimeError(
                f"{name} should remain write/Ask."
            )

    print("Full host tool registration: PASS")
    print("Shell execution remains execute/Ask: PASS")
    print("Host writes remain Ask-gated: PASS")


def routing_tests() -> None:
    read = route_tool_names(
        r"Read the file C:\Users\Ben\Downloads\example.txt"
    )
    if "read_host_file" not in read:
        raise RuntimeError(
            "Explicit absolute file request did not route read_host_file."
        )

    shell = route_tool_names(
        "Run this PowerShell command for me."
    )
    if "run_shell_command" not in shell:
        raise RuntimeError(
            "PowerShell request did not route run_shell_command."
        )

    drives = route_tool_names(
        "Show my drives."
    )
    if "computer_locations" not in drives:
        raise RuntimeError(
            "Drive discovery did not route computer_locations."
        )

    print("Absolute host path routing: PASS")
    print("PowerShell/cmd routing: PASS")
    print("Drive discovery routing: PASS")


async def host_file_tests() -> None:
    with tempfile.TemporaryDirectory(
        prefix="jace-4b2-host-"
    ) as temp:
        root = Path(temp).resolve()
        secret = root / ".env"
        secret.write_text(
            "DEMO_SECRET=local-test-only\n",
            encoding="utf-8",
        )

        async with SessionLocal() as session:
            context = ToolContext(
                session=session,
                conversation_id=None,
                user_message="4B.2 acceptance test",
            )

            listing = await list_host_directory_tool(
                HostListInput(
                    path=str(root),
                ),
                context,
            )
            listing_data = json.loads(listing.content)

            names = {
                item["name"]
                for item in listing_data["entries"]
            }
            if ".env" not in names:
                raise RuntimeError(
                    "Host directory listing unexpectedly hid .env."
                )

            read = await read_host_file_tool(
                HostReadInput(
                    path=str(secret),
                ),
                context,
            )
            read_data = json.loads(read.content)

            if "DEMO_SECRET=local-test-only" not in read_data["content"]:
                raise RuntimeError(
                    "Host read tool could not read the temp .env file."
                )

            target = root / "created.txt"

            write = await write_host_file_tool(
                HostWriteInput(
                    path=str(target),
                    content="hello world\n",
                ),
                context,
            )
            write_data = json.loads(write.content)

            replace = await replace_host_text_tool(
                HostReplaceInput(
                    path=str(target),
                    old_text="world",
                    new_text="Jace",
                    expected_sha256=write_data["sha256"],
                ),
                context,
            )
            replace_data = json.loads(replace.content)

            if replace_data["status"] != "updated":
                raise RuntimeError("Host replace did not update the temp file.")

            moved = root / "moved.txt"

            await move_host_path_tool(
                HostMoveInput(
                    source=str(target),
                    destination=str(moved),
                ),
                context,
            )

            if not moved.exists():
                raise RuntimeError("Host move did not move the temp file.")

            await delete_host_path_tool(
                HostDeleteInput(
                    path=str(moved),
                ),
                context,
            )

            if moved.exists():
                raise RuntimeError("Host delete did not delete the temp file.")

    print("Host filesystem access outside workspace model: PASS")
    print("Sensitive-style .env host read: PASS")
    print("Host write/edit/move/delete primitives: PASS")


async def shell_test() -> None:
    if os.name != "nt":
        print("Windows cmd execution fixture: SKIP (non-Windows test host)")
        return

    with tempfile.TemporaryDirectory(
        prefix="jace-4b2-shell-"
    ) as temp:
        root = Path(temp).resolve()

        async with SessionLocal() as session:
            context = ToolContext(
                session=session,
                conversation_id=None,
                user_message="Run the safe cmd acceptance fixture.",
            )

            result = await run_shell_command_tool(
                ShellCommandInput(
                    shell="cmd",
                    command="echo shell-ok",
                    cwd=str(root),
                    timeout_seconds=10,
                ),
                context,
            )

            data = json.loads(result.content)

            if data["exit_code"] != 0:
                raise RuntimeError(
                    "Safe cmd acceptance fixture returned non-zero."
                )

            if "shell-ok" not in data["stdout"].casefold():
                raise RuntimeError(
                    "cmd stdout was not captured."
                )

    print("Windows cmd arbitrary-shell execution: PASS")


async def main() -> int:
    print()
    print("Jace Step 4B.2 Full Computer Access test")
    print("========================================")
    print()

    registration_tests()
    routing_tests()
    await host_file_tests()
    await shell_test()

    print()
    print(
        "PASS - Step 4B.2 Full Computer Access is operational."
    )
    print(
        "Tests used only temporary files/commands and did not modify a "
        "configured project."
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
