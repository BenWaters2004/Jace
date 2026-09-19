from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from jace.auth.schemas import (
    AuthBootstrapRequest,
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthSessionListResponse,
    AuthSessionResponse,
    AuthStatusResponse,
    AuthTokenResponse,
    AuthUserResponse,
)
from jace.auth.service import (
    authenticate_password,
    create_initial_admin,
    issue_session,
    list_user_sessions,
    revoke_session,
    rotate_refresh_token,
    user_count,
    user_response,
)
from jace.config import settings
from jace.database import SessionLocal
from jace.db.models import AuthUser


router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_required() -> bool:
    return settings.mode == "server" and settings.auth_enabled


def _token_response(user: AuthUser, issued) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        access_expires_at=issued.row.access_expires_at,
        refresh_expires_at=issued.row.refresh_expires_at,
        session_id=issued.row.id,
        user=user_response(user),
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status():
    async with SessionLocal() as session:
        count = await user_count(session)

    required = _auth_required()
    return AuthStatusResponse(
        mode=settings.mode,
        auth_required=required,
        bootstrap_required=required and count == 0,
        bootstrap_available=bool(settings.auth_bootstrap_token),
    )


@router.post(
    "/bootstrap",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bootstrap(
    payload: AuthBootstrapRequest,
    bootstrap_token: str | None = Header(
        default=None,
        alias="X-Jace-Bootstrap-Token",
    ),
):
    if not _auth_required():
        raise HTTPException(
            status_code=400,
            detail="Bootstrap is only used when server-mode authentication is enabled.",
        )

    expected = settings.auth_bootstrap_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Jace Core has no bootstrap token configured.",
        )

    if bootstrap_token is None or not hmac.compare_digest(
        bootstrap_token.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(status_code=403, detail="Invalid bootstrap token.")

    async with SessionLocal() as session:
        try:
            user = await create_initial_admin(
                session,
                email=payload.email,
                display_name=payload.display_name,
                password=payload.password,
            )
            issued = await issue_session(
                session,
                user=user,
                client_id=payload.client_id,
                client_name=payload.client_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _token_response(user, issued)


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: AuthLoginRequest):
    if not _auth_required():
        raise HTTPException(status_code=400, detail="Login is not required in local mode.")

    async with SessionLocal() as session:
        try:
            user = await authenticate_password(
                session,
                email=payload.email,
                password=payload.password,
            )
        except ValueError:
            user = None

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid email address or password.",
            )

        issued = await issue_session(
            session,
            user=user,
            client_id=payload.client_id,
            client_name=payload.client_name,
        )

    return _token_response(user, issued)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh(payload: AuthRefreshRequest):
    if not _auth_required():
        raise HTTPException(
            status_code=400,
            detail="Token refresh is not required in local mode.",
        )

    async with SessionLocal() as session:
        result = await rotate_refresh_token(
            session,
            refresh_token=payload.refresh_token,
            client_id=payload.client_id,
        )

    if result is None:
        raise HTTPException(
            status_code=401,
            detail="Refresh token is invalid or expired.",
        )

    user, issued = result
    return _token_response(user, issued)


@router.get("/me", response_model=AuthUserResponse)
async def me(request: Request):
    if not _auth_required():
        return AuthUserResponse(
            id="local",
            email=None,
            display_name="Local User",
            is_active=True,
            is_admin=True,
            local=True,
        )

    user_id = request.state.auth_user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    async with SessionLocal() as session:
        result = await session.execute(select(AuthUser).where(AuthUser.id == user_id))
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User account is unavailable.")

    return user_response(user)


@router.post("/logout")
async def logout(request: Request):
    if not _auth_required():
        return {"success": True}

    user_id = request.state.auth_user_id
    session_id = request.state.auth_session_id

    if not user_id or not session_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    async with SessionLocal() as session:
        await revoke_session(session, session_id, user_id)

    return {"success": True}


@router.get("/sessions", response_model=AuthSessionListResponse)
async def sessions(request: Request):
    if not _auth_required():
        return AuthSessionListResponse(sessions=[])

    user_id = request.state.auth_user_id
    current_id = request.state.auth_session_id
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    async with SessionLocal() as session:
        rows = await list_user_sessions(session, user_id)

    return AuthSessionListResponse(
        sessions=[
            AuthSessionResponse(
                id=row.id,
                client_id=row.client_id,
                client_name=row.client_name,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                access_expires_at=row.access_expires_at,
                refresh_expires_at=row.refresh_expires_at,
                revoked_at=row.revoked_at,
                current=row.id == current_id,
            )
            for row in rows
        ]
    )


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str, request: Request):
    if not _auth_required():
        return {"success": True}

    user_id = request.state.auth_user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    async with SessionLocal() as session:
        removed = await revoke_session(session, session_id, user_id)

    if not removed:
        raise HTTPException(status_code=404, detail="Session not found.")

    return {"success": True}
