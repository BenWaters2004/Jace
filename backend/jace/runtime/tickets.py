from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _hash(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


@dataclass(slots=True)
class RuntimeStreamTicket:
    token_hash: str
    user_id: str | None
    expires_at: datetime


class RuntimeStreamTicketManager:
    def __init__(self) -> None:
        self._tickets: dict[
            str,
            RuntimeStreamTicket,
        ] = {}
        self._lock = asyncio.Lock()

    async def issue(
        self,
        *,
        user_id: str | None,
        ttl_seconds: int = 60,
    ) -> tuple[str, datetime]:
        raw = (
            "jace_stream_"
            + secrets.token_urlsafe(
                32
            )
        )
        token_hash = _hash(
            raw
        )
        expires_at = (
            _utc_now()
            + timedelta(
                seconds=max(
                    10,
                    min(
                        ttl_seconds,
                        300,
                    ),
                )
            )
        )

        ticket = RuntimeStreamTicket(
            token_hash=token_hash,
            user_id=user_id,
            expires_at=expires_at,
        )

        async with self._lock:
            self._purge_locked()
            self._tickets[
                token_hash
            ] = ticket

        return raw, expires_at

    async def consume(
        self,
        token: str | None,
    ) -> RuntimeStreamTicket | None:
        if not token:
            return None

        token_hash = _hash(
            token
        )

        async with self._lock:
            self._purge_locked()

            ticket = self._tickets.pop(
                token_hash,
                None,
            )

        if ticket is None:
            return None

        if ticket.expires_at <= _utc_now():
            return None

        return ticket

    def _purge_locked(self) -> None:
        now = _utc_now()

        expired = [
            key
            for key, ticket
            in self._tickets.items()
            if ticket.expires_at <= now
        ]

        for key in expired:
            self._tickets.pop(
                key,
                None,
            )


runtime_stream_tickets = (
    RuntimeStreamTicketManager()
)
