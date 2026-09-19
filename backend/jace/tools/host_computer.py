from __future__ import annotations

# JACE_STEP4B2_FULL_HOST_ACCESS_TOOLS

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from jace.computer.host_access import (
    HostPathError,
    available_locations,
    expand_host_path,
)
from jace.config import settings
from jace.tools.base import (
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from jace.tools.computer import _command_environment
from jace.tools.registry import registry


_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")
_BINARY_SUFFIXES = {
    ".7z", ".avi", ".bin", ".bmp", ".dll", ".doc", ".docx", ".exe",
    ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".mov", ".mp3",
    ".mp4", ".onnx", ".pdf", ".png", ".ppt", ".pptx", ".rar", ".so",
    ".tar", ".ttf", ".wav", ".webm", ".webp", ".woff", ".woff2",
    ".xls", ".xlsx", ".xz", ".zip",
}


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
        raise ToolError("The requested file appears to be binary.")

    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ToolError("The requested file is not supported as readable text.")


def _host_path(value: str, *, must_exist: bool = False) -> Path:
    try:
        return expand_host_path(
            value,
            must_exist=must_exist,
        )
    except HostPathError as exc:
        raise ToolError(str(exc)) from exc


class ComputerLocationsInput(BaseModel):
    pass


async def computer_locations_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    result = available_locations()

    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=(
            f"Host filesystem locations available under the current OS user: "
            f"{', '.join(result.get('drives') or [])}"
        ),
    )


class HostListInput(BaseModel):
    path: str = Field(
        default="~",
        max_length=2000,
        description=(
            "Absolute host path, or a path relative to the current user's home."
        ),
    )
    max_entries: int = Field(default=200, ge=1, le=2000)
    include_hidden: bool = True


async def list_host_directory_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostListInput)

    path = _host_path(payload.path, must_exist=True)

    if not path.is_dir():
        raise ToolError("The requested host path is not a directory.")

    entries = []
    truncated = False

    try:
        children = sorted(
            path.iterdir(),
            key=lambda item: (
                not item.is_dir(),
                item.name.casefold(),
            ),
        )
    except OSError as exc:
        raise ToolError("Could not list that directory.") from exc

    for child in children:
        if (
            not payload.include_hidden
            and child.name.startswith(".")
        ):
            continue

        try:
            stat = child.stat()
            entry = {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
                "size": None if child.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
                "is_symlink": child.is_symlink(),
            }
        except OSError:
            entry = {
                "name": child.name,
                "path": str(child),
                "type": "unknown",
                "size": None,
                "modified": None,
                "is_symlink": None,
            }

        entries.append(entry)

        if len(entries) >= payload.max_entries:
            truncated = len(children) > len(entries)
            break

    return ToolExecutionResult(
        content=json.dumps(
            {
                "path": str(path),
                "entries": entries,
                "truncated": truncated,
            },
            ensure_ascii=False,
        ),
        display=f"Listed {len(entries)} entries in {path}.",
    )


class HostReadInput(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        if (
            self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("end_line must be >= start_line.")
        return self


async def read_host_file_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostReadInput)

    path = _host_path(payload.path, must_exist=True)

    if not path.is_file():
        raise ToolError("The requested host path is not a file.")

    content = _read_text(path)
    lines = content.splitlines()

    start = payload.start_line - 1
    end = payload.end_line or len(lines)

    selected = lines[start:end]
    numbered = "\n".join(
        f"{index}: {line}"
        for index, line in enumerate(
            selected,
            start=payload.start_line,
        )
    )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "start_line": payload.start_line,
                "end_line": min(end, len(lines)),
                "line_count": len(lines),
                "content": numbered,
            },
            ensure_ascii=False,
        ),
        display=(
            f"Read {len(selected)} line"
            f"{'' if len(selected) == 1 else 's'} from {path}."
        ),
        metadata={
            "path": str(path),
            "sha256": _sha256(path),
        },
    )


class HostInfoInput(BaseModel):
    path: str = Field(min_length=1, max_length=2000)


async def host_file_info_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostInfoInput)

    path = _host_path(payload.path, must_exist=True)

    try:
        stat = path.stat()
    except OSError as exc:
        raise ToolError("Could not inspect that host path.") from exc

    result = {
        "path": str(path),
        "name": path.name,
        "type": (
            "directory"
            if path.is_dir()
            else "file"
            if path.is_file()
            else "other"
        ),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
        "is_symlink": path.is_symlink(),
        "suffix": path.suffix,
        "sha256": (
            _sha256(path)
            if path.is_file()
            else None
        ),
    }

    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=f"Inspected {path}.",
    )


class HostSearchInput(BaseModel):
    root: str = Field(min_length=1, max_length=2000)
    query: str = Field(default="", max_length=1000)
    name_pattern: str | None = Field(default=None, max_length=300)
    max_results: int = Field(default=50, ge=1, le=200)
    max_files: int = Field(default=3000, ge=1, le=20_000)
    search_contents: bool = True


async def search_host_files_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostSearchInput)

    root = _host_path(payload.root, must_exist=True)

    if not root.is_dir():
        raise ToolError("Search root must be a directory.")

    query = payload.query.casefold()
    results = []
    scanned = 0

    for current_root, dir_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        # Avoid following junctions/symlinks into unexpected volumes while
        # still allowing the user to search those targets explicitly.
        current = Path(current_root)

        safe_dirs = []
        for name in dir_names:
            candidate = current / name
            try:
                if candidate.is_symlink():
                    continue
            except OSError:
                continue
            safe_dirs.append(name)
        dir_names[:] = safe_dirs

        for name in file_names:
            path = current / name
            scanned += 1

            if scanned > payload.max_files:
                return ToolExecutionResult(
                    content=json.dumps(
                        {
                            "root": str(root),
                            "results": results,
                            "files_scanned": payload.max_files,
                            "scan_limit_reached": True,
                        },
                        ensure_ascii=False,
                    ),
                    display=(
                        f"Found {len(results)} matching file results before "
                        "the scan limit was reached."
                    ),
                )

            if (
                payload.name_pattern
                and not path.match(payload.name_pattern)
            ):
                continue

            matched = (
                bool(query)
                and query in name.casefold()
            )

            snippets = []

            if (
                payload.search_contents
                and query
                and path.suffix.casefold() not in _BINARY_SUFFIXES
            ):
                try:
                    text = _read_text(path)
                except ToolError:
                    text = ""

                if text:
                    for index, line in enumerate(
                        text.splitlines(),
                        start=1,
                    ):
                        if query in line.casefold():
                            matched = True
                            snippets.append(
                                {
                                    "line": index,
                                    "text": line[:500],
                                }
                            )
                            if len(snippets) >= 5:
                                break

            if matched:
                results.append(
                    {
                        "path": str(path),
                        "name": name,
                        "matches": snippets,
                    }
                )

                if len(results) >= payload.max_results:
                    return ToolExecutionResult(
                        content=json.dumps(
                            {
                                "root": str(root),
                                "results": results,
                                "files_scanned": scanned,
                                "scan_limit_reached": False,
                                "result_limit_reached": True,
                            },
                            ensure_ascii=False,
                        ),
                        display=f"Found {len(results)} matching host files.",
                    )

    return ToolExecutionResult(
        content=json.dumps(
            {
                "root": str(root),
                "results": results,
                "files_scanned": scanned,
                "scan_limit_reached": False,
                "result_limit_reached": False,
            },
            ensure_ascii=False,
        ),
        display=f"Found {len(results)} matching host files.",
    )


class HostWriteInput(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    content: str = Field(max_length=500_000)
    expected_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    create_parents: bool = True


async def write_host_file_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostWriteInput)

    path = _host_path(payload.path, must_exist=False)

    if path.exists():
        if not path.is_file():
            raise ToolError("The target exists and is not a file.")

        if payload.expected_sha256 is None:
            raise ToolError(
                "Overwriting an existing file requires expected_sha256 from "
                "a current read/info result."
            )

        current_sha = _sha256(path)
        if current_sha.casefold() != payload.expected_sha256.casefold():
            raise ToolError(
                "The file changed since it was inspected. Read it again before overwriting."
            )

    if payload.create_parents:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError("Could not create parent directories.") from exc

    try:
        path.write_text(payload.content, encoding="utf-8")
    except OSError as exc:
        raise ToolError("Could not write the requested file.") from exc

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "written",
                "path": str(path),
                "sha256": _sha256(path),
                "chars": len(payload.content),
            },
            ensure_ascii=False,
        ),
        display=f"Wrote {path}.",
    )


class HostReplaceInput(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    old_text: str = Field(min_length=1, max_length=100_000)
    new_text: str = Field(max_length=100_000)
    expected_sha256: str = Field(min_length=64, max_length=64)
    expected_occurrences: int = Field(default=1, ge=1, le=100)


async def replace_host_text_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostReplaceInput)

    path = _host_path(payload.path, must_exist=True)

    if not path.is_file():
        raise ToolError("The requested path is not a file.")

    current_sha = _sha256(path)
    if current_sha.casefold() != payload.expected_sha256.casefold():
        raise ToolError(
            "The file changed since it was inspected. Read it again before editing."
        )

    content = _read_text(path)
    count = content.count(payload.old_text)

    if count != payload.expected_occurrences:
        raise ToolError(
            f"Expected {payload.expected_occurrences} matching occurrence(s), "
            f"but found {count}."
        )

    updated = content.replace(
        payload.old_text,
        payload.new_text,
    )

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise ToolError("Could not update the requested file.") from exc

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "updated",
                "path": str(path),
                "replacements": count,
                "sha256": _sha256(path),
            },
            ensure_ascii=False,
        ),
        display=f"Updated {path}.",
    )


class HostMoveInput(BaseModel):
    source: str = Field(min_length=1, max_length=2000)
    destination: str = Field(min_length=1, max_length=2000)
    overwrite: bool = False


async def move_host_path_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostMoveInput)

    source = _host_path(payload.source, must_exist=True)
    destination = _host_path(payload.destination, must_exist=False)

    if destination.exists():
        if not payload.overwrite:
            raise ToolError(
                "Destination already exists. Set overwrite=true only when the "
                "user explicitly requested replacement."
            )

        try:
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        except OSError as exc:
            raise ToolError("Could not replace the existing destination.") from exc

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        moved = shutil.move(str(source), str(destination))
    except OSError as exc:
        raise ToolError("Could not move the requested path.") from exc

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "moved",
                "source": str(source),
                "destination": str(Path(moved)),
            },
            ensure_ascii=False,
        ),
        display=f"Moved {source} to {destination}.",
    )


class HostDeleteInput(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    recursive: bool = False


async def delete_host_path_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, HostDeleteInput)

    path = _host_path(payload.path, must_exist=True)

    # Prevent accidental root-drive deletion through this direct tool. The user
    # can still explicitly approve an equivalent shell command if that is
    # genuinely intended.
    if path.parent == path:
        raise ToolError("Refusing to delete a filesystem root with this tool.")

    try:
        if path.is_dir():
            if not payload.recursive:
                path.rmdir()
            else:
                shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        raise ToolError("Could not delete the requested path.") from exc

    return ToolExecutionResult(
        content=json.dumps(
            {
                "status": "deleted",
                "path": str(path),
                "recursive": payload.recursive,
            },
            ensure_ascii=False,
        ),
        display=f"Deleted {path}.",
    )


ShellName = Literal[
    "powershell",
    "cmd",
    "bash",
    "wsl",
]


class ShellCommandInput(BaseModel):
    shell: ShellName = "powershell"
    command: str = Field(
        min_length=1,
        max_length=50_000,
        description=(
            "Exact shell command/script to run. This exact text is shown to "
            "the user for approval before execution."
        ),
    )
    cwd: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Optional host working directory. Defaults to the current user's home."
        ),
    )
    timeout_seconds: int = Field(default=120, ge=1, le=900)


def _shell_invocation(
    shell: ShellName,
    command: str,
) -> list[str]:
    if os.name == "nt":
        if shell == "powershell":
            executable = (
                shutil.which("pwsh.exe")
                or shutil.which("powershell.exe")
            )
            if not executable:
                raise ToolError("PowerShell was not found.")
            return [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]

        if shell == "cmd":
            executable = shutil.which("cmd.exe")
            if not executable:
                raise ToolError("cmd.exe was not found.")
            return [
                executable,
                "/d",
                "/s",
                "/c",
                command,
            ]

        if shell == "wsl":
            executable = shutil.which("wsl.exe")
            if not executable:
                raise ToolError("wsl.exe was not found.")
            return [
                executable,
                "--",
                "bash",
                "-lc",
                command,
            ]

        if shell == "bash":
            executable = shutil.which("bash.exe") or shutil.which("bash")
            if not executable:
                raise ToolError("bash was not found.")
            return [
                executable,
                "-lc",
                command,
            ]

    else:
        if shell == "powershell":
            executable = shutil.which("pwsh")
            if not executable:
                raise ToolError("pwsh was not found.")
            return [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]

        if shell == "cmd":
            raise ToolError("cmd shell is only available on Windows.")

        if shell == "wsl":
            raise ToolError("WSL shell is only available on Windows.")

        executable = shutil.which("bash")
        if not executable:
            raise ToolError("bash was not found.")
        return [
            executable,
            "-lc",
            command,
        ]

    raise ToolError(f"Unsupported shell: {shell}")


async def _kill_process_tree(
    process: asyncio.subprocess.Process,
) -> None:
    if process.returncode is not None:
        return

    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if taskkill:
            try:
                killer = await asyncio.create_subprocess_exec(
                    taskkill,
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.communicate(), timeout=10)
            except Exception:
                pass

        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    try:
        await process.communicate()
    except Exception:
        pass


def _command_risk(command: str) -> str:
    text = command.casefold()

    critical = (
        "format ",
        "diskpart",
        "remove-item -recurse",
        "remove-item -force",
        "del /s",
        "rd /s",
        "rmdir /s",
        "shutdown",
        "restart-computer",
        "stop-computer",
        "bcdedit",
        "reg delete",
    )

    if any(token in text for token in critical):
        return "high"

    mutating = (
        "remove-item",
        "del ",
        "copy-item",
        "move-item",
        "set-content",
        "add-content",
        "new-item",
        "mkdir",
        "git reset",
        "git clean",
        "git push",
        "npm install",
        "winget install",
        "choco install",
        "pip install",
    )

    if any(token in text for token in mutating):
        return "medium"

    return "unknown"


async def run_shell_command_tool(
    data: BaseModel,
    context: ToolContext,
) -> ToolExecutionResult:
    payload = data
    assert isinstance(payload, ShellCommandInput)

    cwd = (
        _host_path(payload.cwd, must_exist=True)
        if payload.cwd
        else Path.home().resolve()
    )

    if not cwd.is_dir():
        raise ToolError("Shell working directory must be a directory.")

    argv = _shell_invocation(
        payload.shell,
        payload.command,
    )

    creation_kwargs: dict[str, Any] = {}
    if os.name != "nt":
        creation_kwargs["start_new_session"] = True

    started = time.perf_counter()

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_command_environment(),
            **creation_kwargs,
        )
    except OSError as exc:
        raise ToolError("Could not start the requested shell command.") from exc

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            process.communicate(),
            timeout=payload.timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        await _kill_process_tree(process)
        raise ToolError(
            f"Shell command timed out after {payload.timeout_seconds} seconds. "
            "The process tree was terminated."
        ) from exc
    except asyncio.CancelledError:
        await _kill_process_tree(process)
        raise

    duration_ms = int(
        (time.perf_counter() - started)
        * 1000
    )

    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")

    limit = max(
        2000,
        settings.computer_command_output_chars,
    )

    stdout_truncated = len(stdout) > limit
    stderr_truncated = len(stderr) > limit

    if stdout_truncated:
        stdout = stdout[:limit] + "\n…[stdout truncated]"

    if stderr_truncated:
        stderr = stderr[:limit] + "\n…[stderr truncated]"

    result = {
        "status": (
            "succeeded"
            if process.returncode == 0
            else "failed"
        ),
        "shell": payload.shell,
        "command": payload.command,
        "cwd": str(cwd),
        "exit_code": process.returncode,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "risk_hint": _command_risk(payload.command),
    }

    return ToolExecutionResult(
        content=json.dumps(result, ensure_ascii=False),
        display=(
            f"Ran {payload.shell} command in {cwd} "
            f"(exit {process.returncode}, {duration_ms} ms)."
        ),
        metadata={
            "shell": payload.shell,
            "cwd": str(cwd),
            "exit_code": process.returncode,
            "duration_ms": duration_ms,
            "risk_hint": _command_risk(payload.command),
        },
    )


def register_full_computer_access_tools() -> None:
    if not settings.computer_enabled:
        return

    definitions = [
        ToolDefinition(
            name="computer_locations",
            label="Computer locations",
            description=(
                "List local drives and common user folders. Use this when Jace "
                "needs to discover host paths outside configured project bookmarks."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=ComputerLocationsInput,
            handler=computer_locations_tool,
        ),
        ToolDefinition(
            name="list_host_directory",
            label="List host directory",
            description=(
                "List any directory accessible to the OS user running Jace. "
                "Configured workspaces are not required."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=HostListInput,
            handler=list_host_directory_tool,
        ),
        ToolDefinition(
            name="read_host_file",
            label="Read host file",
            description=(
                "Read a text file anywhere the current OS user can access. This "
                "host-level tool is not restricted by Computer workspaces or "
                "the old sensitive-file filter."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=HostReadInput,
            handler=read_host_file_tool,
        ),
        ToolDefinition(
            name="host_file_info",
            label="Host file info",
            description=(
                "Inspect metadata and SHA-256 for any host path accessible to "
                "the current OS user."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=HostInfoInput,
            handler=host_file_info_tool,
        ),
        ToolDefinition(
            name="search_host_files",
            label="Search host files",
            description=(
                "Search filenames and optionally text contents recursively from "
                "any host directory accessible to the current OS user."
            ),
            category="Computer",
            risk="read",
            default_permission="allow",
            input_model=HostSearchInput,
            handler=search_host_files_tool,
        ),
        ToolDefinition(
            name="write_host_file",
            label="Write host file",
            description=(
                "Create or overwrite a text file anywhere the current OS user "
                "can write. Existing files require an expected SHA-256."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=HostWriteInput,
            handler=write_host_file_tool,
        ),
        ToolDefinition(
            name="replace_host_text",
            label="Edit host file",
            description=(
                "Perform an exact SHA-guarded text replacement in any host text "
                "file accessible to the current OS user."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=HostReplaceInput,
            handler=replace_host_text_tool,
        ),
        ToolDefinition(
            name="move_host_path",
            label="Move host path",
            description=(
                "Move or rename a host file/directory anywhere the current OS "
                "user has permission. Requires approval."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=HostMoveInput,
            handler=move_host_path_tool,
        ),
        ToolDefinition(
            name="delete_host_path",
            label="Delete host path",
            description=(
                "Delete a host file or directory accessible to the current OS "
                "user. Recursive directory deletion requires recursive=true and approval."
            ),
            category="Computer",
            risk="write",
            default_permission="ask",
            input_model=HostDeleteInput,
            handler=delete_host_path_tool,
        ),
        ToolDefinition(
            name="run_shell_command",
            label="Run shell command",
            description=(
                "Run an arbitrary PowerShell, cmd, Bash or WSL command on the "
                "local computer under the same OS user as Jace. The exact shell, "
                "command and working directory are shown to the user and MUST be "
                "approved for every execution. Use this for tasks that cannot be "
                "completed through a narrower direct tool."
            ),
            category="Computer",
            risk="execute",
            default_permission="ask",
            input_model=ShellCommandInput,
            handler=run_shell_command_tool,
        ),
    ]

    for definition in definitions:
        registry.register(
            definition,
            replace=True,
        )
