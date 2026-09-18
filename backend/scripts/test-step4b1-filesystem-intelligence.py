from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from jace.computer.intelligence import (
    detect_project_markers,
    git_summary,
    language_statistics,
    matches_path_filters,
    scan_workspace,
    tree_entries,
)
from jace.tools import ensure_tools_registered
from jace.tools.filesystem_intelligence import (
    FindWorkspacePathsInput,
    PreviewWorkspaceEditInput,
    WorkspaceOverviewInput,
    WorkspaceRecentFilesInput,
    WorkspaceTreeInput,
)
from jace.tools.registry import registry
from jace.tools.routing import route_tool_names


EXPECTED_TOOLS = {
    "workspace_overview",
    "workspace_tree",
    "workspace_recent_files",
    "find_workspace_paths",
    "preview_workspace_edit",
}


def build_fixture(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "App.tsx").write_text(
        "export function App() { return <main>Hello</main>; }\n",
        encoding="utf-8",
    )
    (root / "src" / "utils.ts").write_text(
        "export const answer = 42;\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Fixture\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        '{"scripts":{"dev":"vite"},"dependencies":{"react":"latest"}}',
        encoding="utf-8",
    )
    (root / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n",
        encoding="utf-8",
    )

    # Protected/irrelevant trees must not appear in project-owned scans.
    (root / ".env").write_text(
        "SECRET=should-not-appear\n",
        encoding="utf-8",
    )
    (root / "node_modules" / "pkg").mkdir(
        parents=True,
    )
    (root / "node_modules" / "pkg" / "index.js").write_text(
        "dependency\n",
        encoding="utf-8",
    )
    (root / "dist").mkdir()
    (root / "dist" / "bundle.js").write_text(
        "generated\n",
        encoding="utf-8",
    )

    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text(
        "ref: refs/heads/main\n",
        encoding="utf-8",
    )


def core_tests() -> None:
    with tempfile.TemporaryDirectory(
        prefix="jace-4b1-"
    ) as temp:
        root = Path(temp)
        build_fixture(root)

        scan = scan_workspace(
            root,
            max_files=1000,
        )
        relative_files = {
            str(path.relative_to(root))
            for path in scan.files
        }

        if ".env" in relative_files:
            raise RuntimeError(
                "Sensitive .env file leaked into project scan."
            )

        if any(
            value.startswith("node_modules")
            for value in relative_files
        ):
            raise RuntimeError(
                "node_modules was not pruned."
            )

        if any(
            value.startswith("dist")
            for value in relative_files
        ):
            raise RuntimeError(
                "dist was not pruned."
            )

        if "src/App.tsx" not in {
            value.replace("\\", "/")
            for value in relative_files
        }:
            raise RuntimeError(
                "Project source file was not discovered."
            )

        markers = detect_project_markers(root)

        if "Node / JavaScript" not in markers["project_types"]:
            raise RuntimeError(
                "Node project detection failed."
            )

        if "pnpm" not in markers["package_managers"]:
            raise RuntimeError(
                "pnpm package-manager detection failed."
            )

        git = git_summary(root)

        if (
            not git["is_git_repository"]
            or git["branch"] != "main"
        ):
            raise RuntimeError(
                "Git branch detection failed."
            )

        languages = {
            row["language"]:
                row["files"]
            for row in language_statistics(scan.files)
        }

        if languages.get("TypeScript React") != 1:
            raise RuntimeError(
                "TSX language classification failed."
            )

        if languages.get("TypeScript") != 1:
            raise RuntimeError(
                "TypeScript language classification failed."
            )

        tree, truncated, _ = tree_entries(
            root,
            root,
            max_depth=4,
            max_entries=100,
            include_hidden=False,
        )

        if truncated:
            raise RuntimeError(
                "Small fixture tree was unexpectedly truncated."
            )

        tree_paths = {
            row["path"].replace("\\", "/")
            for row in tree
        }

        if "src/App.tsx" not in tree_paths:
            raise RuntimeError(
                "Workspace tree omitted source file."
            )

        if any(
            value.startswith("node_modules")
            for value in tree_paths
        ):
            raise RuntimeError(
                "Workspace tree exposed node_modules."
            )

        if not matches_path_filters(
            "src/App.tsx",
            pattern="**/*.tsx",
            extension=None,
            language=None,
        ):
            raise RuntimeError(
                "Glob-like path matching failed."
            )

        if not matches_path_filters(
            "src/utils.ts",
            pattern=None,
            extension="ts",
            language="TypeScript",
        ):
            raise RuntimeError(
                "Extension/language path filtering failed."
            )

    print("Bounded project-owned scanning: PASS")
    print("Sensitive/dependency/build pruning: PASS")
    print("Project/package-manager detection: PASS")
    print("Git branch awareness: PASS")
    print("Language classification: PASS")
    print("Recursive tree intelligence: PASS")
    print("Path/glob/language matching: PASS")


def registration_tests() -> None:
    ensure_tools_registered()

    for name in EXPECTED_TOOLS:
        tool = registry.get(name)

        if tool is None:
            raise RuntimeError(
                f"{name} was not registered."
            )

        if (
            tool.risk != "read"
            or tool.default_permission != "ask"
        ):
            raise RuntimeError(
                f"{name} must remain read/Ask."
            )

    # Exercise model schemas as part of the acceptance test.
    WorkspaceOverviewInput(
        workspace_id="0" * 36,
    )
    WorkspaceTreeInput(
        workspace_id="0" * 36,
        max_depth=4,
    )
    WorkspaceRecentFilesInput(
        workspace_id="0" * 36,
        within_days=7,
    )
    FindWorkspacePathsInput(
        workspace_id="0" * 36,
        pattern="**/*.tsx",
    )
    PreviewWorkspaceEditInput(
        workspace_id="0" * 36,
        path="src/App.tsx",
        mode="replace_text",
        old_text="Hello",
        new_text="Hello Jace",
    )

    print("Filesystem intelligence tool registration: PASS")
    print("Filesystem intelligence tools remain read/Ask: PASS")
    print("Filesystem intelligence input schemas: PASS")


def routing_tests() -> None:
    overview = route_tool_names(
        "Understand this project and give me an overview of the stack."
    )

    if "workspace_overview" not in overview:
        raise RuntimeError(
            "Project overview did not route workspace_overview."
        )

    tree = route_tool_names(
        "Show me the repository tree."
    )

    if "workspace_tree" not in tree:
        raise RuntimeError(
            "Repository tree request did not route workspace_tree."
        )

    recent = route_tool_names(
        "Which files were recently modified in this project?"
    )

    if "workspace_recent_files" not in recent:
        raise RuntimeError(
            "Recent-file request did not route workspace_recent_files."
        )

    find = route_tool_names(
        "Find all TypeScript files in this repository."
    )

    if "find_workspace_paths" not in find:
        raise RuntimeError(
            "Typed file discovery did not route find_workspace_paths."
        )

    if "search_workspace_files" in find:
        raise RuntimeError(
            "Filename discovery still routed content search unnecessarily."
        )

    preview = route_tool_names(
        "Preview the diff before editing this file."
    )

    if "preview_workspace_edit" not in preview:
        raise RuntimeError(
            "Edit preview did not route preview_workspace_edit."
        )

    if (
        "write_workspace_file" in preview
        or "replace_workspace_text" in preview
    ):
        raise RuntimeError(
            "Preview request accidentally exposed write/edit tools."
        )

    print("Project overview smart routing: PASS")
    print("Recursive tree smart routing: PASS")
    print("Recent-file smart routing: PASS")
    print("Path discovery smart routing: PASS")
    print("Preview-only routing does not expose write tools: PASS")


def main() -> int:
    print()
    print("Jace Step 4B.1 Filesystem Intelligence test")
    print("===========================================")
    print()

    core_tests()
    registration_tests()
    routing_tests()

    print()
    print(
        "PASS - Step 4B.1 Filesystem Intelligence is operational."
    )
    print(
        "No user files were created, modified, moved, or deleted by this test."
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
