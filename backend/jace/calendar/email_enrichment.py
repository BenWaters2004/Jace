from __future__ import annotations

# JACE_STEP4C4E_GMAIL_EVENT_ENRICHMENT

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from jace.calendar.models import CalendarEvent
from jace.connections.oauth import valid_access_token
from jace.connections.service import get_connection
from jace.tools.gmail import (
    _get_message,
    _gmail_get,
    _message_summary,
)


STOP_WORDS = {
    "about",
    "after",
    "before",
    "calendar",
    "event",
    "from",
    "gmail",
    "into",
    "the",
    "this",
    "through",
    "train",
    "with",
    "your",
}

DETAIL_LABELS = (
    "booking reference",
    "booking ref",
    "reference",
    "reservation",
    "confirmation",
    "departure",
    "depart",
    "arrival",
    "arrive",
    "platform",
    "coach",
    "carriage",
    "seat",
    "ticket",
    "journey",
    "origin",
    "destination",
    "from",
    "to",
)


class CalendarEmailEnrichmentError(RuntimeError):
    pass


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _keywords(value: str) -> list[str]:
    result: list[str] = []

    for token in re.findall(
        r"[A-Za-z0-9][A-Za-z0-9'&.-]{2,}",
        value,
    ):
        cleaned = token.casefold().strip(".-")

        if (
            len(cleaned) < 4
            or cleaned in STOP_WORDS
            or cleaned in result
        ):
            continue

        result.append(cleaned)

    return result


def _quoted(value: str) -> str:
    return '"' + value.replace('"', " ").strip() + '"'


def _search_queries(
    event: CalendarEvent,
) -> list[str]:
    title = event.title.strip()
    location = event.location.strip()

    title_terms = _keywords(title)
    location_terms = _keywords(location)

    date_filter = ""

    event_date: datetime | None = None

    if event.start_at is not None:
        event_date = event.start_at
    elif event.start_date is not None:
        event_date = datetime.combine(
            event.start_date,
            datetime.min.time(),
        )

    if event_date is not None:
        before = (
            event_date
            + timedelta(days=2)
        ).strftime("%Y/%m/%d")
        after = (
            event_date
            - timedelta(days=120)
        ).strftime("%Y/%m/%d")
        date_filter = (
            f" after:{after} before:{before}"
        )

    queries: list[str] = []

    if title:
        queries.append(
            f"in:anywhere {_quoted(title)}{date_filter}"
        )

    if title_terms:
        queries.append(
            "in:anywhere "
            + " ".join(
                title_terms[:4]
            )
            + date_filter
        )

    if location:
        queries.append(
            f"in:anywhere {_quoted(location)}{date_filter}"
        )

    combined = (
        title_terms[-2:]
        + location_terms[:2]
    )

    if combined:
        queries.append(
            "in:anywhere "
            + " ".join(combined)
            + date_filter
        )

    # Keep query count bounded and deterministic.
    unique: list[str] = []

    for query in queries:
        if query not in unique:
            unique.append(query)

    return unique[:4]


def _date_markers(
    event: CalendarEvent,
) -> list[str]:
    value = event.start_at

    if value:
        try:
            parsed = datetime.fromisoformat(
                value.isoformat()
                if isinstance(value, datetime)
                else str(value)
            )
        except ValueError:
            parsed = None
    else:
        parsed = None

    if parsed is None and event.start_date:
        try:
            parsed = datetime.fromisoformat(
                event.start_date.isoformat()
            )
        except ValueError:
            parsed = None

    if parsed is None:
        return []

    return [
        parsed.strftime("%Y-%m-%d").casefold(),
        parsed.strftime("%d/%m/%Y").casefold(),
        parsed.strftime("%d %B %Y").casefold(),
        parsed.strftime("%d %b %Y").casefold(),
        f"{parsed.day} {parsed.strftime('%B %Y')}".casefold(),
    ]


def _score_message(
    event: CalendarEvent,
    summary: dict[str, Any],
) -> tuple[int, list[str]]:
    subject = str(
        summary.get("subject")
        or ""
    ).casefold()
    body = str(
        summary.get("body")
        or ""
    ).casefold()
    snippet = str(
        summary.get("snippet")
        or ""
    ).casefold()

    haystack = "\n".join(
        (
            subject,
            body,
            snippet,
        )
    )

    title = event.title.strip().casefold()
    location = event.location.strip().casefold()
    title_terms = _keywords(
        event.title
    )
    location_terms = _keywords(
        event.location
    )

    score = 0
    reasons: list[str] = []

    if title and title in subject:
        score += 12
        reasons.append(
            "title in email subject"
        )
    elif title and title in haystack:
        score += 7
        reasons.append(
            "event title in email"
        )

    for term in title_terms:
        if term in subject:
            score += 4
            reasons.append(
                f"title term {term}"
            )
        elif term in haystack:
            score += 2

    if location:
        if location in haystack:
            score += 8
            reasons.append(
                "event location in email"
            )
        else:
            for term in location_terms:
                if term in haystack:
                    score += 3

    for marker in _date_markers(
        event
    ):
        if marker and marker in haystack:
            score += 3
            reasons.append(
                "event date in email"
            )
            break

    if event.start_at is not None:
        start_value = event.start_at

        try:
            zone = ZoneInfo(
                event.timezone
                or "Europe/London"
            )
        except ZoneInfoNotFoundError:
            zone = ZoneInfo(
                "Europe/London"
            )

        if start_value.tzinfo is None:
            start_value = start_value.replace(
                tzinfo=ZoneInfo("UTC")
            )

        time_marker = start_value.astimezone(
            zone
        ).strftime(
            "%H:%M"
        )

        if time_marker in haystack:
            score += 4
            reasons.append(
                "event time in email"
            )

    return score, reasons


def _extract_details(
    body: str,
) -> list[dict[str, str]]:
    details: list[
        dict[str, str]
    ] = []
    seen: set[
        tuple[str, str]
    ] = set()

    lines = [
        re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
        for line in body.splitlines()
    ]

    for line in lines:
        if (
            not line
            or len(line) > 260
        ):
            continue

        lower = line.casefold()

        if not any(
            label in lower
            for label in DETAIL_LABELS
        ):
            continue

        match = re.match(
            r"^([^:–—-]{2,45})\s*[:–—-]\s*(.+)$",
            line,
        )

        if match:
            label = match.group(
                1
            ).strip()
            value = match.group(
                2
            ).strip()
        else:
            # Keep particularly useful travel/booking lines even when the
            # supplier doesn't format them as key:value.
            label = "Detail"
            value = line

        key = (
            label.casefold(),
            value.casefold(),
        )

        if key in seen:
            continue

        seen.add(key)
        details.append(
            {
                "label": label,
                "value": value,
            }
        )

        if len(details) >= 16:
            break

    return details


def _is_from_gmail(
    event: CalendarEvent,
) -> bool:
    if event.source.provider_id != "google":
        return False

    metadata = _json_object(
        event.metadata_json
    )
    provider_data = _json_object(
        event.provider_data_json
    )

    event_type = (
        metadata.get(
            "event_type"
        )
        or provider_data.get(
            "eventType"
        )
    )

    if event_type == "fromGmail":
        return True

    description = (
        event.description
        or ""
    ).casefold()

    return (
        "created from an email"
        in description
        and "gmail"
        in description
    )


async def enrich_calendar_event_from_email(
    session: AsyncSession,
    event: CalendarEvent,
    *,
    display_timezone: str,
) -> dict[str, Any]:
    if not _is_from_gmail(
        event
    ):
        return {
            "event_id": event.id,
            "status": "not_applicable",
            "confidence": "none",
            "display_timezone": display_timezone,
            "source_email": None,
            "details": [],
            "match_reasons": [],
        }

    connection_id = (
        event.source.connection_id
    )

    if not connection_id:
        raise CalendarEmailEnrichmentError(
            "This Google calendar is not linked to a current Google connection."
        )

    connection = await get_connection(
        session,
        connection_id,
    )

    if (
        connection is None
        or connection.provider_id
        != "google"
        or connection.status
        != "configured"
    ):
        raise CalendarEmailEnrichmentError(
            "The Google account for this calendar is not currently connected."
        )

    try:
        access_token = await valid_access_token(
            session,
            connection,
        )
    except Exception as exc:
        raise CalendarEmailEnrichmentError(
            f"Google authorization is not usable: {exc}"
        ) from exc

    candidate_ids: list[str] = []

    for query in _search_queries(
        event
    ):
        listed = await _gmail_get(
            access_token,
            "/users/me/messages",
            params={
                "q": query,
                "maxResults": 10,
                "includeSpamTrash": True,
            },
        )

        refs = listed.get(
            "messages"
        )

        if not isinstance(
            refs,
            list,
        ):
            continue

        for ref in refs:
            if not isinstance(
                ref,
                dict,
            ):
                continue

            message_id = ref.get(
                "id"
            )

            if (
                isinstance(
                    message_id,
                    str,
                )
                and message_id
                not in candidate_ids
            ):
                candidate_ids.append(
                    message_id
                )

            if len(
                candidate_ids
            ) >= 20:
                break

        if len(
            candidate_ids
        ) >= 20:
            break

    best_summary: dict[
        str,
        Any
    ] | None = None
    best_score = -1
    best_reasons: list[
        str
    ] = []

    for message_id in candidate_ids:
        message = await _get_message(
            access_token,
            message_id,
            full=True,
        )
        summary = _message_summary(
            message,
            include_body=True,
        )
        score, reasons = _score_message(
            event,
            summary,
        )

        if score > best_score:
            best_score = score
            best_summary = summary
            best_reasons = reasons

    if (
        best_summary is None
        or best_score < 7
    ):
        return {
            "event_id": event.id,
            "status": "no_match",
            "confidence": "none",
            "display_timezone": display_timezone,
            "source_email": None,
            "details": [],
            "match_reasons": [],
        }

    confidence = (
        "high"
        if best_score >= 18
        else "medium"
        if best_score >= 11
        else "low"
    )

    body = str(
        best_summary.get(
            "body"
        )
        or ""
    )

    return {
        "event_id": event.id,
        "status": "matched",
        "confidence": confidence,
        "display_timezone": display_timezone,
        "source_email": {
            "id": best_summary.get(
                "id"
            ),
            "thread_id": best_summary.get(
                "thread_id"
            ),
            "from": best_summary.get(
                "from"
            ),
            "to": best_summary.get(
                "to"
            ),
            "subject": best_summary.get(
                "subject"
            ),
            "received_at": best_summary.get(
                "received_at"
            ),
            "snippet": best_summary.get(
                "snippet"
            ),
            "body": body,
        },
        "details": _extract_details(
            body
        ),
        "match_reasons": best_reasons[
            :8
        ],
    }
