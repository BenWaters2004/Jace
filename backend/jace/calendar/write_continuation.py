from __future__ import annotations

# JACE_STEP4C5B_V2_CALENDAR_WRITE_CONTINUATION

import re
from typing import Any


_WRITE = re.compile(
    r"\b(?:create|add|schedule|book|make|put|reschedule|move|update|change|"
    r"edit|cancel|delete|remove|invite|set)\b"
    r".{0,200}\b(?:calendar|event|meeting|appointment|series|occurrence|"
    r"attendee|attendees|guest|guests|reminder|reminders|google meet|"
    r"meet link|teams|teams link|online meeting)\b",
    re.IGNORECASE | re.DOTALL,
)

_CONTINUATION = re.compile(
    r"^\s*(?:"
    r"yes|yeah|yep|correct|confirmed|"
    r"okay(?:,)?\s+try\s+again|ok(?:ay)?\s+try\s+again|try\s+again|"
    r"go\s+ahead|proceed|do\s+it|please\s+do|"
    r"same\s+(?:details|parameters)|"
    r"sounds\s+good|that(?:'s| is)\s+(?:good|right|correct)|"
    r"tomorrow(?:'s| is)\s+good|that\s+date\s+is\s+good"
    r")\s*[.!?]*\s*$",
    re.IGNORECASE,
)

_UNRESOLVED_ASSISTANT = re.compile(
    r"\?|"
    r"\b(?:"
    r"try again|retry|need|needs|confirm|confirmation|clarify|"
    r"failed|failure|didn't|did not|couldn't|could not|"
    r"not execute|not executed|not created|not scheduled|"
    r"syntax|parameter|format|permission|scope|"
    r"proceed|go ahead|tomorrow still good"
    r")\b",
    re.IGNORECASE,
)


def is_calendar_write_request(
    text: str,
) -> bool:
    return bool(
        _WRITE.search(
            text or ""
        )
    )


def is_explicit_write_continuation(
    text: str,
) -> bool:
    return bool(
        _CONTINUATION.fullmatch(
            text or ""
        )
    )


def _history_without_current(
    history: list[dict[str, Any]],
    current_message: str,
) -> list[dict[str, Any]]:
    if not history:
        return []

    result = list(
        history
    )

    if (
        result
        and result[-1].get(
            "role"
        )
        == "user"
        and str(
            result[-1].get(
                "content"
            )
            or ""
        ).strip()
        == current_message.strip()
    ):
        result = result[:-1]

    return result


def calendar_capability_message(
    current_message: str,
    history: list[dict[str, Any]],
) -> str:
    """
    Carry a recent unresolved Calendar write request through an explicit short
    confirmation/retry turn.

    This deliberately does *not* treat complaints such as "still not there" as
    authorization to retry a write. Only explicit continuations inherit intent.
    """
    current = (
        current_message
        or ""
    ).strip()

    if is_calendar_write_request(
        current
    ):
        return current

    if not is_explicit_write_continuation(
        current
    ):
        return current

    prior = _history_without_current(
        history,
        current,
    )

    recent_assistant: str | None = None
    original_write: str | None = None

    # Look back only a short distance so unrelated old Calendar writes cannot
    # be revived accidentally.
    for message in reversed(
        prior[-8:]
    ):
        role = str(
            message.get(
                "role"
            )
            or ""
        )
        content = str(
            message.get(
                "content"
            )
            or ""
        ).strip()

        if not content:
            continue

        if (
            recent_assistant is None
            and role
            == "assistant"
        ):
            recent_assistant = content
            continue

        if (
            role
            == "user"
            and is_calendar_write_request(
                content
            )
        ):
            original_write = content
            break

    if not original_write:
        return current

    # Require evidence that the previous assistant turn was unresolved or
    # explicitly asking for clarification/confirmation.
    if (
        recent_assistant is None
        or not _UNRESOLVED_ASSISTANT.search(
            recent_assistant
        )
    ):
        return current

    return (
        original_write
        + "\n\nCALENDAR WRITE CONTINUATION\n"
        + current
    )
