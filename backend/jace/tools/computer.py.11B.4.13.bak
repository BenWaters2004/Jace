from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jace.computer.security import ComputerPathError, relative_display, resolve_workspace_path
from jace.computer.service import (
    ensure_workspace_readable,
    ensure_workspace_writable,
    get_command_preset,
    get_workspace,
    list_workspaces,
    parse_arguments_json,
)
from jace.config import settings
from jace.tools.base import ToolContext, ToolDefinition, ToolError, ToolExecutionResult
from jace.tools.registry import registry


_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ToolError("Could not inspect the requested file.") from exc

    if size > settings.computer_max_read_bytes:
        raise ToolError(
            f"File is too large for Jace's text reader ({size:,} bytes; "
            f"limit {settings.computer_max_read_bytes:,})."
        )

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ToolError("Could not read the requested file.") from exc

    if b"\x00" in raw[:4096]:
        raise ToolError("The requested file appears to be binary rather than text.")

    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ToolError("The requested file is not supported as readable text.")


async def _workspace_for_tool(context: ToolContext, workspace_id: str, *, write: bool = False):
    workspace = await get_workspace(context.session, workspace_id)
    if workspace is None:
        raise ToolError("Unknown computer workspace. Call list_computer_workspaces first.")
    try:
        if write:
            ensure_workspace_writable(workspace)
        else:
            ensure_workspace_readable(workspace)
    except ComputerPathError as exc:
        raise ToolError(str(exc)) from exc
    return workspace


def _resolve(workspace, relative_path: str, *, must_exist: bool = False):
    try:
        return resolve_workspace_path(
            workspace.root_path,
            relative_path,
            must_exist=must_exist,
        )
    except ComputerPathError as exc:
        raise ToolError(str(exc)) from exc


class ListComputerWorkspacesInput(BaseModel):
    include_inactive: bool = Field(default=False)


async def list_computer_workspaces_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ListComputerWorkspacesInput)
    workspaces = await list_workspaces(context.session, active_only=not payload.include_inactive)
    result = []
    for workspace in workspaces:
        result.append(
            {
                "id": workspace.id,
                "label": workspace.label,
                "root_path": workspace.root_path,
                "read_enabled": workspace.read_enabled,
                "write_enabled": workspace.write_enabled,
                "is_active": workspace.is_active,
                "commands": [
                    {
                        "id": command.id,
                        "label": command.label,
                        "relative_cwd": command.relative_cwd,
                        "timeout_seconds": command.timeout_seconds,
                        "is_active": command.is_active,
                    }
                    for command in workspace.commands
                    if command.is_active or payload.include_inactive
                ],
            }
        )
    return ToolExecutionResult(
        content=json.dumps({"workspaces": result}, ensure_ascii=False),
        display=f"Found {len(result)} configured computer workspace{'s' if len(result) != 1 else ''}.",
    )


class ListWorkspaceFilesInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(default=".", max_length=800)
    max_entries: int = Field(default=100, ge=1, le=300)
    include_hidden: bool = False


async def list_workspace_files_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ListWorkspaceFilesInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id)
    root, directory = _resolve(workspace, payload.path, must_exist=True)
    if not directory.is_dir():
        raise ToolError("The requested path is not a directory.")

    entries = []
    try:
        children = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError as exc:
        raise ToolError("Could not list that directory.") from exc

    for child in children:
        if not payload.include_hidden and child.name.startswith("."):
            continue
        try:
            _, resolved = resolve_workspace_path(workspace.root_path, relative_display(root, child), must_exist=True)
        except ComputerPathError:
            continue
        try:
            stat = resolved.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": resolved.name,
                "path": relative_display(root, resolved),
                "type": "directory" if resolved.is_dir() else "file",
                "size": None if resolved.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
            }
        )
        if len(entries) >= payload.max_entries:
            break

    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace": workspace.label,
                "directory": relative_display(root, directory),
                "entries": entries,
                "truncated": len(entries) >= payload.max_entries,
            },
            ensure_ascii=False,
        ),
        display=f"Listed {len(entries)} item{'s' if len(entries) != 1 else ''} in {workspace.label}:{relative_display(root, directory)}.",
    )


class ReadWorkspaceFileInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=300, ge=1, le=600)


async def read_workspace_file_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ReadWorkspaceFileInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id)
    root, path = _resolve(workspace, payload.path, must_exist=True)
    if not path.is_file():
        raise ToolError("The requested path is not a file.")

    text = _read_text(path)
    lines = text.splitlines()
    start = min(payload.start_line - 1, len(lines))
    selected = lines[start : start + payload.max_lines]
    numbered = "\n".join(f"{start + index + 1}: {line}" for index, line in enumerate(selected))
    digest = _sha256(path)

    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace": workspace.label,
                "path": relative_display(root, path),
                "sha256": digest,
                "total_lines": len(lines),
                "start_line": start + 1 if lines else 1,
                "returned_lines": len(selected),
                "truncated": start + len(selected) < len(lines),
                "text": numbered,
            },
            ensure_ascii=False,
        ),
        display=f"Read {len(selected)} line{'s' if len(selected) != 1 else ''} from {workspace.label}:{relative_display(root, path)}.",
        metadata={"sha256": digest},
    )


class WorkspaceFileInfoInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)


async def workspace_file_info_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, WorkspaceFileInfoInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id)
    root, path = _resolve(workspace, payload.path, must_exist=True)
    stat = path.stat()
    result = {
        "workspace": workspace.label,
        "path": relative_display(root, path),
        "type": "directory" if path.is_dir() else "file",
        "size": None if path.is_dir() else stat.st_size,
        "modified": stat.st_mtime,
        "sha256": _sha256(path) if path.is_file() and stat.st_size <= settings.computer_max_read_bytes else None,
    }
    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Inspected {workspace.label}:{result['path']}.",
    )


class SearchWorkspaceFilesInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    query: str = Field(min_length=1, max_length=300)
    path: str = Field(default=".", max_length=800)
    include_content: bool = True
    max_results: int = Field(default=20, ge=1, le=50)


async def search_workspace_files_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, SearchWorkspaceFilesInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id)
    root, base = _resolve(workspace, payload.path, must_exist=True)
    if not base.is_dir():
        raise ToolError("Search path must be a directory.")

    query = payload.query.casefold()
    results = []
    scanned = 0

    for current_root, dir_names, file_names in os.walk(base):
        dir_names[:] = [name for name in dir_names if not name.startswith(".")]
        for name in file_names:
            if scanned >= settings.computer_search_max_files:
                break
            scanned += 1
            candidate = Path(current_root) / name
            try:
                _, candidate = resolve_workspace_path(
                    workspace.root_path,
                    relative_display(root, candidate),
                    must_exist=True,
                )
            except ComputerPathError:
                continue

            relative = relative_display(root, candidate)
            path_match = query in relative.casefold()
            content_match = None
            line_number = None

            if payload.include_content:
                try:
                    if candidate.stat().st_size <= settings.computer_max_read_bytes:
                        text = _read_text(candidate)
                        for index, line in enumerate(text.splitlines(), start=1):
                            if query in line.casefold():
                                line_number = index
                                content_match = line.strip()[:500]
                                break
                except (ToolError, OSError):
                    pass

            if path_match or content_match is not None:
                results.append(
                    {
                        "path": relative,
                        "path_match": path_match,
                        "line": line_number,
                        "snippet": content_match,
                    }
                )
                if len(results) >= min(payload.max_results, settings.computer_search_max_results):
                    break
        if scanned >= settings.computer_search_max_files or len(results) >= payload.max_results:
            break

    return ToolExecutionResult(
        content=json.dumps(
            {
                "workspace": workspace.label,
                "query": payload.query,
                "results": results,
                "files_scanned": scanned,
                "scan_limit_reached": scanned >= settings.computer_search_max_files,
            },
            ensure_ascii=False,
        ),
        display=f"Found {len(results)} matching file result{'s' if len(results) != 1 else ''} in {workspace.label}.",
    )


class CreateWorkspaceDirectoryInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)


async def create_workspace_directory_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, CreateWorkspaceDirectoryInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id, write=True)
    root, path = _resolve(workspace, payload.path, must_exist=False)
    if path.exists():
        raise ToolError("That path already exists.")
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise ToolError("Could not create the directory.") from exc
    return ToolExecutionResult(
        content=json.dumps({"created_directory": relative_display(root, path)}),
        display=f"Created directory {workspace.label}:{relative_display(root, path)}.",
    )


class WriteWorkspaceFileInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)
    content: str = Field(max_length=200_000)
    overwrite: bool = False
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


async def write_workspace_file_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, WriteWorkspaceFileInput)
    if len(payload.content) > settings.computer_max_write_chars:
        raise ToolError("Requested file content exceeds the configured write limit.")

    workspace = await _workspace_for_tool(context, payload.workspace_id, write=True)
    root, path = _resolve(workspace, payload.path, must_exist=False)

    if path.exists():
        if not path.is_file():
            raise ToolError("The destination exists and is not a file.")
        if not payload.overwrite:
            raise ToolError("The file already exists. Read it first, then request overwrite with its SHA-256.")
        if payload.expected_sha256 is None:
            raise ToolError("Overwriting an existing file requires expected_sha256 from read_workspace_file or workspace_file_info.")
        current = _sha256(path)
        if current.casefold() != payload.expected_sha256.casefold():
            raise ToolError("The file changed since it was inspected. Read it again before overwriting.")
    elif payload.expected_sha256 is not None:
        raise ToolError("expected_sha256 was supplied but the destination file does not exist.")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload.content, encoding="utf-8")
    except OSError as exc:
        raise ToolError("Could not write the file.") from exc

    digest = _sha256(path)
    return ToolExecutionResult(
        content=json.dumps({"path": relative_display(root, path), "sha256": digest, "characters": len(payload.content)}),
        display=f"Wrote {workspace.label}:{relative_display(root, path)}.",
        metadata={"sha256": digest},
    )


class ReplaceWorkspaceTextInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)
    old_text: str = Field(min_length=1, max_length=30_000)
    new_text: str = Field(max_length=30_000)
    expected_occurrences: int = Field(default=1, ge=1, le=50)
    expected_sha256: str = Field(min_length=64, max_length=64)


async def replace_workspace_text_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ReplaceWorkspaceTextInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id, write=True)
    root, path = _resolve(workspace, payload.path, must_exist=True)
    if not path.is_file():
        raise ToolError("The requested path is not a file.")

    current_sha = _sha256(path)
    if current_sha.casefold() != payload.expected_sha256.casefold():
        raise ToolError("The file changed since it was inspected. Read it again before editing.")

    text = _read_text(path)
    count = text.count(payload.old_text)
    if count != payload.expected_occurrences:
        raise ToolError(
            f"Expected {payload.expected_occurrences} matching occurrence(s), but found {count}. No change was made."
        )
    updated = text.replace(payload.old_text, payload.new_text)
    if len(updated) > settings.computer_max_write_chars:
        raise ToolError("Edited file would exceed the configured write limit.")
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise ToolError("Could not update the file.") from exc

    digest = _sha256(path)
    return ToolExecutionResult(
        content=json.dumps({"path": relative_display(root, path), "sha256": digest, "replacements": count}),
        display=f"Updated {workspace.label}:{relative_display(root, path)} ({count} replacement{'s' if count != 1 else ''}).",
        metadata={"sha256": digest},
    )


class MoveWorkspacePathInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    source_path: str = Field(min_length=1, max_length=800)
    destination_path: str = Field(min_length=1, max_length=800)
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


async def move_workspace_path_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, MoveWorkspacePathInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id, write=True)
    root, source = _resolve(workspace, payload.source_path, must_exist=True)
    _, destination = _resolve(workspace, payload.destination_path, must_exist=False)
    if source == root:
        raise ToolError("The workspace root itself cannot be moved or renamed.")
    if destination.exists():
        raise ToolError("Destination already exists; move will not overwrite it.")
    if source.is_dir():
        try:
            destination.relative_to(source)
        except ValueError:
            pass
        else:
            raise ToolError("A directory cannot be moved inside itself.")
    if source.is_file():
        if payload.expected_sha256 is None:
            raise ToolError("Moving a file requires expected_sha256 from a prior inspection.")
        if _sha256(source).casefold() != payload.expected_sha256.casefold():
            raise ToolError("The source file changed since it was inspected.")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    except OSError as exc:
        raise ToolError("Could not move the requested path.") from exc
    return ToolExecutionResult(
        content=json.dumps({"from": relative_display(root, source), "to": relative_display(root, destination)}),
        display=f"Moved {workspace.label}:{payload.source_path} to {payload.destination_path}.",
    )


class DeleteWorkspaceFileInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    path: str = Field(min_length=1, max_length=800)
    expected_sha256: str = Field(min_length=64, max_length=64)


async def delete_workspace_file_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, DeleteWorkspaceFileInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id, write=True)
    root, path = _resolve(workspace, payload.path, must_exist=True)
    if not path.is_file():
        raise ToolError("Phase 6 deletion only permits exact files, not directories.")
    if _sha256(path).casefold() != payload.expected_sha256.casefold():
        raise ToolError("The file changed since it was inspected. Read it again before deleting.")
    display_path = relative_display(root, path)
    try:
        path.unlink()
    except OSError as exc:
        raise ToolError("Could not delete the file.") from exc
    return ToolExecutionResult(
        content=json.dumps({"deleted_file": display_path}),
        display=f"Deleted {workspace.label}:{display_path}.",
    )


class RunWorkspaceCommandInput(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    command_id: str = Field(min_length=36, max_length=36)


def _command_environment() -> dict[str, str]:
    if settings.computer_command_inherit_environment:
        return dict(os.environ)

    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


async def run_workspace_command_tool(data: BaseModel, context: ToolContext) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, RunWorkspaceCommandInput)
    workspace = await _workspace_for_tool(context, payload.workspace_id, write=False)
    preset = await get_command_preset(context.session, payload.command_id)
    if preset is None or preset.workspace_id != workspace.id or not preset.is_active:
        raise ToolError("Unknown or inactive command preset for this workspace.")

    _, cwd = _resolve(workspace, preset.relative_cwd, must_exist=True)
    if not cwd.is_dir():
        raise ToolError("The command preset working directory is not a directory.")

    arguments = parse_arguments_json(preset.arguments_json)
    timeout = min(preset.timeout_seconds, settings.computer_command_max_timeout_seconds)

    try:
        process = await asyncio.create_subprocess_exec(
            preset.executable,
            *arguments,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_command_environment(),
        )
    except (OSError, ValueError) as exc:
        raise ToolError(f"Could not start command preset '{preset.label}'.") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ToolError(f"Command preset timed out after {timeout} seconds.") from exc

    output = stdout.decode("utf-8", errors="replace")
    error_output = stderr.decode("utf-8", errors="replace")
    combined = (output + ("\n" if output and error_output else "") + error_output).strip()
    truncated = len(combined) > settings.computer_command_output_chars
    if truncated:
        combined = combined[: settings.computer_command_output_chars] + "\n…[output truncated]"

    result = {
        "workspace": workspace.label,
        "command_id": preset.id,
        "command_label": preset.label,
        "working_directory": preset.relative_cwd,
        "exit_code": process.returncode,
        "output": combined,
        "truncated": truncated,
    }
    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Ran command preset '{preset.label}' in {workspace.label} (exit {process.returncode}).",
    )


def register_computer_tools() -> None:
    if not settings.computer_enabled:
        return

    definitions = [
        ToolDefinition(
            name="list_computer_workspaces",
            label="List computer workspaces",
            description=(
                "List the local directory workspaces explicitly approved by the user, including their IDs, "
                "read/write status and available command preset IDs. Call this before any other computer tool."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=ListComputerWorkspacesInput,
            handler=list_computer_workspaces_tool,
        ),
        ToolDefinition(
            name="list_workspace_files",
            label="List workspace files",
            description="List files/directories inside one approved workspace. Paths must be workspace-relative.",
            category="Computer",
            risk="read",
            default_permission="ask",
            input_model=ListWorkspaceFilesInput,
            handler=list_workspace_files_tool,
        ),
        ToolDefinition(
            name="read_workspace_file",
            label="Read workspace file",
            description=(
                "Read a text file inside an approved workspace with line numbers and return its SHA-256. "
                "Potential credential/configuration files are blocked."
            ),
            category="Computer",
            risk="read",
            default_permission="ask",
            input_model=ReadWorkspaceFileInput,
            handler=read_workspace_file_tool,
        ),
        ToolDefinition(
            name="search_workspace_files",
            label="Search workspace files",
            description="Search file names and text content inside an approved workspace.",
            category="Computer",
            risk="read",
            default_permission="ask",
            input_model=SearchWorkspaceFilesInput,
            handler=search_workspace_files_tool,
        ),
        ToolDefinition(
            name="workspace_file_info",
            label="Workspace file info",
            description="Inspect one workspace file/directory and obtain SHA-256 for safe later writes or deletion.",
            category="Computer",
            risk="read",
            default_permission="ask",
            input_model=WorkspaceFileInfoInput,
            handler=workspace_file_info_tool,
        ),
        ToolDefinition(
            name="create_workspace_directory",
            label="Create workspace directory",
            description="Create a directory inside a write-enabled approved workspace.",
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=CreateWorkspaceDirectoryInput,
            handler=create_workspace_directory_tool,
        ),
        ToolDefinition(
            name="write_workspace_file",
            label="Write workspace file",
            description=(
                "Create or overwrite a UTF-8 text file inside a write-enabled workspace. Existing files require "
                "their current SHA-256, so inspect/read them first."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=WriteWorkspaceFileInput,
            handler=write_workspace_file_tool,
        ),
        ToolDefinition(
            name="replace_workspace_text",
            label="Edit workspace file",
            description=(
                "Replace an exact text fragment inside a write-enabled workspace file. Requires current SHA-256 "
                "and exact expected occurrence count to avoid blind edits."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=ReplaceWorkspaceTextInput,
            handler=replace_workspace_text_tool,
        ),
        ToolDefinition(
            name="move_workspace_path",
            label="Move workspace path",
            description="Move/rename a path within the same approved workspace without overwriting destinations.",
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=MoveWorkspacePathInput,
            handler=move_workspace_path_tool,
        ),
        ToolDefinition(
            name="delete_workspace_file",
            label="Delete workspace file",
            description=(
                "Delete one exact file inside a write-enabled workspace. Recursive directory deletion is not "
                "available and the file's current SHA-256 is required."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=DeleteWorkspaceFileInput,
            handler=delete_workspace_file_tool,
        ),
        ToolDefinition(
            name="run_workspace_command",
            label="Run command preset",
            description=(
                "Run one exact command preset that the user created for an approved workspace. Jace cannot invent "
                "shell commands or modify preset arguments."
            ),
            category="Computer",
            risk="execute",
            default_permission="ask",
            input_model=RunWorkspaceCommandInput,
            handler=run_workspace_command_tool,
        ),
    ]

    for definition in definitions:
        registry.register(definition, replace=True)
