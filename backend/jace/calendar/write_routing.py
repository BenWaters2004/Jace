from __future__ import annotations

# JACE_STEP4C5B_DETERMINISTIC_WRITE_ROUTING

import re
from typing import Iterable, Literal


CalendarWriteKind = Literal[
    "create",
    "modify",
]


_STRONG_CREATE = re.compile(
    r"\b(?:create|schedule|book|make)\b"
    r".{0,160}\b(?:calendar|event|meeting|appointment)\b",
    re.IGNORECASE,
)

_CREATE = re.compile(
    r"\b(?:create|add|schedule|book|make|put)\b"
    r".{0,160}\b(?:calendar|event|meeting|appointment)\b"
    r"|\b(?:calendar|event|meeting|appointment)\b"
    r".{0,100}\b(?:create|add|schedule|book|make)\b",
    re.IGNORECASE,
)

_MODIFY = re.compile(
    r"\b(?:reschedule|move|update|change|edit|cancel|delete|remove)\b"
    r".{0,180}\b(?:calendar|event|meeting|appointment|series|occurrence)\b"
    r"|\b(?:reschedule|move|change)\b.{0,140}\b(?:to|from|at)\s+"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b"
    r"|\b(?:invite|add|remove)\b.{0,140}\b"
    r"(?:attendee|attendees|guest|guests|invitee|invitees|[^@\s]+@[^@\s]+)"
    r"|\b(?:make|set|change|update)\b.{0,140}\b"
    r"(?:recurring|recurrence|repeat|repeating)\b"
    r"|\b(?:add|set|change|remove)\b.{0,140}\b(?:reminder|reminders)\b"
    r"|\b(?:add|create|remove)\b.{0,140}\b"
    r"(?:google meet|meet link|teams|teams link|online meeting)\b",
    re.IGNORECASE,
)

_RELATIVE_DATE = re.compile(
    r"\b(?:today|yesterday|tomorrow|tonight|"
    r"day before yesterday|day after tomorrow|"
    r"this (?:week|weekend|morning|afternoon|evening)|"
    r"next (?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"in \d+ (?:minutes?|hours?|days?))\b",
    re.IGNORECASE,
)

_CONFLICT = re.compile(
    r"\b(?:conflict|clash|free|busy|availability|available)\b",
    re.IGNORECASE,
)


def calendar_write_kind(
    message: str,
) -> CalendarWriteKind | None:
    text = " ".join(
        (message or "").strip().split()
    )

    if not text:
        return None

    # A strong create phrase wins even when the same request also includes
    # attendee/reminder/recurrence instructions for the new event.
    if _STRONG_CREATE.search(text):
        return "create"

    # Otherwise scheduling-detail verbs usually refer to an existing event,
    # e.g. "Invite Bob to the meeting" or "add a reminder".
    if _MODIFY.search(text):
        return "modify"

    if _CREATE.search(text):
        return "create"

    return None


def compact_calendar_write_tools(
    message: str,
    routed_tools: Iterable[str],
    capability_tools: Iterable[str],
) -> list[str]:
    """
    Keep a calendar write turn small enough for local models to use reliably.

    This activates only when the runtime capability resolver has actually
    supplied an executable external calendar write tool. It never manufactures
    a provider tool and cannot bypass scope/connection/permission resolution.
    """
    kind = calendar_write_kind(
        message
    )

    routed = set(
        routed_tools
    )
    capability = set(
        capability_tools
    )

    if kind is None:
        return sorted(
            routed
        )

    expected_suffix = (
        "_calendar_create_event"
        if kind == "create"
        else "_calendar_modify_event"
    )

    write_tools = {
        name
        for name in capability
        if name.endswith(
            expected_suffix
        )
    }

    if not write_tools:
        # Preserve the normal routing and the capability-resolution prompt when
        # no executable write tool was resolved. This lets Jace explain a
        # missing scope/account/permission accurately.
        return sorted(
            routed
        )

    selected = set(
        write_tools
    )

    if _RELATIVE_DATE.search(
        message
    ):
        selected.add(
            "current_datetime"
        )

    if kind == "modify":
        # Modification first needs a stable local event ID. Keep the focused
        # lookup tools, not every Calendar Intelligence schema.
        selected.add(
            "calendar_find_event"
        )
        selected.add(
            "calendar_list_events"
        )

    if _CONFLICT.search(
        message
    ):
        selected.add(
            "calendar_check_conflicts"
        )

    return sorted(
        selected
    )
