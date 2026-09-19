from __future__ import annotations

import sys

from jace.computer.host_request import (
    extract_explicit_host_path,
    host_auto_tool_call,
)
from jace.tools import ensure_tools_registered
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


EXACT_PROMPT = r"Show me what's in C:\Users\Ben\Downloads."


def exact_prompt_tests() -> None:
    routed = route_tool_names(
        EXACT_PROMPT
    )

    if "list_host_directory" not in routed:
        raise RuntimeError(
            "The exact regression prompt did not route list_host_directory."
        )

    for old_name in (
        "list_computer_workspaces",
        "list_workspace_files",
        "read_workspace_file",
    ):
        if old_name in routed:
            raise RuntimeError(
                f"The exact regression prompt still routed old workspace tool "
                f"{old_name!r}."
            )

    path = extract_explicit_host_path(
        EXACT_PROMPT
    )

    if path != r"C:\Users\Ben\Downloads":
        raise RuntimeError(
            f"Host path extraction was wrong: {path!r}"
        )

    call = host_auto_tool_call(
        routed,
        EXACT_PROMPT,
    )

    expected = {
        "type":
            "function",
        "function": {
            "name":
                "list_host_directory",
            "arguments": {
                "path":
                    r"C:\Users\Ben\Downloads",
            },
        },
    }

    if call != expected:
        raise RuntimeError(
            f"Deterministic host tool call was wrong: {call!r}"
        )

    print("Exact prompt → list_host_directory routing: PASS")
    print("Old workspace handshake removed for explicit host path: PASS")
    print("Exact Windows path extraction: PASS")
    print("Deterministic read-only host call construction: PASS")


def broader_routing_tests() -> None:
    common = route_tool_names(
        "Show me what's in my Downloads."
    )

    if "list_host_directory" not in common:
        raise RuntimeError(
            "Common Downloads listing did not route list_host_directory."
        )

    if extract_explicit_host_path(
        "Show me what's in my Downloads."
    ) != "~/Downloads":
        raise RuntimeError(
            "Common Downloads path resolution failed."
        )

    shell = route_tool_names(
        "Use PowerShell to show the ten most recently modified files "
        "in my Downloads folder."
    )

    if "run_shell_command" not in shell:
        raise RuntimeError(
            "PowerShell request did not route run_shell_command."
        )

    if host_auto_tool_call(
        shell,
        "Use PowerShell to show the ten most recently modified files "
        "in my Downloads folder.",
    ) is not None:
        raise RuntimeError(
            "Shell request unexpectedly synthesized a command."
        )

    print("Common-folder host routing: PASS")
    print("PowerShell routing: PASS")
    print("Shell command is not auto-invented: PASS")


def registration_tests() -> None:
    ensure_tools_registered()

    listing = registry.get(
        "list_host_directory"
    )
    shell = registry.get(
        "run_shell_command"
    )

    if listing is None:
        raise RuntimeError(
            "list_host_directory is not registered."
        )

    if shell is None:
        raise RuntimeError(
            "run_shell_command is not registered."
        )

    if (
        listing.risk != "read"
        or listing.default_permission != "allow"
    ):
        raise RuntimeError(
            "list_host_directory should remain read/Allow."
        )

    if (
        shell.risk != "execute"
        or shell.default_permission != "ask"
    ):
        raise RuntimeError(
            "run_shell_command should remain execute/Ask."
        )

    print("Host directory tool registration: PASS")
    print("Shell execution remains execute/Ask: PASS")


def main() -> int:
    print()
    print("Jace Step 4B.2 v2 Host Execution Fix test")
    print("=========================================")
    print()

    exact_prompt_tests()
    broader_routing_tests()
    registration_tests()

    print()
    print(
        "PASS - the exact host-filesystem regression prompt now routes and "
        "constructs a real local tool call."
    )
    print(
        "No user files were created, modified or deleted and no shell "
        "command was executed by this test."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
