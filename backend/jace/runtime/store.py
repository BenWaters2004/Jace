from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select

from jace.config import settings
from jace.database import SessionLocal
from jace.db.models import RuntimeEventRecord, utc_now


_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "password",
    "secret",
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "client_secret",
    "device_token",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}

        for key, item in value.items():
            normalised = str(key).strip().casefold()

            if (
                normalised in _SECRET_KEYS
                or normalised.endswith("_token")
                or normalised.endswith("_secret")
                or normalised.endswith("_password")
                or normalised.endswith("_api_key")
            ):
                output[str(key)] = "<redacted>"
            else:
                output[str(key)] = _redact(item)

        return output

    if isinstance(value, list):
        return [_redact(item) for item in value]

    if isinstance(value, tuple):
        return [_redact(item) for item in value]

    return value


def _scope(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)

    if value is None:
        return None

    rendered = str(value).strip()

    return rendered[:100] if rendered else None


def record_to_event(
    row: RuntimeEventRecord,
) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json)
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    return {
        "type": row.event_type,
        "event_id": row.event_id,
        "sequence": row.sequence,
        "timestamp": row.created_at.isoformat(),
        "durable": True,
        **payload,
    }


async def append_runtime_event(
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    safe_payload = _redact(dict(payload))

    row = RuntimeEventRecord(
        event_type=event_type[:160],
        payload_json=json.dumps(
            safe_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ),
        conversation_id=_scope(
            safe_payload,
            "conversation_id",
        ),
        project_id=_scope(
            safe_payload,
            "project_id",
        ),
        workflow_id=_scope(
            safe_payload,
            "workflow_id",
        ),
        task_id=_scope(
            safe_payload,
            "task_id",
        ),
        agent_id=_scope(
            safe_payload,
            "agent_id",
        ),
        device_id=_scope(
            safe_payload,
            "device_id",
        ),
        request_id=_scope(
            safe_payload,
            "request_id",
        ),
        created_at=utc_now(),
    )

    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return record_to_event(row)


async def replay_runtime_events(
    *,
    after_sequence: int = 0,
    through_sequence: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    maximum = max(
        1,
        min(
            int(limit or settings.runtime_event_replay_limit),
            settings.runtime_event_replay_limit,
        ),
    )

    statement = (
        select(RuntimeEventRecord)
        .where(
            RuntimeEventRecord.sequence
            > max(0, int(after_sequence))
        )
        .order_by(
            RuntimeEventRecord.sequence.asc()
        )
        .limit(maximum)
    )

    if through_sequence is not None:
        statement = statement.where(
            RuntimeEventRecord.sequence
            <= int(through_sequence)
        )

    async with SessionLocal() as session:
        result = await session.execute(
            statement
        )

        return [
            record_to_event(row)
            for row in result.scalars().all()
        ]


async def latest_runtime_event() -> dict[str, Any] | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(RuntimeEventRecord)
            .order_by(
                RuntimeEventRecord.sequence.desc()
            )
            .limit(1)
        )

        row = result.scalar_one_or_none()

    return (
        record_to_event(row)
        if row is not None
        else None
    )


async def latest_state_event() -> dict[str, Any] | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(RuntimeEventRecord)
            .where(
                RuntimeEventRecord.event_type
                == "jace.state.changed"
            )
            .order_by(
                RuntimeEventRecord.sequence.desc()
            )
            .limit(1)
        )

        row = result.scalar_one_or_none()

    return (
        record_to_event(row)
        if row is not None
        else None
    )


async def prune_runtime_events() -> int:
    days = max(
        1,
        int(
            settings.runtime_event_retention_days
        ),
    )

    cutoff = utc_now() - timedelta(
        days=days
    )

    async with SessionLocal() as session:
        result = await session.execute(
            delete(RuntimeEventRecord).where(
                RuntimeEventRecord.created_at
                < cutoff
            )
        )
        await session.commit()

    return int(
        result.rowcount or 0
    )
