from __future__ import annotations

import ntpath
import posixpath
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from jace.api.processes import (
    ProcessResponse,
    _response as process_response,
)
from jace.api.terminals import (
    TerminalResponse,
    _response as terminal_response,
)
from jace.auth.actor_context import ActorContext, require_actor
from jace.auth.resource_ownership import require_or_claim_local
from jace.database import SessionLocal
from jace.db.models import (
    ComputerWorkspace,
    Device,
    ExecutionScope,
)
from jace.devices.connections import device_connections
from jace.devices.service import device_response
from jace.execution_scopes.security import device_scoped_path
from jace.execution_scopes.service import scope_shells
from jace.process_runtime import process_runtime
from jace.terminal_runtime import terminal_runtime
from jace.tools.permissions import (
    create_tool_audit,
    update_tool_audit,
)


router = APIRouter(
    prefix="/execution/runtime",
    tags=["execution-runtime"],
)


ShellName = Literal[
    "powershell",
    "cmd",
    "wsl",
    "bash",
]


class ScopedProcessStart(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    shell: ShellName
    command: str = Field(min_length=1, max_length=50000)
    relative_cwd: str = Field(default=".", max_length=1200)
    mode: Literal["foreground", "background"] = "background"
    timeout_seconds: int | None = Field(
        default=120,
        ge=1,
        le=86400,
    )


class ScopedProcessMutation(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    force: bool = False


class ScopedProcessResult(BaseModel):
    scope_id: str
    process: ProcessResponse


class ScopedTerminalOpen(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    shell: ShellName
    relative_cwd: str = Field(default=".", max_length=1200)
    cols: int = Field(default=120, ge=20, le=400)
    rows: int = Field(default=30, ge=5, le=200)


class ScopedTerminalInput(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    data: str = Field(min_length=1, max_length=20000)


class ScopedTerminalResize(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    cols: int = Field(ge=20, le=400)
    rows: int = Field(ge=5, le=200)


class ScopedTerminalClose(BaseModel):
    scope_id: str = Field(min_length=1, max_length=64)
    force: bool = False


class ScopedTerminalResult(BaseModel):
    scope_id: str
    terminal: TerminalResponse


def _runtime_user_id(
    actor: ActorContext,
) -> str | None:
    if actor.server_mode:
        if not actor.actor_id:
            raise HTTPException(
                status_code=401,
                detail="Authenticated actor identity is required.",
            )
        return actor.actor_id

    return None


async def _require_scope(
    actor: ActorContext,
    *,
    scope_id: str,
    shell: str,
    process: bool = False,
    terminal: bool = False,
) -> tuple[ExecutionScope, Device]:
    async with SessionLocal() as session:
        scope = await session.get(
            ExecutionScope,
            scope_id,
        )

        if scope is None or not scope.is_active:
            raise HTTPException(
                status_code=404,
                detail="Execution scope not found or inactive.",
            )

        await require_or_claim_local(
            session,
            resource_kind="execution_scope",
            resource_id=scope.id,
            actor_id=actor.actor_id,
            client_id=actor.client_id,
            server_mode=actor.server_mode,
        )

        workspace = await session.get(
            ComputerWorkspace,
            scope.workspace_id,
        )

        if workspace is None or not workspace.is_active:
            raise HTTPException(
                status_code=409,
                detail="The execution scope workspace is missing or inactive.",
            )

        await require_or_claim_local(
            session,
            resource_kind="workspace",
            resource_id=workspace.id,
            actor_id=actor.actor_id,
            client_id=actor.client_id,
            server_mode=actor.server_mode,
        )

        if not workspace.read_enabled:
            raise HTTPException(
                status_code=403,
                detail="The execution scope workspace is not readable.",
            )

        if not workspace.write_enabled:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Interactive process/terminal execution requires a "
                    "write-enabled computer workspace."
                ),
            )

        device = await session.get(
            Device,
            scope.device_id,
        )

        if (
            device is None
            or not device.is_active
            or device.revoked_at is not None
        ):
            raise HTTPException(
                status_code=404,
                detail="The execution scope device is missing or revoked.",
            )

        if (
            actor.server_mode
            and device.owner_user_id != actor.actor_id
        ):
            raise HTTPException(
                status_code=404,
                detail="The execution scope device was not found.",
            )

        if shell not in set(scope_shells(scope)):
            raise HTTPException(
                status_code=403,
                detail=f"Shell {shell!r} is not allowed by this execution scope.",
            )

        capabilities = set(
            device_response(device).capabilities
        )

        if process:
            if not scope.process_enabled:
                raise HTTPException(
                    status_code=403,
                    detail="Process execution is disabled for this scope.",
                )

            if "process.runtime" not in capabilities:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The selected Device Agent does not advertise "
                        "process.runtime."
                    ),
                )

        if terminal:
            if not scope.terminal_enabled:
                raise HTTPException(
                    status_code=403,
                    detail="Interactive terminals are disabled for this scope.",
                )

            if "terminal.runtime" not in capabilities:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The selected Device Agent does not advertise "
                        "terminal.runtime."
                    ),
                )

    if not await device_connections.is_connected(device.id):
        raise HTTPException(
            status_code=409,
            detail="The selected Device Agent is not connected.",
        )

    return scope, device


def _path_module(value: str):
    if (
        re.match(r"^[A-Za-z]:[\\/]", value)
        or "\\" in value
    ):
        return ntpath

    return posixpath


def _runtime_within_scope(
    *,
    root: str,
    runtime_cwd: str | None,
) -> bool:
    if not runtime_cwd:
        return False

    path_module = _path_module(root)

    try:
        normal_root = path_module.normcase(
            path_module.abspath(
                path_module.normpath(root)
            )
        )
        normal_cwd = path_module.normcase(
            path_module.abspath(
                path_module.normpath(runtime_cwd)
            )
        )

        return (
            path_module.commonpath(
                [normal_root, normal_cwd]
            )
            == normal_root
        )
    except ValueError:
        return False


async def _require_process_in_scope(
    actor: ActorContext,
    process_id: str,
    scope_id: str,
):
    row = await process_runtime.get_process(
        process_id,
        user_id=_runtime_user_id(actor),
        server_mode=actor.server_mode,
    )

    scope, device = await _require_scope(
        actor,
        scope_id=scope_id,
        shell=row.shell,
        process=True,
    )

    if (
        row.device_id != device.id
        or not _runtime_within_scope(
            root=scope.device_root_path,
            runtime_cwd=row.cwd,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "The requested process does not belong to the selected "
                "execution scope."
            ),
        )

    return scope, row


async def _require_terminal_in_scope(
    actor: ActorContext,
    terminal_id: str,
    scope_id: str,
):
    row = await terminal_runtime.get_terminal(
        terminal_id,
        user_id=_runtime_user_id(actor),
        server_mode=actor.server_mode,
    )

    scope, device = await _require_scope(
        actor,
        scope_id=scope_id,
        shell=row.shell,
        terminal=True,
    )

    if (
        row.device_id != device.id
        or not _runtime_within_scope(
            root=scope.device_root_path,
            runtime_cwd=row.cwd,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "The requested terminal does not belong to the selected "
                "execution scope."
            ),
        )

    return scope, row



async def _create_ui_audit(
    actor: ActorContext,
    *,
    tool_name: str,
    arguments: dict,
):
    async with SessionLocal() as session:
        return await create_tool_audit(
            session,
            conversation_id=None,
            tool_name=tool_name,
            permission_mode="explicit_user_action",
            arguments=arguments,
            configured_permission="explicit_user_action",
            session_grant_used=False,
            session_grant_available=False,
            actor_id=actor.actor_id,
            client_id=actor.client_id,
        )


async def _complete_ui_audit(
    audit_id: str,
    *,
    status: str,
    result_preview: str | None = None,
    error: str | None = None,
):
    async with SessionLocal() as session:
        await update_tool_audit(
            session,
            audit_id,
            status=status,
            result_preview=result_preview,
            error=error,
            completed=True,
        )



def _runtime_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))

    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))

    if isinstance(exc, ConnectionError):
        return HTTPException(status_code=409, detail=str(exc))

    return HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/processes",
    response_model=ScopedProcessResult,
)
async def start_scoped_process(
    payload: ScopedProcessStart,
    actor: ActorContext = Depends(require_actor),
):
    audit = await _create_ui_audit(
        actor,
        tool_name="ui_run_device_command",
        arguments=payload.model_dump(),
    )

    scope, device = await _require_scope(
        actor,
        scope_id=payload.scope_id,
        shell=payload.shell,
        process=True,
    )

    try:
        cwd = device_scoped_path(
            scope.device_root_path,
            payload.relative_cwd,
        )

        row = await process_runtime.start_process(
            user_id=_runtime_user_id(actor),
            device_id=device.id,
            shell=payload.shell,
            command=payload.command,
            cwd=cwd,
            mode=payload.mode,
            timeout_seconds=payload.timeout_seconds,
            wait_for_start=True,
            scope_root=scope.device_root_path,
        )
    except (
        PermissionError,
        LookupError,
        ConnectionError,
        RuntimeError,
        ValueError,
    ) as exc:
        await _complete_ui_audit(
            audit.id,
            status="failed",
            error=str(exc),
        )
        raise _runtime_error(exc) from exc

    await _complete_ui_audit(
        audit.id,
        status="completed",
        result_preview=(
            "Process launch accepted: "
            f"{row.id} · {row.status}"
        ),
    )

    return ScopedProcessResult(
        scope_id=scope.id,
        process=process_response(row),
    )


@router.post(
    "/processes/{process_id}/terminate",
    response_model=ScopedProcessResult,
)
async def terminate_scoped_process(
    process_id: str,
    payload: ScopedProcessMutation,
    actor: ActorContext = Depends(require_actor),
):
    audit = await _create_ui_audit(
        actor,
        tool_name="ui_stop_device_process",
        arguments={
            "scope_id": payload.scope_id,
            "process_id": process_id,
            "force": payload.force,
        },
    )

    scope, _row = await _require_process_in_scope(
        actor,
        process_id,
        payload.scope_id,
    )

    try:
        row = await process_runtime.terminate_process(
            process_id,
            user_id=_runtime_user_id(actor),
            server_mode=actor.server_mode,
            force=payload.force,
        )
    except (LookupError, RuntimeError) as exc:
        await _complete_ui_audit(
            audit.id,
            status="failed",
            error=str(exc),
        )
        raise _runtime_error(exc) from exc

    await _complete_ui_audit(
        audit.id,
        status="completed",
        result_preview=(
            "Process termination requested: "
            f"{row.id} · {row.status}"
        ),
    )

    return ScopedProcessResult(
        scope_id=scope.id,
        process=process_response(row),
    )


@router.post(
    "/terminals",
    response_model=ScopedTerminalResult,
)
async def open_scoped_terminal(
    payload: ScopedTerminalOpen,
    actor: ActorContext = Depends(require_actor),
):
    audit = await _create_ui_audit(
        actor,
        tool_name="ui_open_device_terminal",
        arguments=payload.model_dump(),
    )

    scope, device = await _require_scope(
        actor,
        scope_id=payload.scope_id,
        shell=payload.shell,
        terminal=True,
    )

    try:
        cwd = device_scoped_path(
            scope.device_root_path,
            payload.relative_cwd,
        )

        row = await terminal_runtime.open_terminal(
            user_id=_runtime_user_id(actor),
            device_id=device.id,
            shell=payload.shell,
            cwd=cwd,
            cols=payload.cols,
            rows=payload.rows,
            wait_for_start=True,
            scope_root=scope.device_root_path,
        )
    except (
        PermissionError,
        LookupError,
        ConnectionError,
        RuntimeError,
        ValueError,
    ) as exc:
        await _complete_ui_audit(
            audit.id,
            status="failed",
            error=str(exc),
        )
        raise _runtime_error(exc) from exc

    await _complete_ui_audit(
        audit.id,
        status="completed",
        result_preview=(
            "Terminal opened: "
            f"{row.id} · {row.status}"
        ),
    )

    return ScopedTerminalResult(
        scope_id=scope.id,
        terminal=terminal_response(row),
    )


@router.post(
    "/terminals/{terminal_id}/input",
    response_model=ScopedTerminalResult,
)
async def scoped_terminal_input(
    terminal_id: str,
    payload: ScopedTerminalInput,
    actor: ActorContext = Depends(require_actor),
):
    scope, _row = await _require_terminal_in_scope(
        actor,
        terminal_id,
        payload.scope_id,
    )

    try:
        row = await terminal_runtime.write_input(
            terminal_id,
            user_id=_runtime_user_id(actor),
            server_mode=actor.server_mode,
            data=payload.data,
        )
    except (
        LookupError,
        ConnectionError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise _runtime_error(exc) from exc

    return ScopedTerminalResult(
        scope_id=scope.id,
        terminal=terminal_response(row),
    )


@router.post(
    "/terminals/{terminal_id}/resize",
    response_model=ScopedTerminalResult,
)
async def scoped_terminal_resize(
    terminal_id: str,
    payload: ScopedTerminalResize,
    actor: ActorContext = Depends(require_actor),
):
    scope, _row = await _require_terminal_in_scope(
        actor,
        terminal_id,
        payload.scope_id,
    )

    try:
        row = await terminal_runtime.resize_terminal(
            terminal_id,
            user_id=_runtime_user_id(actor),
            server_mode=actor.server_mode,
            cols=payload.cols,
            rows=payload.rows,
        )
    except (
        LookupError,
        ConnectionError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise _runtime_error(exc) from exc

    return ScopedTerminalResult(
        scope_id=scope.id,
        terminal=terminal_response(row),
    )


@router.post(
    "/terminals/{terminal_id}/close",
    response_model=ScopedTerminalResult,
)
async def scoped_terminal_close(
    terminal_id: str,
    payload: ScopedTerminalClose,
    actor: ActorContext = Depends(require_actor),
):
    audit = await _create_ui_audit(
        actor,
        tool_name="ui_close_device_terminal",
        arguments={
            "scope_id": payload.scope_id,
            "terminal_id": terminal_id,
            "force": payload.force,
        },
    )

    scope, _row = await _require_terminal_in_scope(
        actor,
        terminal_id,
        payload.scope_id,
    )

    try:
        row = await terminal_runtime.close_terminal(
            terminal_id,
            user_id=_runtime_user_id(actor),
            server_mode=actor.server_mode,
            force=payload.force,
        )
    except (LookupError, RuntimeError) as exc:
        await _complete_ui_audit(
            audit.id,
            status="failed",
            error=str(exc),
        )
        raise _runtime_error(exc) from exc

    await _complete_ui_audit(
        audit.id,
        status="completed",
        result_preview=(
            "Terminal close requested: "
            f"{row.id} · {row.status}"
        ),
    )

    return ScopedTerminalResult(
        scope_id=scope.id,
        terminal=terminal_response(row),
    )
