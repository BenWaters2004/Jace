from fastapi import APIRouter, HTTPException

from jace.computer.security import ComputerPathError
from jace.computer.service import (
    create_command_preset,
    create_workspace,
    delete_command_preset,
    delete_workspace_configuration,
    get_command_preset,
    get_workspace,
    list_workspaces,
    parse_arguments_json,
    update_command_preset,
    update_workspace,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.schemas import (
    ComputerCommandPresetCreate,
    ComputerCommandPresetResponse,
    ComputerCommandPresetUpdate,
    ComputerStatusResponse,
    ComputerWorkspaceCreate,
    ComputerWorkspaceListResponse,
    ComputerWorkspaceResponse,
    ComputerWorkspaceUpdate,
)


router = APIRouter(prefix="/computer", tags=["computer"])


def command_response(command) -> ComputerCommandPresetResponse:
    return ComputerCommandPresetResponse(
        id=command.id,
        workspace_id=command.workspace_id,
        label=command.label,
        executable=command.executable,
        arguments=parse_arguments_json(command.arguments_json),
        relative_cwd=command.relative_cwd,
        timeout_seconds=command.timeout_seconds,
        is_active=command.is_active,
        created_at=command.created_at,
        updated_at=command.updated_at,
    )


def workspace_response(workspace) -> ComputerWorkspaceResponse:
    return ComputerWorkspaceResponse(
        id=workspace.id,
        label=workspace.label,
        root_path=workspace.root_path,
        read_enabled=workspace.read_enabled,
        write_enabled=workspace.write_enabled,
        is_active=workspace.is_active,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        commands=[command_response(command) for command in workspace.commands],
    )


@router.get("/status", response_model=ComputerStatusResponse)
async def computer_status():
    async with SessionLocal() as session:
        workspaces = await list_workspaces(session, active_only=False)

    return ComputerStatusResponse(
        enabled=settings.computer_enabled,
        workspace_count=len(workspaces),
        active_workspace_count=sum(1 for item in workspaces if item.is_active),
        command_preset_count=sum(len(item.commands) for item in workspaces),
        sensitive_files_allowed=settings.computer_allow_sensitive_files,
    )


@router.get("/workspaces", response_model=ComputerWorkspaceListResponse)
async def computer_workspaces():
    async with SessionLocal() as session:
        workspaces = await list_workspaces(session, active_only=False)
    return ComputerWorkspaceListResponse(
        enabled=settings.computer_enabled,
        workspaces=[workspace_response(item) for item in workspaces],
    )


@router.post("/workspaces", response_model=ComputerWorkspaceResponse)
async def add_computer_workspace(request: ComputerWorkspaceCreate):
    if not settings.computer_enabled:
        raise HTTPException(status_code=409, detail="Computer access is disabled by backend configuration.")

    async with SessionLocal() as session:
        try:
            workspace = await create_workspace(
                session,
                label=request.label,
                root_path=request.root_path,
                read_enabled=request.read_enabled,
                write_enabled=request.write_enabled,
            )
        except (ValueError, ComputerPathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace_response(workspace)


@router.patch("/workspaces/{workspace_id}", response_model=ComputerWorkspaceResponse)
async def patch_computer_workspace(workspace_id: str, request: ComputerWorkspaceUpdate):
    async with SessionLocal() as session:
        workspace = await get_workspace(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        try:
            workspace = await update_workspace(
                session,
                workspace,
                label=request.label,
                root_path=request.root_path,
                read_enabled=request.read_enabled,
                write_enabled=request.write_enabled,
                is_active=request.is_active,
            )
        except (ValueError, ComputerPathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace_response(workspace)


@router.delete("/workspaces/{workspace_id}")
async def remove_computer_workspace(workspace_id: str):
    async with SessionLocal() as session:
        workspace = await get_workspace(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        await delete_workspace_configuration(session, workspace)
    return {"success": True}


@router.post(
    "/workspaces/{workspace_id}/commands",
    response_model=ComputerCommandPresetResponse,
)
async def add_command(workspace_id: str, request: ComputerCommandPresetCreate):
    async with SessionLocal() as session:
        workspace = await get_workspace(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        try:
            command = await create_command_preset(
                session,
                workspace,
                label=request.label,
                executable=request.executable,
                arguments=request.arguments,
                relative_cwd=request.relative_cwd,
                timeout_seconds=request.timeout_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return command_response(command)


@router.patch("/commands/{command_id}", response_model=ComputerCommandPresetResponse)
async def patch_command(command_id: str, request: ComputerCommandPresetUpdate):
    async with SessionLocal() as session:
        command = await get_command_preset(session, command_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Command preset not found.")
        try:
            command = await update_command_preset(
                session,
                command,
                label=request.label,
                executable=request.executable,
                arguments=request.arguments,
                relative_cwd=request.relative_cwd,
                timeout_seconds=request.timeout_seconds,
                is_active=request.is_active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return command_response(command)


@router.delete("/commands/{command_id}")
async def remove_command(command_id: str):
    async with SessionLocal() as session:
        command = await get_command_preset(session, command_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Command preset not found.")
        await delete_command_preset(session, command)
    return {"success": True}
