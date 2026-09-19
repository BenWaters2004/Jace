from __future__ import annotations

from typing import Literal

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)
from pydantic import BaseModel, Field

from jace.config import settings
from jace.db.models import (
    ProcessOutputChunk,
    ProcessRun,
)
from jace.process_runtime import process_runtime


router = APIRouter(
    prefix="/processes",
    tags=["processes"],
)


class ProcessStartRequest(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=64,
    )
    shell: Literal[
        "powershell",
        "cmd",
        "wsl",
        "bash",
    ]
    command: str = Field(
        min_length=1,
        max_length=50000,
    )
    cwd: str | None = Field(
        default=None,
        max_length=2000,
    )
    mode: Literal[
        "foreground",
        "background",
    ] = "foreground"
    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86400,
    )
    wait_for_exit: bool = False
    wait_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
    )
    project_id: str | None = Field(
        default=None,
        max_length=100,
    )
    task_id: str | None = Field(
        default=None,
        max_length=100,
    )
    agent_id: str | None = Field(
        default=None,
        max_length=100,
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=100,
    )


class ProcessTerminateRequest(BaseModel):
    force: bool = False


class ProcessResponse(BaseModel):
    id: str
    device_id: str
    mode: str
    shell: str
    command_preview: str
    command_sha256: str
    cwd: str | None
    status: str
    pid: int | None
    exit_code: int | None
    timeout_seconds: int | None
    output_bytes: int
    output_truncated: bool
    last_agent_sequence: int
    error: str | None
    project_id: str | None
    task_id: str | None
    agent_id: str | None
    conversation_id: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    cancel_requested_at: str | None
    lost_at: str | None


class ProcessListResponse(BaseModel):
    processes: list[ProcessResponse]


class ProcessOutputItem(BaseModel):
    sequence: int
    agent_sequence: int
    stream: str
    text: str
    byte_count: int
    created_at: str


class ProcessOutputResponse(BaseModel):
    process_id: str
    output: list[ProcessOutputItem]
    count: int
    next_sequence: int


def _user_id(
    request: Request,
) -> str | None:
    if settings.mode != "server":
        return None

    user_id = getattr(
        request.state,
        "auth_user_id",
        None,
    )

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    return user_id


def _response(
    row: ProcessRun,
) -> ProcessResponse:
    return ProcessResponse(
        id=row.id,
        device_id=row.device_id,
        mode=row.mode,
        shell=row.shell,
        command_preview=row.command_preview,
        command_sha256=row.command_sha256,
        cwd=row.cwd,
        status=row.status,
        pid=row.pid,
        exit_code=row.exit_code,
        timeout_seconds=row.timeout_seconds,
        output_bytes=row.output_bytes,
        output_truncated=bool(
            row.output_truncated
        ),
        last_agent_sequence=(
            row.last_agent_sequence
        ),
        error=row.error,
        project_id=row.project_id,
        task_id=row.task_id,
        agent_id=row.agent_id,
        conversation_id=row.conversation_id,
        created_at=row.created_at.isoformat(),
        started_at=(
            row.started_at.isoformat()
            if row.started_at
            else None
        ),
        completed_at=(
            row.completed_at.isoformat()
            if row.completed_at
            else None
        ),
        cancel_requested_at=(
            row.cancel_requested_at.isoformat()
            if row.cancel_requested_at
            else None
        ),
        lost_at=(
            row.lost_at.isoformat()
            if row.lost_at
            else None
        ),
    )


def _output_item(
    row: ProcessOutputChunk,
) -> ProcessOutputItem:
    return ProcessOutputItem(
        sequence=row.sequence,
        agent_sequence=row.agent_sequence,
        stream=row.stream,
        text=row.text,
        byte_count=row.byte_count,
        created_at=row.created_at.isoformat(),
    )


@router.post(
    "",
    response_model=ProcessResponse,
)
async def start_process(
    payload: ProcessStartRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await process_runtime.start_process(
            user_id=user_id,
            device_id=payload.device_id,
            shell=payload.shell,
            command=payload.command,
            cwd=payload.cwd,
            mode=payload.mode,
            timeout_seconds=(
                payload.timeout_seconds
            ),
            project_id=payload.project_id,
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            conversation_id=(
                payload.conversation_id
            ),
            wait_for_start=True,
        )

        if payload.wait_for_exit:
            row = await process_runtime.wait_for_exit(
                row.id,
                user_id=user_id,
                server_mode=(
                    settings.mode
                    == "server"
                ),
                timeout_seconds=(
                    payload
                    .wait_timeout_seconds
                ),
            )

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return _response(
        row
    )


@router.get(
    "",
    response_model=ProcessListResponse,
)
async def list_processes(
    request: Request,
    device_id: str | None = None,
    status: str | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
):
    user_id = _user_id(
        request
    )

    rows = await process_runtime.list_processes(
        user_id=user_id,
        server_mode=(
            settings.mode
            == "server"
        ),
        device_id=device_id,
        status=status,
        limit=limit,
    )

    return ProcessListResponse(
        processes=[
            _response(row)
            for row in rows
        ]
    )


@router.get(
    "/{process_id}",
    response_model=ProcessResponse,
)
async def get_process(
    process_id: str,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await process_runtime.get_process(
            process_id,
            user_id=user_id,
            server_mode=(
                settings.mode
                == "server"
            ),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return _response(
        row
    )


@router.get(
    "/{process_id}/output",
    response_model=ProcessOutputResponse,
)
async def get_process_output(
    process_id: str,
    request: Request,
    after_sequence: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
    ),
):
    user_id = _user_id(
        request
    )

    try:
        rows = await process_runtime.output(
            process_id,
            user_id=user_id,
            server_mode=(
                settings.mode
                == "server"
            ),
            after_sequence=after_sequence,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    next_sequence = (
        rows[-1].sequence
        if rows
        else after_sequence
    )

    return ProcessOutputResponse(
        process_id=process_id,
        output=[
            _output_item(row)
            for row in rows
        ],
        count=len(rows),
        next_sequence=next_sequence,
    )


@router.post(
    "/{process_id}/terminate",
    response_model=ProcessResponse,
)
async def terminate_process(
    process_id: str,
    payload: ProcessTerminateRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await process_runtime.terminate_process(
            process_id,
            user_id=user_id,
            server_mode=(
                settings.mode
                == "server"
            ),
            force=payload.force,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return _response(
        row
    )
