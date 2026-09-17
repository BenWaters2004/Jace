from __future__ import annotations

# JACE_STEP4C5A_CALENDAR_TARGET_RESOLUTION

from dataclasses import dataclass
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jace.calendar.models import CalendarEvent, CalendarSource


@dataclass(frozen=True, slots=True)
class CalendarModifyTargetHint:
    provider_id: str
    connection_id: str
    account_hint: str | None
    event_id: str
    title: str


_ACTION_RE = re.compile(
    r"\b(?:move|reschedule|update|change|edit|cancel|delete|remove)\b",
    re.IGNORECASE,
)

_QUOTED_RE = re.compile(
    r'''["'“”‘’]([^"'“”‘’]{2,300})["'“”‘’]'''
)

_TRAILING_CHANGE_RE = re.compile(
    r"\s+(?:to|from|on|at)\s+"
    r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
    r"today|tomorrow|yesterday|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"next\b.*|this\b.*)$",
    re.IGNORECASE,
)


def candidate_phrases(message: str) -> list[str]:
    phrases: list[str] = []

    for match in _QUOTED_RE.finditer(message):
        value = match.group(1).strip()
        if value and value not in phrases:
            phrases.append(value)

    action = _ACTION_RE.search(message)
    if action:
        tail = message[action.end():].strip()
        tail = re.sub(
            r"^(?:the|my)\s+",
            "",
            tail,
            flags=re.IGNORECASE,
        )
        tail = _TRAILING_CHANGE_RE.sub("", tail).strip(
            " .,:;!?\"'“”‘’"
        )

        if (
            len(tail) >= 2
            and tail not in phrases
            and not re.fullmatch(
                r"(?:it|this|that|event|meeting|appointment)",
                tail,
                flags=re.IGNORECASE,
            )
        ):
            phrases.append(tail)

    return phrases[:4]


def _unique_targets(rows) -> list[CalendarModifyTargetHint]:
    result: list[CalendarModifyTargetHint] = []
    seen: set[tuple[str, str, str]] = set()

    for event, source in rows:
        connection_id = source.connection_id
        if not connection_id:
            continue

        key = (
            source.provider_id,
            connection_id,
            event.id,
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(
            CalendarModifyTargetHint(
                provider_id=source.provider_id,
                connection_id=connection_id,
                account_hint=source.account_hint,
                event_id=event.id,
                title=event.title,
            )
        )

    return result


async def infer_calendar_modify_target(
    session: AsyncSession,
    message: str,
) -> CalendarModifyTargetHint | None:
    """
    Resolve a uniquely named cached external event to the backend-owned
    provider connection. The model never chooses the connection ID.
    """
    if not _ACTION_RE.search(message):
        return None

    phrases = candidate_phrases(message)
    if not phrases:
        return None

    for phrase in phrases:
        statement = (
            select(CalendarEvent, CalendarSource)
            .join(
                CalendarSource,
                CalendarEvent.source_id == CalendarSource.id,
            )
            .where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.status != "cancelled",
                CalendarSource.enabled.is_(True),
                CalendarSource.provider_id.in_(("google", "microsoft")),
                CalendarSource.connection_id.is_not(None),
                func.lower(CalendarEvent.title) == phrase.casefold(),
            )
        )

        rows = list((await session.execute(statement)).all())
        unique = _unique_targets(rows)

        if len(unique) == 1:
            return unique[0]
        if len(unique) > 1:
            return None

    for phrase in phrases:
        if len(phrase) < 4:
            continue

        statement = (
            select(CalendarEvent, CalendarSource)
            .join(
                CalendarSource,
                CalendarEvent.source_id == CalendarSource.id,
            )
            .where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.status != "cancelled",
                CalendarSource.enabled.is_(True),
                CalendarSource.provider_id.in_(("google", "microsoft")),
                CalendarSource.connection_id.is_not(None),
                func.lower(CalendarEvent.title).contains(phrase.casefold()),
            )
            .limit(12)
        )

        rows = list((await session.execute(statement)).all())
        unique = _unique_targets(rows)

        if len(unique) == 1:
            return unique[0]
        if len(unique) > 1:
            return None

    return None
