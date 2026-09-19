from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.db.models import (
    ComputerWorkspace,
    Device,
    ExecutionScope,
    utc_now,
)


_ALLOWED_SHELLS = {
    "powershell",
    "cmd",
    "wsl",
    "bash",
}


def _absolute_device_path(value: str) -> str:
    path = str(value or "").strip()

    if not path:
        raise ValueError(
            "Execution scope root path cannot be empty."
        )

    windows = PureWindowsPath(
        path
    )
    posix = PurePosixPath(
        path
    )

    if not (
        windows.is_absolute()
        or posix.is_absolute()
    ):
        raise ValueError(
            "Execution scope root path must be absolute on the target device."
        )

    return path


def normalise_shells(
    values: Iterable[str],
) -> list[str]:
    shells: list[str] = []

    for raw in values:
        shell = str(
            raw
        ).strip().lower()

        if not shell:
            continue

        if shell not in _ALLOWED_SHELLS:
            raise ValueError(
                f"Unsupported execution shell: {shell}"
            )

        if shell not in shells:
            shells.append(
                shell
            )

    if not shells:
        raise ValueError(
            "Execution scope must allow at least one shell."
        )

    return shells


def scope_shells(
    row: ExecutionScope,
) -> list[str]:
    try:
        parsed = json.loads(
            row.allowed_shells_json
            or "[]"
        )
    except json.JSONDecodeError:
        return []

    if not isinstance(
        parsed,
        list,
    ):
        return []

    return [
        str(item)
        for item in parsed
        if str(item)
    ]


async def get_execution_scope(
    session: AsyncSession,
    scope_id: str,
) -> ExecutionScope | None:
    result = await session.execute(
        select(ExecutionScope).where(
            ExecutionScope.id
            == scope_id
        )
    )

    return result.scalar_one_or_none()


async def list_execution_scopes(
    session: AsyncSession,
    *,
    active_only: bool = True,
) -> list[ExecutionScope]:
    statement = (
        select(ExecutionScope)
        .order_by(
            ExecutionScope.label.asc()
        )
    )

    if active_only:
        statement = statement.where(
            ExecutionScope.is_active.is_(
                True
            )
        )

    result = await session.execute(
        statement
    )

    return list(
        result.scalars().all()
    )


async def create_execution_scope(
    session: AsyncSession,
    *,
    label: str,
    device_id: str,
    workspace_id: str,
    device_root_path: str | None,
    allowed_shells: list[str],
    process_enabled: bool,
    terminal_enabled: bool,
) -> ExecutionScope:
    label = str(
        label
    ).strip()

    if not label:
        raise ValueError(
            "Execution scope label cannot be empty."
        )

    device = await session.get(
        Device,
        device_id,
    )

    if (
        device is None
        or not device.is_active
        or device.revoked_at
        is not None
    ):
        raise ValueError(
            "Execution scope device does not exist or is revoked."
        )

    workspace = await session.get(
        ComputerWorkspace,
        workspace_id,
    )

    if (
        workspace is None
        or not workspace.is_active
    ):
        raise ValueError(
            "Execution scope workspace does not exist or is inactive."
        )

    root = _absolute_device_path(
        device_root_path
        or workspace.root_path
    )
    shells = normalise_shells(
        allowed_shells
    )

    row = ExecutionScope(
        label=label[:160],
        device_id=device_id,
        workspace_id=workspace_id,
        device_root_path=root,
        allowed_shells_json=json.dumps(
            shells,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        process_enabled=bool(
            process_enabled
        ),
        terminal_enabled=bool(
            terminal_enabled
        ),
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    session.add(
        row
    )
    await session.commit()
    await session.refresh(
        row
    )

    return row


async def update_execution_scope(
    session: AsyncSession,
    row: ExecutionScope,
    *,
    label: str | None = None,
    device_root_path: str | None = None,
    allowed_shells: list[str] | None = None,
    process_enabled: bool | None = None,
    terminal_enabled: bool | None = None,
    is_active: bool | None = None,
) -> ExecutionScope:
    if label is not None:
        value = str(
            label
        ).strip()

        if not value:
            raise ValueError(
                "Execution scope label cannot be empty."
            )

        row.label = value[:160]

    if device_root_path is not None:
        row.device_root_path = (
            _absolute_device_path(
                device_root_path
            )
        )

    if allowed_shells is not None:
        row.allowed_shells_json = (
            json.dumps(
                normalise_shells(
                    allowed_shells
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    if process_enabled is not None:
        row.process_enabled = bool(
            process_enabled
        )

    if terminal_enabled is not None:
        row.terminal_enabled = bool(
            terminal_enabled
        )

    if is_active is not None:
        row.is_active = bool(
            is_active
        )

    row.updated_at = utc_now()

    await session.commit()
    await session.refresh(
        row
    )

    return row


async def delete_execution_scope(
    session: AsyncSession,
    row: ExecutionScope,
) -> None:
    await session.delete(
        row
    )
    await session.commit()
