from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
)
from pydantic import BaseModel, Field

from jace.database import SessionLocal
from jace.execution_scopes import (
    create_execution_scope,
    delete_execution_scope,
    get_execution_scope,
    list_execution_scopes,
    update_execution_scope,
)
from jace.execution_scopes.service import (
    scope_shells,
)


router = APIRouter(
    prefix="/execution/scopes",
    tags=["execution"],
)


class ExecutionScopeCreate(BaseModel):
    label: str = Field(
        min_length=1,
        max_length=160,
    )
    device_id: str = Field(
        min_length=1,
        max_length=64,
    )
    workspace_id: str = Field(
        min_length=1,
        max_length=64,
    )
    device_root_path: str | None = Field(
        default=None,
        max_length=1600,
    )
    allowed_shells: list[str] = Field(
        default_factory=lambda: [
            "powershell",
        ],
        min_length=1,
        max_length=4,
    )
    process_enabled: bool = True
    terminal_enabled: bool = True


class ExecutionScopeUpdate(BaseModel):
    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    device_root_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1600,
    )
    allowed_shells: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=4,
    )
    process_enabled: bool | None = None
    terminal_enabled: bool | None = None
    is_active: bool | None = None


class ExecutionScopeResponse(BaseModel):
    id: str
    label: str
    device_id: str
    workspace_id: str
    device_root_path: str
    allowed_shells: list[str]
    process_enabled: bool
    terminal_enabled: bool
    is_active: bool
    created_at: str
    updated_at: str


class ExecutionScopeListResponse(BaseModel):
    scopes: list[
        ExecutionScopeResponse
    ]


def _response(
    row,
) -> ExecutionScopeResponse:
    return ExecutionScopeResponse(
        id=row.id,
        label=row.label,
        device_id=row.device_id,
        workspace_id=row.workspace_id,
        device_root_path=(
            row.device_root_path
        ),
        allowed_shells=scope_shells(
            row
        ),
        process_enabled=bool(
            row.process_enabled
        ),
        terminal_enabled=bool(
            row.terminal_enabled
        ),
        is_active=bool(
            row.is_active
        ),
        created_at=(
            row.created_at.isoformat()
        ),
        updated_at=(
            row.updated_at.isoformat()
        ),
    )


@router.get(
    "",
    response_model=(
        ExecutionScopeListResponse
    ),
)
async def execution_scopes(
    active_only: bool = True,
):
    async with SessionLocal() as session:
        rows = await list_execution_scopes(
            session,
            active_only=active_only,
        )

    return ExecutionScopeListResponse(
        scopes=[
            _response(
                row
            )
            for row in rows
        ]
    )


@router.post(
    "",
    response_model=(
        ExecutionScopeResponse
    ),
)
async def create_scope(
    payload: ExecutionScopeCreate,
):
    try:
        async with SessionLocal() as session:
            row = await create_execution_scope(
                session,
                label=payload.label,
                device_id=payload.device_id,
                workspace_id=(
                    payload.workspace_id
                ),
                device_root_path=(
                    payload.device_root_path
                ),
                allowed_shells=(
                    payload.allowed_shells
                ),
                process_enabled=(
                    payload.process_enabled
                ),
                terminal_enabled=(
                    payload.terminal_enabled
                ),
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(
                exc
            ),
        ) from exc

    return _response(
        row
    )


@router.patch(
    "/{scope_id}",
    response_model=(
        ExecutionScopeResponse
    ),
)
async def update_scope(
    scope_id: str,
    payload: ExecutionScopeUpdate,
):
    async with SessionLocal() as session:
        row = await get_execution_scope(
            session,
            scope_id,
        )

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Execution scope not found."
                ),
            )

        try:
            row = await update_execution_scope(
                session,
                row,
                label=payload.label,
                device_root_path=(
                    payload.device_root_path
                ),
                allowed_shells=(
                    payload.allowed_shells
                ),
                process_enabled=(
                    payload.process_enabled
                ),
                terminal_enabled=(
                    payload.terminal_enabled
                ),
                is_active=(
                    payload.is_active
                ),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(
                    exc
                ),
            ) from exc

    return _response(
        row
    )


@router.delete(
    "/{scope_id}",
)
async def delete_scope(
    scope_id: str,
):
    async with SessionLocal() as session:
        row = await get_execution_scope(
            session,
            scope_id,
        )

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Execution scope not found."
                ),
            )

        await delete_execution_scope(
            session,
            row,
        )

    return {
        "success": True,
    }
