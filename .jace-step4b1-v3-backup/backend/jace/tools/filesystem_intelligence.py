from __future__ import annotations

# JACE_STEP4B1_FILESYSTEM_INTELLIGENCE_TOOLS

from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from jace.computer.intelligence import (
    detect_project_markers,
    git_summary,
    language_for_path,
    language_statistics,
    matches_path_filters,
    scan_workspace,
    tree_entries,
    utc_iso_from_timestamp,
)
from jace.computer.security import relative_display
from jace.config import settings
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.computer import (
    _read_text,
    _resolve,
    _sha256,
    _workspace_for_tool,
)
from jace.tools.registry import registry


def _bounded_scan_limit(
    requested: int,
) -> int:
    # Intelligence scans may inspect more filenames/metadata than content
    # search, but remain bounded relative to the existing computer policy.
    return min(
        requested,
        max(
            settings.computer_search_max_files,
            10_000,
        ),
    )


class WorkspaceOverviewInput(BaseModel):
    workspace_id: str = Field(
        min_length=36,
        max_length=36,
    )
    max_files: int = Field(
        default=5000,
        ge=100,
        le=10_000,
    )
    recent_limit: int = Field(
        default=10,
        ge=0,
        le=50,
    )
    largest_limit: int = Field(
        default=10,
        ge=0,
        le=50,
    )


async def workspace_overview_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        WorkspaceOverviewInput,
    )

    workspace = await _workspace_for_tool(
        context,
        payload.workspace_id,
    )
    root = Path(
        workspace.root_path
    ).resolve(
        strict=True
    )

    scan = scan_workspace(
        root,
        max_files=_bounded_scan_limit(
            payload.max_files
        ),
        include_hidden=False,
    )

    total_bytes = 0
    file_rows: list[
        tuple[
            Path,
            int,
            float,
        ]
    ] = []

    for path in scan.files:
        try:
            stat = path.stat()
        except OSError:
            continue

        total_bytes += stat.st_size
        file_rows.append(
            (
                path,
                stat.st_size,
                stat.st_mtime,
            )
        )

    recent = [
        {
            "path":
                relative_display(
                    root,
                    path,
                ),
            "modified":
                utc_iso_from_timestamp(
                    modified
                ),
            "size":
                size,
            "language":
                language_for_path(
                    path
                ),
        }
        for path, size, modified
        in sorted(
            file_rows,
            key=lambda item:
                item[
                    2
                ],
            reverse=True,
        )[
            :payload.recent_limit
        ]
    ]

    largest = [
        {
            "path":
                relative_display(
                    root,
                    path,
                ),
            "size":
                size,
            "modified":
                utc_iso_from_timestamp(
                    modified
                ),
            "language":
                language_for_path(
                    path
                ),
        }
        for path, size, modified
        in sorted(
            file_rows,
            key=lambda item:
                item[
                    1
                ],
            reverse=True,
        )[
            :payload.largest_limit
        ]
    ]

    top_level, top_truncated, top_pruned = tree_entries(
        root,
        root,
        max_depth=1,
        max_entries=120,
        include_hidden=False,
    )

    project = detect_project_markers(
        root
    )
    git = git_summary(
        root
    )
    languages = language_statistics(
        scan.files
    )

    result = {
        "workspace": {
            "id":
                workspace.id,
            "label":
                workspace.label,
            "root_path":
                workspace.root_path,
            "read_enabled":
                workspace.read_enabled,
            "write_enabled":
                workspace.write_enabled,
        },
        "project":
            project,
        "git":
            git,
        "statistics": {
            "files":
                len(
                    scan.files
                ),
            "directories":
                len(
                    scan.directories
                ),
            "bytes":
                total_bytes,
            "files_scanned":
                scan.files_scanned,
            "directories_pruned":
                scan.directories_pruned,
            "scan_limit_reached":
                scan.scan_limit_reached,
        },
        "languages":
            languages,
        "top_level":
            top_level,
        "top_level_truncated":
            top_truncated,
        "top_level_pruned":
            top_pruned,
        "recent_files":
            recent,
        "largest_files":
            largest,
    }

    project_types = (
        ", ".join(
            project[
                "project_types"
            ]
        )
        or "unclassified project"
    )

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Profiled {workspace.label}: "
            f"{len(scan.files)} project-owned files, "
            f"{project_types}."
        ),
        metadata={
            "workspace_id":
                workspace.id,
            "files_scanned":
                scan.files_scanned,
            "scan_limit_reached":
                scan.scan_limit_reached,
        },
    )


class WorkspaceTreeInput(BaseModel):
    workspace_id: str = Field(
        min_length=36,
        max_length=36,
    )
    path: str = Field(
        default=".",
        max_length=800,
    )
    max_depth: int = Field(
        default=4,
        ge=1,
        le=10,
    )
    max_entries: int = Field(
        default=300,
        ge=1,
        le=1000,
    )
    include_hidden: bool = False
    files_only: bool = False


async def workspace_tree_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        WorkspaceTreeInput,
    )

    workspace = await _workspace_for_tool(
        context,
        payload.workspace_id,
    )
    root, base = _resolve(
        workspace,
        payload.path,
        must_exist=True,
    )

    if not base.is_dir():
        raise ToolError(
            "Workspace tree path must be a directory."
        )

    entries, truncated, pruned = tree_entries(
        root,
        base,
        max_depth=payload.max_depth,
        max_entries=payload.max_entries,
        include_hidden=payload.include_hidden,
        files_only=payload.files_only,
    )

    result = {
        "workspace":
            workspace.label,
        "path":
            relative_display(
                root,
                base,
            ),
        "max_depth":
            payload.max_depth,
        "entries":
            entries,
        "truncated":
            truncated,
        "directories_pruned":
            pruned,
    }

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Mapped {len(entries)} workspace tree "
            f"entr{'y' if len(entries) == 1 else 'ies'} "
            f"in {workspace.label}:{relative_display(root, base)}."
        ),
        metadata={
            "workspace_id":
                workspace.id,
            "truncated":
                truncated,
        },
    )


class WorkspaceRecentFilesInput(BaseModel):
    workspace_id: str = Field(
        min_length=36,
        max_length=36,
    )
    path: str = Field(
        default=".",
        max_length=800,
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
    )
    within_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
    )
    extension: str | None = Field(
        default=None,
        max_length=30,
    )
    language: str | None = Field(
        default=None,
        max_length=80,
    )
    max_files: int = Field(
        default=5000,
        ge=100,
        le=10_000,
    )


async def workspace_recent_files_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        WorkspaceRecentFilesInput,
    )

    workspace = await _workspace_for_tool(
        context,
        payload.workspace_id,
    )
    root, base = _resolve(
        workspace,
        payload.path,
        must_exist=True,
    )

    if not base.is_dir():
        raise ToolError(
            "Recent-file path must be a directory."
        )

    scan = scan_workspace(
        root,
        base=base,
        max_files=_bounded_scan_limit(
            payload.max_files
        ),
        include_hidden=False,
    )

    threshold: float | None = None

    if payload.within_days is not None:
        threshold = (
            datetime.now(
                timezone.utc
            )
            - timedelta(
                days=payload.within_days
            )
        ).timestamp()

    rows = []

    for path in scan.files:
        relative = relative_display(
            root,
            path,
        )

        if not matches_path_filters(
            relative,
            pattern=None,
            extension=payload.extension,
            language=payload.language,
        ):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        if (
            threshold is not None
            and stat.st_mtime
            < threshold
        ):
            continue

        rows.append(
            {
                "path":
                    relative,
                "size":
                    stat.st_size,
                "modified":
                    utc_iso_from_timestamp(
                        stat.st_mtime
                    ),
                "language":
                    language_for_path(
                        path
                    ),
            }
        )

    rows.sort(
        key=lambda item:
            item[
                "modified"
            ],
        reverse=True,
    )

    rows = rows[
        :payload.limit
    ]

    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace":
                    workspace.label,
                "path":
                    relative_display(
                        root,
                        base,
                    ),
                "recent_files":
                    rows,
                "files_scanned":
                    scan.files_scanned,
                "directories_pruned":
                    scan.directories_pruned,
                "scan_limit_reached":
                    scan.scan_limit_reached,
            },
            ensure_ascii=False,
        ),
        display=(
            f"Found {len(rows)} recent project file"
            f"{'' if len(rows) == 1 else 's'} in {workspace.label}."
        ),
        metadata={
            "workspace_id":
                workspace.id,
            "scan_limit_reached":
                scan.scan_limit_reached,
        },
    )


class FindWorkspacePathsInput(BaseModel):
    workspace_id: str = Field(
        min_length=36,
        max_length=36,
    )
    path: str = Field(
        default=".",
        max_length=800,
    )
    pattern: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Glob-like path/name pattern such as **/*.tsx, *Controller.php, "
            "README*, or *.env.example."
        ),
    )
    extension: str | None = Field(
        default=None,
        max_length=30,
    )
    language: str | None = Field(
        default=None,
        max_length=80,
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
    )
    max_files: int = Field(
        default=5000,
        ge=100,
        le=10_000,
    )

    @model_validator(mode="after")
    def require_filter(self):
        if not (
            self.pattern
            or self.extension
            or self.language
        ):
            raise ValueError(
                "Provide pattern, extension, or language."
            )

        return self


async def find_workspace_paths_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        FindWorkspacePathsInput,
    )

    workspace = await _workspace_for_tool(
        context,
        payload.workspace_id,
    )
    root, base = _resolve(
        workspace,
        payload.path,
        must_exist=True,
    )

    if not base.is_dir():
        raise ToolError(
            "Path discovery must start from a directory."
        )

    scan = scan_workspace(
        root,
        base=base,
        max_files=_bounded_scan_limit(
            payload.max_files
        ),
        include_hidden=False,
    )

    matches = []

    for path in scan.files:
        relative = relative_display(
            root,
            path,
        )

        if not matches_path_filters(
            relative,
            pattern=payload.pattern,
            extension=payload.extension,
            language=payload.language,
        ):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        matches.append(
            {
                "path":
                    relative,
                "size":
                    stat.st_size,
                "modified":
                    utc_iso_from_timestamp(
                        stat.st_mtime
                    ),
                "language":
                    language_for_path(
                        path
                    ),
            }
        )

        if len(
            matches
        ) >= payload.max_results:
            break

    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace":
                    workspace.label,
                "path":
                    relative_display(
                        root,
                        base,
                    ),
                "pattern":
                    payload.pattern,
                "extension":
                    payload.extension,
                "language":
                    payload.language,
                "matches":
                    matches,
                "files_scanned":
                    scan.files_scanned,
                "directories_pruned":
                    scan.directories_pruned,
                "scan_limit_reached":
                    scan.scan_limit_reached,
            },
            ensure_ascii=False,
        ),
        display=(
            f"Found {len(matches)} matching project path"
            f"{'' if len(matches) == 1 else 's'} in {workspace.label}."
        ),
        metadata={
            "workspace_id":
                workspace.id,
            "scan_limit_reached":
                scan.scan_limit_reached,
        },
    )


class PreviewWorkspaceEditInput(BaseModel):
    workspace_id: str = Field(
        min_length=36,
        max_length=36,
    )
    path: str = Field(
        min_length=1,
        max_length=800,
    )
    mode: Literal[
        "replace_text",
        "full_content",
    ] = "replace_text"
    old_text: str | None = Field(
        default=None,
        max_length=30_000,
    )
    new_text: str | None = Field(
        default=None,
        max_length=200_000,
    )
    expected_occurrences: int = Field(
        default=1,
        ge=1,
        le=50,
    )

    @model_validator(mode="after")
    def validate_preview(self):
        if self.mode == "replace_text":
            if (
                not self.old_text
                or self.new_text is None
            ):
                raise ValueError(
                    "replace_text requires old_text and new_text."
                )
        elif self.new_text is None:
            raise ValueError(
                "full_content requires new_text."
            )

        return self


async def preview_workspace_edit_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(
        payload,
        PreviewWorkspaceEditInput,
    )

    workspace = await _workspace_for_tool(
        context,
        payload.workspace_id,
    )
    root, path = _resolve(
        workspace,
        payload.path,
        must_exist=True,
    )

    if not path.is_file():
        raise ToolError(
            "Edit preview path must be a file."
        )

    current = _read_text(
        path
    )
    current_sha = _sha256(
        path
    )

    if payload.mode == "replace_text":
        assert payload.old_text is not None
        assert payload.new_text is not None

        count = current.count(
            payload.old_text
        )

        if count != payload.expected_occurrences:
            raise ToolError(
                f"Expected {payload.expected_occurrences} matching occurrence(s), "
                f"but found {count}. No preview was generated."
            )

        proposed = current.replace(
            payload.old_text,
            payload.new_text,
        )
        replacements = count
    else:
        assert payload.new_text is not None
        proposed = payload.new_text
        replacements = None

    if len(
        proposed
    ) > settings.computer_max_write_chars:
        raise ToolError(
            "Proposed file would exceed the configured write limit."
        )

    proposed_sha = hashlib.sha256(
        proposed.encode(
            "utf-8"
        )
    ).hexdigest()

    diff_lines = list(
        difflib.unified_diff(
            current.splitlines(),
            proposed.splitlines(),
            fromfile=relative_display(
                root,
                path,
            ),
            tofile=(
                relative_display(
                    root,
                    path,
                )
                + " (proposed)"
            ),
            lineterm="",
        )
    )

    max_diff_chars = 16_000
    diff = "\n".join(
        diff_lines
    )
    truncated = (
        len(
            diff
        )
        > max_diff_chars
    )

    if truncated:
        diff = (
            diff[
                :max_diff_chars
            ]
            + "\n…[diff truncated]"
        )

    result = {
        "workspace":
            workspace.label,
        "path":
            relative_display(
                root,
                path,
            ),
        "mode":
            payload.mode,
        "current_sha256":
            current_sha,
        "proposed_sha256":
            proposed_sha,
        "replacements":
            replacements,
        "changed":
            current
            != proposed,
        "diff":
            diff,
        "diff_truncated":
            truncated,
        "next_write": {
            "tool":
                (
                    "replace_workspace_text"
                    if payload.mode
                    == "replace_text"
                    else "write_workspace_file"
                ),
            "expected_sha256":
                current_sha,
        },
    }

    return ToolExecutionResult(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        display=(
            f"Previewed proposed edit to "
            f"{workspace.label}:{relative_display(root, path)}."
        ),
        metadata={
            "workspace_id":
                workspace.id,
            "current_sha256":
                current_sha,
            "proposed_sha256":
                proposed_sha,
            "changed":
                current
                != proposed,
        },
    )


def register_filesystem_intelligence_tools() -> None:
    if not settings.computer_enabled:
        return

    definitions = [
        ToolDefinition(
            name="workspace_overview",
            label="Workspace overview",
            description=(
                "Build a bounded high-level profile of an approved local "
                "workspace: project/framework markers, package managers, Git "
                "branch, language statistics, top-level structure, recent and "
                "largest project-owned files. Dependency/build/cache trees and "
                "protected credential paths are excluded."
            ),
            category="Filesystem",
            risk="read",
            default_permission="ask",
            input_model=WorkspaceOverviewInput,
            handler=workspace_overview_tool,
        ),
        ToolDefinition(
            name="workspace_tree",
            label="Workspace tree",
            description=(
                "Map a bounded recursive directory tree inside an approved "
                "workspace. Dependency/build/cache directories and protected "
                "credential paths are pruned."
            ),
            category="Filesystem",
            risk="read",
            default_permission="ask",
            input_model=WorkspaceTreeInput,
            handler=workspace_tree_tool,
        ),
        ToolDefinition(
            name="workspace_recent_files",
            label="Recent workspace files",
            description=(
                "List recently modified project-owned files in an approved "
                "workspace, optionally filtered by age, extension or language."
            ),
            category="Filesystem",
            risk="read",
            default_permission="ask",
            input_model=WorkspaceRecentFilesInput,
            handler=workspace_recent_files_tool,
        ),
        ToolDefinition(
            name="find_workspace_paths",
            label="Find workspace paths",
            description=(
                "Discover files in an approved workspace by glob-like pattern, "
                "extension or programming language without reading file contents."
            ),
            category="Filesystem",
            risk="read",
            default_permission="ask",
            input_model=FindWorkspacePathsInput,
            handler=find_workspace_paths_tool,
        ),
        ToolDefinition(
            name="preview_workspace_edit",
            label="Preview workspace edit",
            description=(
                "Generate a unified diff for a proposed edit to an existing "
                "workspace text file without changing it. Returns the current "
                "SHA-256 required by the existing safe write/edit tools."
            ),
            category="Filesystem",
            risk="read",
            default_permission="ask",
            input_model=PreviewWorkspaceEditInput,
            handler=preview_workspace_edit_tool,
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
