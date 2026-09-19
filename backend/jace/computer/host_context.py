from __future__ import annotations

# JACE_STEP4B2_V3_HOST_CONTEXT

import ntpath
import re
from pathlib import PureWindowsPath
from typing import Any

from jace.computer.host_request import extract_explicit_host_path


_FILENAME_RE = re.compile(
    r'''(?i)(?:"|')?(?P<name>[^\\/:*?"<>|\r\n]+\.(?:'''
    r'''txt|md|markdown|csv|json|xml|html?|log|ini|cfg|conf|ya?ml|toml|'''
    r'''py|php|js|jsx|ts|tsx|css|scss|sql|sh|ps1|bat|cmd|java|c|h|cpp|hpp|'''
    r'''cs|go|rs|rb|swift|kt|docx|pdf|png|jpe?g|webp|gif|bmp|wav|mp3|m4a|'''
    r'''flac|ogg|oga|webm|aac|wma'''
    r'''))(?:"|')?(?:[.!?;,]*)\s*$'''
)


def _history_without_current(
    history: list[dict[str, Any]],
    current_message: str,
) -> list[dict[str, Any]]:
    if not history:
        return []

    result = list(history)

    if (
        result
        and result[-1].get("role") == "user"
        and str(result[-1].get("content") or "").strip()
        == current_message.strip()
    ):
        result = result[:-1]

    return result


def _filename_from_followup(
    message: str,
) -> str | None:
    text = (
        message
        or ""
    ).strip()

    if not text:
        return None

    if extract_explicit_host_path(
        text
    ):
        return None

    candidate = re.sub(
        r"(?i)^\s*(?:okay[, ]*|ok[, ]*)?"
        r"(?:please\s+)?"
        r"(?:read|open|inspect|view|show|describe|analyse|analyze|"
        r"summarise|summarize|transcribe)\s+",
        "",
        text,
        count=1,
    ).strip()

    candidate = candidate.strip(
        " \t\r\n\"'"
    )
    candidate = re.sub(
        r"[.!?;,]+$",
        "",
        candidate,
    ).strip()

    match = _FILENAME_RE.fullmatch(
        candidate
    )

    if not match:
        return None

    name = match.group(
        "name"
    ).strip()

    if "\\" in name or "/" in name:
        return None

    return name


def _directory_from_prior_host_path(
    value: str,
) -> str | None:
    path = extract_explicit_host_path(value)

    if not path:
        return None

    name = ntpath.basename(path)
    _, extension = ntpath.splitext(name)

    if extension:
        parent = ntpath.dirname(path)
        return parent or None

    return path


def host_context_message(
    current_message: str,
    history: list[dict[str, Any]],
) -> str:
    current = (current_message or "").strip()

    filename = _filename_from_followup(current)

    if not filename:
        return current

    prior = _history_without_current(
        history,
        current,
    )

    for message in reversed(prior[-12:]):
        if str(message.get("role") or "") != "user":
            continue

        content = str(message.get("content") or "").strip()

        if not content:
            continue

        directory = _directory_from_prior_host_path(
            content
        )

        if not directory:
            continue

        full_path = str(
            PureWindowsPath(directory)
            / filename
        )

        return (
            current
            + "\n\nHOST FILE CONTEXT\n"
            + f"Resolved path: {full_path}"
        )

    return current
