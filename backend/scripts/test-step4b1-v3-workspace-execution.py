from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.agent import _filesystem_auto_tool_name
from jace.tools.base import ToolContext
from jace.tools.filesystem_intelligence import (
    WorkspaceOverviewInput,
    _intelligence_workspace,
    _workspace_matches_message,
    workspace_overview_tool,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


EXACT_PROMPT = (
    "Understand my Jace project and give me an overview of the "
    "stack, languages and structure."
)


def schema_and_matching_tests() -> None:
    ensure_tools_registered()

    definition = registry.get("workspace_overview")
    if definition is None:
        raise RuntimeError("workspace_overview is not registered.")

    schema = definition.input_model.model_json_schema()
    required = set(schema.get("required") or [])

    if "workspace_id" in required:
        raise RuntimeError(
            "workspace_overview still requires workspace_id from the model."
        )

    fake = SimpleNamespace(
        label="Jace project",
        root_path=r"C:\Users\Ben\jace",
    )

    if not _workspace_matches_message(fake, EXACT_PROMPT):
        raise RuntimeError(
            "The exact regression prompt did not match the 'Jace project' workspace."
        )

    if _filesystem_auto_tool_name(["workspace_overview"]) != "workspace_overview":
        raise RuntimeError(
            "workspace_overview was not eligible for deterministic safe-default execution."
        )

    if _filesystem_auto_tool_name([
        "workspace_overview",
        "workspace_tree",
    ]) is not None:
        raise RuntimeError(
            "Deterministic filesystem fallback must not guess between two tools."
        )

    print("Optional workspace_id schema: PASS")
    print("Named workspace matching: PASS")
    print("Deterministic overview fallback selection: PASS")


def routing_tests() -> None:
    routed = route_tool_names(EXACT_PROMPT)

    if "workspace_overview" not in routed:
        raise RuntimeError(
            "The exact regression prompt did not route workspace_overview."
        )

    if "list_computer_workspaces" in routed:
        raise RuntimeError(
            "The exact regression prompt still forces list_computer_workspaces first."
        )

    print("Exact prompt → workspace_overview routing: PASS")
    print("Redundant workspace-list routing removed: PASS")


async def live_workspace_test() -> None:
    async with SessionLocal() as session:
        context = ToolContext(
            session=session,
            conversation_id=None,
            user_message=EXACT_PROMPT,
        )

        workspace = await _intelligence_workspace(
            context,
            None,
        )

        if not workspace.is_active or not workspace.read_enabled:
            raise RuntimeError(
                "Auto-selected workspace is not active/readable."
            )

        result = await workspace_overview_tool(
            WorkspaceOverviewInput(
                max_files=1000,
                recent_limit=3,
                largest_limit=3,
            ),
            context,
        )

    payload = json.loads(result.content)
    selected = payload.get("workspace") or {}

    if selected.get("id") != workspace.id:
        raise RuntimeError(
            "workspace_overview did not use the auto-selected workspace."
        )

    if not isinstance(payload.get("languages"), list):
        raise RuntimeError(
            "workspace_overview did not return language statistics."
        )

    print(
        "Live workspace auto-selection: PASS "
        f"({workspace.label} → {workspace.root_path})"
    )
    print("Live workspace_overview execution: PASS")


async def main() -> int:
    print()
    print("Jace Step 4B.1 v3 Workspace Execution test")
    print("============================================")
    print()

    schema_and_matching_tests()
    routing_tests()
    await live_workspace_test()

    print()
    print(
        "PASS - Step 4B.1 v3 resolves and inspects the configured workspace "
        "without requiring the model to perform a workspace-ID handshake."
    )
    print("No user files were modified by this test.")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print()
        print(f"FAIL - {exc}", file=sys.stderr)
        print()
        raise
