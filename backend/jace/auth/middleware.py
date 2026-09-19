from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from jace.auth.service import authenticate_access_token
from jace.config import settings
from jace.database import SessionLocal


_PUBLIC_PATHS = {
    "/",
    "/health",
    "/runtime-info",
    "/auth/status",
    "/auth/bootstrap",
    "/auth/login",
    "/auth/refresh",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce opaque bearer sessions when Jace Core runs in server mode."""

    async def dispatch(self, request: Request, call_next):
        request.state.auth_user_id = None
        request.state.auth_session_id = None
        request.state.auth_mode = "local"

        if settings.mode != "server" or not settings.auth_enabled:
            return await call_next(request)

        request.state.auth_mode = "server"

        if request.method == "OPTIONS" or request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")

        if scheme.lower() != "bearer" or not token.strip():
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        async with SessionLocal() as session:
            principal = await authenticate_access_token(session, token.strip())

        if principal is None:
            return JSONResponse(
                {"detail": "Authentication token is invalid or expired."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        user, auth_session = principal
        request.state.auth_user_id = user.id
        request.state.auth_session_id = auth_session.id

        return await call_next(request)
