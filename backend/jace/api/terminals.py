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
    TerminalOutputChunk,
    TerminalSession,
)
from jace.terminal_runtime import terminal_runtime


router = APIRouter(
    prefix="/terminals",
    tags=["terminals"],
)


class TerminalOpenRequest(BaseModel):
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
    cwd: str | None = Field(
        default=None,
        max_length=2000,
    )
    cols: int = Field(
        default=120,
        ge=20,
        le=400,
    )
    rows: int = Field(
        default=30,
        ge=5,
        le=200,
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


class TerminalInputRequest(BaseModel):
    data: str = Field(
        max_length=20000,
    )


class TerminalResizeRequest(BaseModel):
    cols: int = Field(
        ge=20,
        le=400,
    )
    rows: int = Field(
        ge=5,
        le=200,
    )


class TerminalCloseRequest(BaseModel):
    force: bool = False


class TerminalResponse(BaseModel):
    id: str
    device_id: str
    shell: str
    cwd: str | None
    cols: int
    rows: int
    status: str
    pid: int | None
    backend: str | None
    exit_code: int | None
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
    close_requested_at: str | None
    lost_at: str | None


class TerminalListResponse(BaseModel):
    terminals: list[TerminalResponse]


class TerminalOutputItem(BaseModel):
    sequence: int
    agent_sequence: int
    text: str
    byte_count: int
    created_at: str


class TerminalOutputResponse(BaseModel):
    terminal_id: str
    output: list[TerminalOutputItem]
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
    row: TerminalSession,
) -> TerminalResponse:
    return TerminalResponse(
        id=row.id,
        device_id=row.device_id,
        shell=row.shell,
        cwd=row.cwd,
        cols=row.cols,
        rows=row.rows,
        status=row.status,
        pid=row.pid,
        backend=row.backend,
        exit_code=row.exit_code,
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
        close_requested_at=(
            row.close_requested_at.isoformat()
            if row.close_requested_at
            else None
        ),
        lost_at=(
            row.lost_at.isoformat()
            if row.lost_at
            else None
        ),
    )


def _output_item(
    row: TerminalOutputChunk,
) -> TerminalOutputItem:
    return TerminalOutputItem(
        sequence=row.sequence,
        agent_sequence=row.agent_sequence,
        text=row.text,
        byte_count=row.byte_count,
        created_at=row.created_at.isoformat(),
    )


@router.post(
    "",
    response_model=TerminalResponse,
)
async def open_terminal(
    payload: TerminalOpenRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await terminal_runtime.open_terminal(
            user_id=user_id,
            device_id=payload.device_id,
            shell=payload.shell,
            cwd=payload.cwd,
            cols=payload.cols,
            rows=payload.rows,
            project_id=payload.project_id,
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            conversation_id=(
                payload.conversation_id
            ),
            wait_for_start=True,
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
    response_model=TerminalListResponse,
)
async def list_terminals(
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

    rows = await terminal_runtime.list_terminals(
        user_id=user_id,
        server_mode=(
            settings.mode
            == "server"
        ),
        device_id=device_id,
        status=status,
        limit=limit,
    )

    return TerminalListResponse(
        terminals=[
            _response(row)
            for row in rows
        ]
    )


@router.get(
    "/{terminal_id}",
    response_model=TerminalResponse,
)
async def get_terminal(
    terminal_id: str,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await terminal_runtime.get_terminal(
            terminal_id,
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
    "/{terminal_id}/output",
    response_model=TerminalOutputResponse,
)
async def get_terminal_output(
    terminal_id: str,
    request: Request,
    after_sequence: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=1000,
        ge=1,
        le=4000,
    ),
):
    user_id = _user_id(
        request
    )

    try:
        rows = await terminal_runtime.output(
            terminal_id,
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

    return TerminalOutputResponse(
        terminal_id=terminal_id,
        output=[
            _output_item(row)
            for row in rows
        ],
        count=len(rows),
        next_sequence=(
            rows[-1].sequence
            if rows
            else after_sequence
        ),
    )


@router.post(
    "/{terminal_id}/input",
    response_model=TerminalResponse,
)
async def terminal_input(
    terminal_id: str,
    payload: TerminalInputRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await terminal_runtime.write_input(
            terminal_id,
            user_id=user_id,
            server_mode=(
                settings.mode
                == "server"
            ),
            data=payload.data,
        )
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
    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return _response(
        row
    )


@router.post(
    "/{terminal_id}/resize",
    response_model=TerminalResponse,
)
async def terminal_resize(
    terminal_id: str,
    payload: TerminalResizeRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await terminal_runtime.resize_terminal(
            terminal_id,
            user_id=user_id,
            server_mode=(
                settings.mode
                == "server"
            ),
            cols=payload.cols,
            rows=payload.rows,
        )
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
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return _response(
        row
    )


@router.post(
    "/{terminal_id}/close",
    response_model=TerminalResponse,
)
async def terminal_close(
    terminal_id: str,
    payload: TerminalCloseRequest,
    request: Request,
):
    user_id = _user_id(
        request
    )

    try:
        row = await terminal_runtime.close_terminal(
            terminal_id,
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
