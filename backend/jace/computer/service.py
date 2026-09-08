from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from jace.computer.security import ComputerPathError, validate_workspace_root
from jace.db.models import ComputerCommandPreset, ComputerWorkspace


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def list_workspaces(
    session: AsyncSession,
    *,
    active_only: bool = False,
) -> list[ComputerWorkspace]:
    statement = (
        select(ComputerWorkspace)
        .options(selectinload(ComputerWorkspace.commands))
        .order_by(ComputerWorkspace.label.asc())
    )
    if active_only:
        statement = statement.where(ComputerWorkspace.is_active.is_(True))
    result = await session.execute(statement)
    return list(result.scalars().unique().all())


async def get_workspace(
    session: AsyncSession,
    workspace_id: str,
) -> ComputerWorkspace | None:
    result = await session.execute(
        select(ComputerWorkspace)
        .options(selectinload(ComputerWorkspace.commands))
        .where(ComputerWorkspace.id == workspace_id)
    )
    return result.scalar_one_or_none()


async def create_workspace(
    session: AsyncSession,
    *,
    label: str,
    root_path: str,
    read_enabled: bool = True,
    write_enabled: bool = False,
) -> ComputerWorkspace:
    resolved = validate_workspace_root(root_path)

    result = await session.execute(
        select(ComputerWorkspace).where(ComputerWorkspace.root_path == str(resolved))
    )
    if result.scalar_one_or_none() is not None:
        raise ValueError("That workspace path is already configured.")

    workspace = ComputerWorkspace(
        label=label.strip(),
        root_path=str(resolved),
        read_enabled=read_enabled,
        write_enabled=write_enabled,
        is_active=True,
    )
    session.add(workspace)
    await session.commit()
    return (await get_workspace(session, workspace.id)) or workspace


async def update_workspace(
    session: AsyncSession,
    workspace: ComputerWorkspace,
    *,
    label: str | None = None,
    root_path: str | None = None,
    read_enabled: bool | None = None,
    write_enabled: bool | None = None,
    is_active: bool | None = None,
) -> ComputerWorkspace:
    if label is not None:
        workspace.label = label.strip()
    if root_path is not None:
        resolved = validate_workspace_root(root_path)
        result = await session.execute(
            select(ComputerWorkspace).where(
                ComputerWorkspace.root_path == str(resolved),
                ComputerWorkspace.id != workspace.id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("That workspace path is already configured.")
        workspace.root_path = str(resolved)
    if read_enabled is not None:
        workspace.read_enabled = read_enabled
    if write_enabled is not None:
        workspace.write_enabled = write_enabled
    if is_active is not None:
        workspace.is_active = is_active
    workspace.updated_at = utc_now()
    await session.commit()
    return (await get_workspace(session, workspace.id)) or workspace


async def delete_workspace_configuration(
    session: AsyncSession,
    workspace: ComputerWorkspace,
) -> None:
    await session.delete(workspace)
    await session.commit()


def parse_arguments_json(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


_BLOCKED_EXECUTABLES = {
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "cmd",
    "cmd.exe",
    "bash",
    "bash.exe",
    "sh",
    "wsl",
    "wsl.exe",
    "cscript",
    "cscript.exe",
    "wscript",
    "wscript.exe",
    "mshta",
    "mshta.exe",
    "rundll32",
    "rundll32.exe",
}


def validate_command_executable(executable: str) -> str:
    value = executable.strip().strip('"')
    if not value:
        raise ValueError("Executable cannot be empty.")
    name = Path(value).name.casefold()
    if name in _BLOCKED_EXECUTABLES:
        raise ValueError(
            "Interactive shell hosts are not permitted as command presets. "
            "Use a direct executable such as git, npm, cargo, pytest, or a specific program."
        )
    return value


async def create_command_preset(
    session: AsyncSession,
    workspace: ComputerWorkspace,
    *,
    label: str,
    executable: str,
    arguments: list[str],
    relative_cwd: str = ".",
    timeout_seconds: int = 120,
) -> ComputerCommandPreset:
    if not workspace.is_active:
        raise ValueError("Cannot add a command preset to an inactive workspace.")

    preset = ComputerCommandPreset(
        workspace_id=workspace.id,
        label=label.strip(),
        executable=validate_command_executable(executable),
        arguments_json=json.dumps([str(item) for item in arguments], ensure_ascii=False),
        relative_cwd=relative_cwd.strip() or ".",
        timeout_seconds=timeout_seconds,
        is_active=True,
    )
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return preset


async def get_command_preset(
    session: AsyncSession,
    command_id: str,
) -> ComputerCommandPreset | None:
    return await session.get(ComputerCommandPreset, command_id)


async def update_command_preset(
    session: AsyncSession,
    preset: ComputerCommandPreset,
    *,
    label: str | None = None,
    executable: str | None = None,
    arguments: list[str] | None = None,
    relative_cwd: str | None = None,
    timeout_seconds: int | None = None,
    is_active: bool | None = None,
) -> ComputerCommandPreset:
    if label is not None:
        preset.label = label.strip()
    if executable is not None:
        preset.executable = validate_command_executable(executable)
    if arguments is not None:
        preset.arguments_json = json.dumps([str(item) for item in arguments], ensure_ascii=False)
    if relative_cwd is not None:
        preset.relative_cwd = relative_cwd.strip() or "."
    if timeout_seconds is not None:
        preset.timeout_seconds = timeout_seconds
    if is_active is not None:
        preset.is_active = is_active
    preset.updated_at = utc_now()
    await session.commit()
    await session.refresh(preset)
    return preset


async def delete_command_preset(
    session: AsyncSession,
    preset: ComputerCommandPreset,
) -> None:
    await session.delete(preset)
    await session.commit()


def ensure_workspace_readable(workspace: ComputerWorkspace) -> None:
    if not workspace.is_active:
        raise ComputerPathError("This workspace is inactive.")
    if not workspace.read_enabled:
        raise ComputerPathError("Read access is disabled for this workspace.")


def ensure_workspace_writable(workspace: ComputerWorkspace) -> None:
    if not workspace.is_active:
        raise ComputerPathError("This workspace is inactive.")
    if not workspace.write_enabled:
        raise ComputerPathError("Write access is disabled for this workspace.")
