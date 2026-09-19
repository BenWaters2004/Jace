from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.config import settings
from jace.db.models import AuthSession, AuthUser, utc_now

_password_hasher = PasswordHasher()


@dataclass(slots=True)
class IssuedSession:
    row: AuthSession
    access_token: str
    refresh_token: str


def _normalise_email(value: str) -> str:
    email = value.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return email


def _normalise_display_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Display name is required.")
    return name


def _validate_password(password: str) -> None:
    if len(password) < settings.auth_password_min_length:
        raise ValueError(
            f"Password must be at least {settings.auth_password_min_length} characters."
        )


def _hash_password(password: str) -> str:
    _validate_password(password)
    return _password_hasher.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_access_token() -> str:
    return "jace_at_" + secrets.token_urlsafe(48)


def _new_refresh_token() -> str:
    return "jace_rt_" + secrets.token_urlsafe(64)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def user_response(user: AuthUser):
    from jace.auth.schemas import AuthUserResponse

    return AuthUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        local=False,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AuthUser))
    return int(result.scalar_one())


async def create_initial_admin(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    password: str,
) -> AuthUser:
    if await user_count(session) != 0:
        raise ValueError("Jace Core already has a user account.")

    user = AuthUser(
        email=_normalise_email(email),
        display_name=_normalise_display_name(display_name),
        password_hash=_hash_password(password),
        is_active=True,
        is_admin=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_password(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> AuthUser | None:
    normalised = _normalise_email(email)
    result = await session.execute(
        select(AuthUser).where(AuthUser.email == normalised)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not _verify_password(user.password_hash, password):
        return None

    if _password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _password_hasher.hash(password)

    user.last_login_at = utc_now()
    user.updated_at = utc_now()
    await session.commit()
    await session.refresh(user)
    return user


async def issue_session(
    session: AsyncSession,
    *,
    user: AuthUser,
    client_id: str,
    client_name: str | None,
) -> IssuedSession:
    now = utc_now()
    access_token = _new_access_token()
    refresh_token = _new_refresh_token()

    row = AuthSession(
        user_id=user.id,
        access_token_hash=_hash_token(access_token),
        refresh_token_hash=_hash_token(refresh_token),
        client_id=client_id.strip(),
        client_name=(client_name.strip() if client_name else None),
        access_expires_at=now + timedelta(minutes=settings.auth_access_token_minutes),
        refresh_expires_at=now + timedelta(days=settings.auth_refresh_token_days),
        last_seen_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return IssuedSession(
        row=row,
        access_token=access_token,
        refresh_token=refresh_token,
    )


async def authenticate_access_token(
    session: AsyncSession,
    token: str,
) -> tuple[AuthUser, AuthSession] | None:
    token_hash = _hash_token(token)
    result = await session.execute(
        select(AuthSession, AuthUser)
        .join(AuthUser, AuthUser.id == AuthSession.user_id)
        .where(AuthSession.access_token_hash == token_hash)
    )
    row = result.first()
    if row is None:
        return None

    auth_session, user = row
    now = utc_now()

    if auth_session.revoked_at is not None:
        return None
    if _as_utc(auth_session.access_expires_at) <= now:
        return None
    if not user.is_active:
        return None

    return user, auth_session


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    refresh_token: str,
    client_id: str,
) -> tuple[AuthUser, IssuedSession] | None:
    token_hash = _hash_token(refresh_token)
    result = await session.execute(
        select(AuthSession, AuthUser)
        .join(AuthUser, AuthUser.id == AuthSession.user_id)
        .where(AuthSession.refresh_token_hash == token_hash)
    )
    found = result.first()
    if found is None:
        return None

    auth_session, user = found
    now = utc_now()

    if auth_session.revoked_at is not None:
        return None
    if _as_utc(auth_session.refresh_expires_at) <= now:
        return None
    if not user.is_active:
        return None
    if auth_session.client_id != client_id.strip():
        return None

    access_token = _new_access_token()
    next_refresh = _new_refresh_token()

    auth_session.access_token_hash = _hash_token(access_token)
    auth_session.refresh_token_hash = _hash_token(next_refresh)
    auth_session.access_expires_at = now + timedelta(
        minutes=settings.auth_access_token_minutes
    )
    auth_session.refresh_expires_at = now + timedelta(
        days=settings.auth_refresh_token_days
    )
    auth_session.last_seen_at = now

    await session.commit()
    await session.refresh(auth_session)

    return (
        user,
        IssuedSession(
            row=auth_session,
            access_token=access_token,
            refresh_token=next_refresh,
        ),
    )


async def revoke_session(session: AsyncSession, session_id: str, user_id: str) -> bool:
    result = await session.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False

    if row.revoked_at is None:
        row.revoked_at = utc_now()
        await session.commit()

    return True


async def list_user_sessions(
    session: AsyncSession,
    user_id: str,
) -> list[AuthSession]:
    result = await session.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user_id)
        .order_by(AuthSession.created_at.desc())
    )
    return list(result.scalars().all())
